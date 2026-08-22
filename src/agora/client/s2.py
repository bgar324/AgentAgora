import hashlib
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from agora.client.base import BaseAPIClient
from agora.client.cache import FileCache
from agora.config.settings import SemanticScholarSettings
from agora.core.errors import ClientError
from agora.schemas.research import AcademicField, Paper, SearchHit, Snippet

logger = logging.getLogger("agora.client.s2")

SNIPPET_SEARCH_PATH = "/graph/v1/snippet/search"
PAPER_SEARCH_PATH = "/graph/v1/paper/search"
PAPER_BATCH_PATH = "/graph/v1/paper/batch"

SNIPPET_SEARCH_LIMIT = 1_000
PAPER_SEARCH_LIMIT = 100
PAPER_BATCH_LIMIT = 500

SNIPPET_FIELDS = (
    "snippet.text",
    "snippet.snippetKind",
    "snippet.section",
)

PAPER_FIELDS = (
    "paperId",
    "corpusId",
    "title",
    "abstract",
    "tldr",
    "venue",
    "year",
    "url",
    "citationCount",
    "fieldsOfStudy",
    "authors",
    "embedding.specter_v2",
)


def search_text(query: str) -> str:
    text = "".join(
        character if character.isalnum() or character.isspace() else " "
        for character in query
    )
    return " ".join(text.split())


def snippet_id(source_id: str, location: str | None, text: str) -> str:
    value = "\x1f".join((source_id, location or "", " ".join(text.split())))
    digest = hashlib.sha256(value.encode()).hexdigest()[:16]
    return f"snippet_{digest}"


def parse_hit(record: Mapping[str, Any]) -> SearchHit | None:
    paper = record.get("paper")
    snippet = record.get("snippet")

    if not isinstance(paper, Mapping):
        return None
    if not isinstance(snippet, Mapping):
        return None
    if snippet.get("snippetKind") == "title":
        return None

    corpus_id = paper.get("corpusId")
    text = " ".join(str(snippet.get("text") or "").split())

    if corpus_id is None or not text:
        return None

    source_id = str(corpus_id)
    location = snippet.get("section")
    score = record.get("score")

    return SearchHit(
        snippet=Snippet(
            id=snippet_id(source_id, str(location) if location else None, text),
            source_id=source_id,
            title=str(paper.get("title") or ""),
            text=text,
            location=str(location) if location is not None else None,
        ),
        score=float(score) if isinstance(score, (int, float)) else None,
    )


def parse_paper(record: Mapping[str, Any]) -> Paper | None:
    corpus_id = record.get("corpusId")

    if corpus_id is None:
        return None

    paper_id = record.get("paperId")
    tldr = record.get("tldr")
    embedding = record.get("embedding")

    if isinstance(tldr, Mapping):
        tldr = tldr.get("text")
    if isinstance(embedding, Mapping):
        embedding = embedding.get("vector")

    return Paper(
        source_id=str(corpus_id),
        paper_id=str(paper_id) if paper_id is not None else None,
        s2_corpus_id=str(corpus_id),
        title=str(record.get("title") or ""),
        abstract=record.get("abstract"),
        tldr=str(tldr) if tldr is not None else None,
        year=record.get("year"),
        venue=record.get("venue"),
        url=record.get("url"),
        citation_count=record.get("citationCount"),
        fields_of_study=list(record.get("fieldsOfStudy") or []),
        authors=[
            str(author.get("name"))
            for author in record.get("authors") or []
            if isinstance(author, Mapping) and author.get("name")
        ],
        specter_v2=embedding,
    )


class SemanticScholarClient(BaseAPIClient):
    def __init__(
        self,
        settings: SemanticScholarSettings,
        *,
        cache: FileCache | None = None,
    ) -> None:
        if cache is None and settings.cache_dir is not None:
            cache = FileCache(settings.cache_dir, ttl=settings.cache_ttl)

        headers = {
            "accept": "application/json",
            "user-agent": "agora/0.1",
        }
        if settings.api_key:
            headers["x-api-key"] = settings.api_key

        super().__init__(
            base_url=settings.base_url,
            headers=headers,
            timeout=settings.timeout,
            min_request_interval=settings.min_request_interval,
            max_retries=settings.max_retries,
            retry_threshold_s=settings.retry_threshold_s,
            cache=cache,
            cache_ttl=settings.cache_ttl,
        )

    async def search_papers(self, query: str, *, limit: int) -> list[Paper]:
        query = search_text(query)
        if not query:
            raise ValueError("query cannot be empty")

        response = await self.request_json(
            "GET",
            PAPER_SEARCH_PATH,
            params={
                "query": query,
                "limit": min(limit, PAPER_SEARCH_LIMIT),
                "fields": ",".join(PAPER_FIELDS),
            },
        )
        records = response.get("data", []) if isinstance(response, Mapping) else []
        return [
            paper
            for record in records
            if isinstance(record, Mapping) and (paper := parse_paper(record)) is not None
        ]


    async def search_snippets(
        self,
        query: str,
        *,
        limit: int,
        fields_of_study: Sequence[AcademicField] = (),
        year: str | None = None,
        min_citations: int = 0,
    ) -> list[SearchHit]:
        query = search_text(query)

        if not query:
            raise ValueError("query cannot be empty")

        params: dict[str, str | int] = {
            "query": query,
            "limit": min(limit, SNIPPET_SEARCH_LIMIT),
            "fields": ",".join(SNIPPET_FIELDS),
        }

        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(field.value for field in fields_of_study)
        if year:
            params["year"] = year
        if min_citations:
            params["minCitationCount"] = min_citations

        response = await self.request_json("GET", SNIPPET_SEARCH_PATH, params=params)

        records = response.get("data", []) if isinstance(response, Mapping) else []

        return [
            hit
            for record in records
            if isinstance(record, Mapping) and (hit := parse_hit(record)) is not None
        ]

    async def get_papers(
        self,
        source_ids: Sequence[str],
        *,
        batch_size: int,
    ) -> list[Paper]:
        source_ids = list(dict.fromkeys(source_ids))
        batch_size = min(batch_size, PAPER_BATCH_LIMIT)

        papers: dict[str, Paper] = {}
        dropped = 0
        last_error: ClientError | None = None

        for start in range(0, len(source_ids), batch_size):
            batch = source_ids[start : start + batch_size]

            try:
                response = await self.request_json(
                    "POST",
                    PAPER_BATCH_PATH,
                    params={"fields": ",".join(PAPER_FIELDS)},
                    json_body={
                        "ids": [f"CorpusId:{source_id}" for source_id in batch]
                    },
                )
            except ClientError as error:
                dropped += len(batch)
                logger.warning("Dropping paper batch of %d: %s", len(batch), error)
                last_error = error
                continue

            if not isinstance(response, list):
                continue

            for record in response:
                if not isinstance(record, Mapping):
                    continue
                paper = parse_paper(record)
                if paper is not None:
                    papers.setdefault(paper.source_id, paper)

        if dropped:
            logger.warning(
                "Hydrated %d of %d papers (%d dropped)",
                len(papers),
                len(source_ids),
                dropped,
            )
        if last_error is not None and not papers:
            raise last_error


        return [papers[source_id] for source_id in source_ids if source_id in papers]
