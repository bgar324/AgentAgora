from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agora.schemas.deliberation import (
    Contribution,
    DocumentSection,
    Objective,
    Resolution,
    Suggestion,
)
from agora.schemas.panel import PerspectiveFacets
from agora.schemas.research import Paper, ResearchDirection

PublicStatus = Literal["active", "waiting", "failed", "complete", "cancelled"]

PublicStage = Literal[
    "brief",
    "perspectives",
    "ready",
    "opening",
    "selection",
    "deliberation",
    "report",
]

WaitingFor = Literal[
    "perspective_selection",
    "proposal_selection",
    "resolution_decision",
]


class ErrorDetail(BaseModel):
    code: str
    message: str


class WorkspaceCreate(BaseModel):
    name: str


class WorkspaceView(BaseModel):
    id: str
    name: str
    created_at: str


class InvestigationCreate(BaseModel):
    idea: str
    n: int = Field(default=3, ge=1, le=6)


class InvestigationPatch(BaseModel):
    version: int
    title: str | None = None
    research_question: str | None = None
    research_directions: list[ResearchDirection] | None = None


class InvestigationView(BaseModel):
    id: str
    workspace_id: str
    title: str | None
    idea: str
    research_question: str | None
    research_directions: list[ResearchDirection]
    status: PublicStatus
    stage: PublicStage
    waiting_for: WaitingFor | None
    version: int


class InvestigationState(BaseModel):
    investigation_id: str
    status: PublicStatus
    stage: PublicStage
    waiting_for: WaitingFor | None
    active_thread_id: str | None
    document_version: int | None
    version: int


class MapPosition(BaseModel):
    x: float
    y: float


class PerspectiveDiscovery(BaseModel):
    version: int
    n: int = Field(default=3, ge=1, le=6)
    thread_id: str | None = None
    question: str | None = None


class PerspectiveSelection(BaseModel):
    version: int
    perspective_ids: list[str]


class PerspectiveSummary(BaseModel):
    id: str
    name: str
    focus: str
    framing: str
    position: str
    source_count: int
    selected: bool
    map_position: MapPosition | None


class PerspectiveView(BaseModel):
    id: str
    name: str
    focus: str
    framing: str
    position: str
    facets: PerspectiveFacets
    label: str
    subthemes: list[str]
    source_count: int
    selected: bool
    map_position: MapPosition | None
    version: int


class PaperView(BaseModel):
    id: str
    title: str
    abstract: str | None
    tldr: str | None
    year: int | None
    venue: str | None
    url: str | None
    citation_count: int | None
    fields_of_study: list[str]

    @classmethod
    def of(cls, paper: Paper) -> "PaperView":
        return cls(
            id=paper.source_id,
            title=paper.title,
            abstract=paper.abstract,
            tldr=paper.tldr,
            year=paper.year,
            venue=paper.venue,
            url=paper.url,
            citation_count=paper.citation_count,
            fields_of_study=paper.fields_of_study,
        )


class SourcePage(BaseModel):
    items: list[PaperView]
    total: int
    limit: int
    offset: int


class DeliberationStart(BaseModel):
    version: int


class ProposalSelectionBody(BaseModel):
    version: int
    proposal_ids: list[str]


class CitationView(BaseModel):
    index: int
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    text: str = ""


class ProposalView(BaseModel):
    id: str
    perspective_id: str
    version: int
    claim: str
    reasoning: str
    evidence_count: int
    selected: bool
    citations: list[CitationView] = Field(default_factory=list)


class ResponseView(BaseModel):
    proposal_id: str
    reviewer_id: str
    response: str
    question: str | None


class PerspectiveUpdateView(BaseModel):
    perspective_id: str
    trigger: Literal["response", "thread"]
    decision: Literal["unchanged", "revise"]
    reason: str
    facets_changed: list[str]
    open_question: str | None


class DocumentSectionView(BaseModel):
    id: str
    version: int
    title: str
    text: str


class ReferenceView(BaseModel):
    index: int
    source_id: str = ""
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    url: str | None = None


class WorkingDocumentView(BaseModel):
    id: str
    version: int
    title: str
    objectives: list[Objective]
    sections: list[DocumentSectionView]
    references: list[ReferenceView] = Field(default_factory=list)


class ThreadSummary(BaseModel):
    id: str
    title: str
    question: str
    context: str = ""
    status: Literal["suggested", "open", "closed"]
    section_id: str | None


class ThreadCreate(BaseModel):
    version: int
    thread_id: str | None = None
    title: str = ""
    question: str = ""
    context: str = ""


class ThreadView(BaseModel):
    id: str
    version: int
    status: Literal["suggested", "open", "closed"]
    title: str
    question: str
    context: str
    section_id: str | None
    participants: list[str]
    resolution: Resolution | None


class ContributionContext(BaseModel):
    kind: Literal["text", "paper"]
    value: str | None = None
    paper_id: str | None = None


class ContributionCreate(BaseModel):
    kind: Literal["reply", "support", "challenge"]
    text: str = ""
    reply_to: str | None = None
    context: list[ContributionContext] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_text(self) -> "ContributionCreate":
        if self.kind in ("reply", "challenge") and not self.text.strip():
            raise ValueError(f"A {self.kind} requires text")
        return self


class ContributionView(Contribution):
    citations: list[CitationView] = Field(default_factory=list)


class ContributionPage(BaseModel):
    items: list[ContributionView]
    total: int
    limit: int
    offset: int


class EvidenceRequestBody(BaseModel):
    need: str
    query: str


class ResolutionDecisionBody(BaseModel):
    version: int
    action: Literal[
        "accept_and_close",
        "edit_and_close",
        "keep_open",
        "request_evidence",
    ]
    consensus: str | None = None
    disagreement: str | None = None
    open_question: str | None = None


class SuggestionDecisionBody(BaseModel):
    version: int
    action: Literal["accept", "edit", "reject", "defer"]
    text: str | None = None

    @model_validator(mode="after")
    def require_text(self) -> "SuggestionDecisionBody":
        if self.action == "edit" and not (self.text or "").strip():
            raise ValueError("An edited Suggestion requires text")
        return self


class SectionPatch(BaseModel):
    version: int
    text: str


class DeliberationView(BaseModel):
    perspectives: list[PerspectiveSummary]
    proposals: list[ProposalView]
    responses: list[ResponseView]
    perspective_updates: list[PerspectiveUpdateView]
    objectives: list[Objective]
    document: WorkingDocumentView | None
    threads: list[ThreadSummary]
    active_thread: ThreadView | None
    pending_resolution: Resolution | None
    pending_suggestions: list[Suggestion]


class EventEnvelope(BaseModel):
    id: str
    type: str
    investigation_id: str
    created_at: str
    data: dict


def section_view(section: DocumentSection) -> DocumentSectionView:
    return DocumentSectionView(
        id=section.id,
        version=section.version,
        title=section.title,
        text=section.text,
    )
