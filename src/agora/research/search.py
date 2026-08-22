from collections.abc import Sequence

from agora.client.base import LiteratureClient
from agora.config.research import SearchConfig
from agora.schemas.research import (
    AcademicField,
    LiteratureSearchResult,
    PaperCorpus,
    RetrievalSeed,
    SearchBatch,
    SearchPlan,
    SearchQuery,
    Snippet,
)


def seed_queries(seeds: Sequence[RetrievalSeed]) -> list[SearchQuery]:
    return [
        SearchQuery(id=f"R{i}", stage="seed", query=seed.query, intent=seed.intent)
        for i, seed in enumerate(seeds, start=1)
    ]


def plan_queries(plan: SearchPlan) -> list[SearchQuery]:
    queries = seed_queries(plan.retrieval_seeds)

    queries.extend(
        SearchQuery(
            id=f"P{i}",
            stage="direction",
            query=direction.query,
            intent=direction.intent,
        )
        for i, direction in enumerate(plan.research_directions, start=1)
    )

    return queries


def select_snippets(
    searches: Sequence[SearchBatch],
    *,
    limit: int,
    per_source: int = 1,
) -> list[Snippet]:
    if limit <= 0:
        return []

    if per_source < 1:
        raise ValueError("per_source must be positive")

    selected: list[Snippet] = []
    selected_ids: set[str] = set()
    source_counts: dict[str, int] = {}

    depth = max((len(batch.hits) for batch in searches), default=0)

    for rank in range(depth):
        for batch in searches:
            if rank >= len(batch.hits):
                continue

            snippet = batch.hits[rank].snippet

            if snippet.id in selected_ids:
                continue
            if source_counts.get(snippet.source_id, 0) >= per_source:
                continue

            selected_ids.add(snippet.id)
            source_counts[snippet.source_id] = (
                source_counts.get(snippet.source_id, 0) + 1
            )
            selected.append(snippet)

            if len(selected) == limit:
                return selected

    return selected


def select_source_ids(
    searches: Sequence[SearchBatch],
    *,
    limit: int,
) -> list[str]:
    if limit <= 0:
        return []

    ranked: list[list[str]] = []

    for batch in searches:
        source_ids: list[str] = []
        seen: set[str] = set()

        for hit in batch.hits:
            source_id = hit.snippet.source_id

            if source_id in seen:
                continue

            seen.add(source_id)
            source_ids.append(source_id)

        ranked.append(source_ids)

    selected: dict[str, None] = {}

    depth = max((len(source_ids) for source_ids in ranked), default=0)

    for rank in range(depth):
        for source_ids in ranked:
            if rank < len(source_ids):
                selected.setdefault(source_ids[rank], None)

            if len(selected) == limit:
                return list(selected)

    return list(selected)


def query_origins(searches: Sequence[SearchBatch]) -> dict[str, list[str]]:
    origins: dict[str, list[str]] = {}

    for batch in searches:
        seen: set[str] = set()

        for hit in batch.hits:
            source_id = hit.snippet.source_id

            if source_id in seen:
                continue

            seen.add(source_id)
            origins.setdefault(source_id, []).append(batch.search.id)

    return origins


class LiteratureSearch:
    def __init__(
        self,
        client: LiteratureClient,
        config: SearchConfig | None = None,
    ):
        self.client = client
        self.config = config or SearchConfig()

        if self.config.search_limit < 1:
            raise ValueError("search_limit must be positive")
        if self.config.corpus_size < 1:
            raise ValueError("corpus_size must be positive")
        if self.config.batch_size < 1:
            raise ValueError("batch_size must be positive")

    async def retrieve(
        self,
        queries: Sequence[SearchQuery],
        fields_of_study: Sequence[AcademicField],
    ) -> list[SearchBatch]:
        searches: list[SearchBatch] = []

        for query in queries:
            hits = await self.client.search_snippets(
                query.query,
                limit=self.config.search_limit,
                fields_of_study=fields_of_study,
                year=self.config.year,
                min_citations=self.config.min_citations,
            )

            searches.append(SearchBatch(search=query, hits=hits))

        return searches

    async def search_seeds(
        self,
        seeds: Sequence[RetrievalSeed],
        fields_of_study: Sequence[AcademicField],
        *,
        limit: int,
    ) -> tuple[list[SearchBatch], list[Snippet]]:
        searches = await self.retrieve(seed_queries(seeds), fields_of_study)

        snippets = select_snippets(searches, limit=limit, per_source=1)

        return searches, snippets

    async def search(
        self,
        *,
        corpus_id: str,
        investigation_id: str,
        plan: SearchPlan,
    ) -> LiteratureSearchResult:
        queries = plan_queries(plan)

        if not queries:
            raise ValueError("SearchPlan contains no queries")

        searches = await self.retrieve(queries, plan.fields_of_study)

        source_ids = select_source_ids(searches, limit=self.config.corpus_size)

        if not source_ids:
            raise ValueError("No papers were retrieved")

        papers = await self.client.get_papers(
            source_ids,
            batch_size=self.config.batch_size,
        )

        if not papers:
            raise ValueError("No paper records were returned")

        origins = query_origins(searches)

        corpus = PaperCorpus(
            id=corpus_id,
            investigation_id=investigation_id,
            papers=papers,
            query_origins={
                paper.source_id: origins.get(paper.source_id, [])
                for paper in papers
            },
        )

        return LiteratureSearchResult(corpus=corpus, searches=searches)
