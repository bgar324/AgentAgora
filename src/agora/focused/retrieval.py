from dataclasses import dataclass, field

from agora.client.s2 import SemanticScholarClient


@dataclass(frozen=True)
class FocusedAuthor:
    name: str


@dataclass(frozen=True)
class FocusedSearchResult:
    id: str
    title: str
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    authors: list[FocusedAuthor] = field(default_factory=list)
    tldr: str | None = None
    open_access_pdf_url: str | None = None
    specter_v2: list[float] | None = None


class FocusedSemanticScholar:
    """Full-paper search shape expected by the focused study service.

    Facets may be extracted only from paper abstracts, never search snippets.
    """

    def __init__(self, client: SemanticScholarClient) -> None:
        self._client = client

    async def search(self, query: str, limit: int = 8) -> list[FocusedSearchResult]:
        papers = await self._client.search_papers(query, limit=limit)
        return [
            FocusedSearchResult(
                id=paper.source_id,
                title=paper.title,
                abstract=paper.abstract,
                year=paper.year,
                venue=paper.venue,
                authors=[FocusedAuthor(name=name) for name in paper.authors],
                tldr=paper.tldr,
                specter_v2=paper.specter_v2,
            )
            for paper in papers
            if paper.abstract and paper.abstract.strip()
        ][:limit]
