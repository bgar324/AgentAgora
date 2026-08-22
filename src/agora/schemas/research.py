from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AcademicField(StrEnum):
    COMPUTER_SCIENCE = "Computer Science"
    MEDICINE = "Medicine"
    CHEMISTRY = "Chemistry"
    BIOLOGY = "Biology"
    MATERIALS_SCIENCE = "Materials Science"
    PHYSICS = "Physics"
    GEOLOGY = "Geology"
    PSYCHOLOGY = "Psychology"
    ART = "Art"
    HISTORY = "History"
    GEOGRAPHY = "Geography"
    SOCIOLOGY = "Sociology"
    BUSINESS = "Business"
    POLITICAL_SCIENCE = "Political Science"
    ECONOMICS = "Economics"
    PHILOSOPHY = "Philosophy"
    MATHEMATICS = "Mathematics"
    ENGINEERING = "Engineering"
    ENVIRONMENTAL_SCIENCE = "Environmental Science"
    AGRICULTURAL_AND_FOOD_SCIENCES = "Agricultural and Food Sciences"
    EDUCATION = "Education"
    LAW = "Law"
    LINGUISTICS = "Linguistics"


SearchStage = Literal[
    "seed",
    "direction",
]


class ResearchIdea(BaseModel):
    idea: str


class ResearchQuestion(BaseModel):
    title: str
    main_question: str


class RetrievalSeed(BaseModel):
    query: str
    intent: str


class ResearchDirection(BaseModel):
    topic: str
    query: str
    intent: str


class SearchPlan(BaseModel):
    idea: ResearchIdea
    research_question: ResearchQuestion
    fields_of_study: list[AcademicField] = Field(default_factory=list)
    retrieval_seeds: list[RetrievalSeed] = Field(default_factory=list)
    research_directions: list[ResearchDirection] = Field(default_factory=list)


class Paper(BaseModel):
    source_id: str
    paper_id: str | None = None
    s2_corpus_id: str | None = None

    title: str
    abstract: str | None = None
    tldr: str | None = None

    year: int | None = None
    venue: str | None = None
    url: str | None = None
    citation_count: int | None = None
    fields_of_study: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)

    specter_v2: list[float] | None = None


class Snippet(BaseModel):
    id: str
    source_id: str
    title: str
    text: str
    location: str | None = None


class SearchHit(BaseModel):
    snippet: Snippet
    score: float | None = None


class SearchQuery(BaseModel):
    id: str
    stage: SearchStage
    query: str
    intent: str


class SearchBatch(BaseModel):
    search: SearchQuery
    hits: list[SearchHit] = Field(default_factory=list)


class PaperCorpus(BaseModel):
    id: str
    investigation_id: str
    papers: list[Paper]
    query_origins: dict[str, list[str]] = Field(default_factory=dict)


class LiteratureSearchResult(BaseModel):
    corpus: PaperCorpus
    searches: list[SearchBatch]


RepresentativeRole = Literal[
    "central",
    "diverse",
]


class TopicRepresentation(BaseModel):
    label: str | None = None
    terms: list[str] = Field(default_factory=list)


class RepresentativePaper(BaseModel):
    source_id: str
    title: str
    abstract: str
    role: RepresentativeRole
    rank: int


class LiteratureCluster(BaseModel):
    id: str
    source_ids: list[str]
    representatives: list[RepresentativePaper]
    topic: TopicRepresentation | None = None

    @property
    def size(self) -> int:
        return len(self.source_ids)


class ClusteredLiterature(BaseModel):
    clusters: list[LiteratureCluster]
    unassigned_source_ids: list[str] = Field(default_factory=list)
