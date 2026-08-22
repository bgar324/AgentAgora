import re
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal, Protocol

import numpy as np
from numpy.typing import NDArray
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from agora.schemas.panel import Observation
from agora.schemas.research import PaperCorpus, Snippet

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_BATCH = 512
RRF_K = 60
SHORTLIST = 24
KEYWORD_TERMS = 24

SearchMethod = Literal[
    "vector",
    "keyword",
    "hybrid",
]

Embedder = Callable[[Sequence[str]], Awaitable[NDArray[np.float64]]]


class SnippetMatch(BaseModel):
    snippet: Snippet
    score: float
    observations: list[Observation] = Field(default_factory=list)


class KnowledgeSearch(Protocol):
    async def search(
        self,
        query: str,
        *,
        investigation_id: str,
        corpus_id: str,
        source_ids: Sequence[str],
        method: SearchMethod,
        limit: int,
        per_source: int = 1,
    ) -> list[SnippetMatch]:
        ...


def unit_rows(X: NDArray) -> NDArray[np.float64]:
    X = np.asarray(X, dtype=np.float64)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    return X / np.where(norms == 0.0, 1.0, norms)


async def embed_texts(
    texts: Sequence[str],
    *,
    client: AsyncOpenAI,
    model: str = EMBEDDING_MODEL,
) -> NDArray[np.float64]:
    if not texts:
        return np.zeros((0, 0))

    vectors: list[list[float]] = []

    for start in range(0, len(texts), EMBEDDING_BATCH):
        response = await client.embeddings.create(
            model=model,
            input=list(texts[start : start + EMBEDDING_BATCH]),
        )
        vectors.extend(
            item.embedding
            for item in sorted(response.data, key=lambda item: item.index)
        )

    return unit_rows(np.asarray(vectors))


def snippet_id(source_id: str, location: str) -> str:
    return f"snippet_{source_id}_{location}"


def index_corpus(db: sqlite3.Connection, corpus: PaperCorpus) -> int:
    rows = []

    for paper in corpus.papers:
        text = " ".join((paper.abstract or "").split())

        if not text:
            continue

        rows.append(
            (
                snippet_id(paper.source_id, "abstract"),
                paper.source_id,
                paper.title.strip(),
                "abstract",
                text,
            )
        )

    with db:
        db.executemany(
            "insert or ignore into snippets values (?,?,?,?,?)",
            rows,
        )
        db.execute("insert into snippets_fts(snippets_fts) values('rebuild')")

    return db.execute("select count(*) from snippets").fetchone()[0]


async def embed_snippets(db: sqlite3.Connection, *, embed: Embedder) -> int:
    pending = db.execute(
        "select snippet_id, text from snippets "
        "where snippet_id not in (select snippet_id from snippet_vec)"
    ).fetchall()

    if not pending:
        return 0

    X = await embed([row["text"] for row in pending])

    with db:
        db.executemany(
            "insert or replace into snippet_vec values (?,?,?)",
            [
                (
                    row["snippet_id"],
                    X.shape[1],
                    X[i].astype(np.float32).tobytes(),
                )
                for i, row in enumerate(pending)
            ],
        )

    return len(pending)


class SnippetIndex:
    def __init__(self, connection: sqlite3.Connection, embed: Embedder):
        self.db = connection
        self.embed = embed

    def candidates(self, source_ids: Sequence[str]) -> list[sqlite3.Row]:
        placeholders = ",".join("?" * len(source_ids))
        return self.db.execute(
            "select snippet_id, source_id, title, location, text from snippets "
            f"where source_id in ({placeholders})",
            tuple(source_ids),
        ).fetchall()

    async def vector_scores(
        self,
        query: str,
        rows: Sequence[sqlite3.Row],
        limit: int,
    ) -> list[tuple[sqlite3.Row, float]]:
        if not rows:
            return []

        ids = [row["snippet_id"] for row in rows]
        placeholders = ",".join("?" * len(ids))
        stored = self.db.execute(
            "select snippet_id, vec from snippet_vec "
            f"where snippet_id in ({placeholders})",
            ids,
        ).fetchall()
        vectors = {
            row["snippet_id"]: np.frombuffer(row["vec"], dtype=np.float32)
            for row in stored
        }
        kept = [row for row in rows if row["snippet_id"] in vectors]

        if not kept:
            return []

        V = np.stack([vectors[row["snippet_id"]] for row in kept]).astype(
            np.float64
        )
        q = (await self.embed([query]))[0]
        similarity = V @ q
        order = np.argsort(-similarity)[:limit]

        return [(kept[i], float(similarity[i])) for i in order]

    def keyword_scores(
        self,
        query: str,
        rows: Sequence[sqlite3.Row],
        limit: int,
    ) -> list[tuple[sqlite3.Row, float]]:
        by_id = {row["snippet_id"]: row for row in rows}
        words = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", query)[:KEYWORD_TERMS]
        terms = " OR ".join(f'"{word}"' for word in words)

        if not terms or not rows:
            return []

        matched = self.db.execute(
            "select s.snippet_id, bm25(snippets_fts) rank from snippets_fts "
            "join snippets s on s.rowid = snippets_fts.rowid "
            "where snippets_fts match ? order by rank limit ?",
            (terms, limit * 8),
        ).fetchall()

        return [
            (by_id[m["snippet_id"]], -float(m["rank"]))
            for m in matched
            if m["snippet_id"] in by_id
        ][:limit]

    def stored_observations(self, snippet_id: str) -> list[Observation]:
        rows = self.db.execute(
            "select observation_id, source_id, location, text from observations "
            "where snippet_id = ?",
            (snippet_id,),
        ).fetchall()
        return [
            Observation(
                id=row["observation_id"],
                text=row["text"],
                source_id=row["source_id"],
                location=row["location"],
            )
            for row in rows
        ]

    async def search(
        self,
        query: str,
        *,
        investigation_id: str,
        corpus_id: str,
        source_ids: Sequence[str],
        method: SearchMethod,
        limit: int,
        per_source: int = 1,
    ) -> list[SnippetMatch]:
        rows = self.candidates(source_ids)

        if method == "vector":
            ranked = await self.vector_scores(query, rows, SHORTLIST)
        elif method == "keyword":
            ranked = self.keyword_scores(query, rows, SHORTLIST)
        else:
            fused: dict[str, float] = {}
            keep: dict[str, sqlite3.Row] = {}
            pools = (
                await self.vector_scores(query, rows, SHORTLIST),
                self.keyword_scores(query, rows, SHORTLIST),
            )

            for pool in pools:
                for rank, (row, _) in enumerate(pool):
                    fused[row["snippet_id"]] = (
                        fused.get(row["snippet_id"], 0.0) + 1.0 / (RRF_K + rank)
                    )
                    keep[row["snippet_id"]] = row

            ranked = [
                (keep[sid], score)
                for sid, score in sorted(fused.items(), key=lambda kv: -kv[1])[
                    :SHORTLIST
                ]
            ]

        taken: dict[str, int] = {}
        matches: list[SnippetMatch] = []

        for row, score in ranked:
            if taken.get(row["source_id"], 0) >= per_source:
                continue

            taken[row["source_id"]] = taken.get(row["source_id"], 0) + 1
            matches.append(
                SnippetMatch(
                    snippet=Snippet(
                        id=row["snippet_id"],
                        source_id=row["source_id"],
                        title=row["title"],
                        text=row["text"],
                        location=row["location"],
                    ),
                    score=score,
                    observations=self.stored_observations(row["snippet_id"]),
                )
            )

            if len(matches) == limit:
                break

        return matches
