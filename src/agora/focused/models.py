"""Private and public contracts for the baseline focused study."""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

Facet = Literal["scope", "explanation", "approach", "significance"]
ResearchQuestion = Annotated[str, Field(min_length=1, max_length=4000)]
RetrievalTier = Literal["answer", "problem", "candidate"]
SearchQuery = Annotated[str, Field(min_length=1, max_length=500)]

# Stable wire and display order. A hidden Perspective profile carries all four.
FACETS: list[Facet] = ["scope", "explanation", "approach", "significance"]

PERSONA_COLORS = [
    "#3b6ea5",
    "#2f7d70",
    "#d3922f",
    "#b8567a",
    "#5a8f3c",
    "#7a5aa5",
]


def utcnow() -> datetime:
    return datetime.now(UTC)


class ExpPaper(BaseModel):
    """A paper in the working corpus.

    Facet evidence is grounded only in ``abstract_sentences``. PDF and
    introduction availability therefore cannot change the study condition.
    """

    id: str
    title: str
    abstract: str | None = None
    abstract_sentences: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    authors: list[str] = Field(default_factory=list)
    source_query: str | None = None
    retrieval_tier: RetrievalTier | None = None
    tldr: str | None = None
    open_access_pdf_url: str | None = None
    specter_v2: list[float] | None = None


class FacetEvidence(BaseModel):
    """One perspective facet grounded in an abstract sentence."""

    facet: Facet
    text: str = Field(max_length=4000)
    paper_id: str | None = None
    sentence_index: int | None = None
    sentence: str | None = None
    edited: bool = False


class ClusterCard(BaseModel):
    """A literature cluster shown during perspective construction."""

    id: str
    name: str
    blurb: str
    facets: list[FacetEvidence] = Field(default_factory=list)
    paper_ids: list[str] = Field(default_factory=list)
    representative_paper_ids: list[str] = Field(default_factory=list)


class FramingPosition(BaseModel):
    """Coupled perspective descriptors synthesized from all four facets."""

    framing: str = Field(description="How the perspective frames the question.")
    position: str = Field(description="The position that follows from that frame.")


class Perspective(BaseModel):
    """An abstract-grounded perspective available to the focused panel."""

    id: str
    name: str = Field(min_length=1, max_length=200)
    color: str
    facets: dict[Facet, FacetEvidence] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    anchor_paper_id: str | None = None
    related_paper_count: int = Field(default=0, ge=0)
    cluster_id: str | None = None
    framing: FramingPosition | None = None
    summary: str = Field(default="", max_length=4000)
    evolved: bool = False
    origin: str = "cluster"
    source_question_id: str | None = None
    panel_cycle: int = Field(default=0, ge=0)


class ClusteringDiagnostics(BaseModel):
    """Which clustering path ran and how well it separated the corpus."""

    method: Literal[
        "position_llm",
        "specter_hdbscan_dpp",
        "specter_kmeans",
        "tfidf_kmeans",
        "demo_seeds",
        "single_group",
        "balanced_fallback",
    ]
    embedded: int = 0
    total: int = 0
    requested_clusters: int = 0
    cluster_sizes: list[int] = Field(default_factory=list)
    silhouette: float | None = None
    retrieval_tier_counts: dict[RetrievalTier, int] = Field(default_factory=dict)


class SuggestedQuery(BaseModel):
    query: SearchQuery
    rationale: str = ""
    kind: Literal["problem", "question"] = "problem"
    question_index: int | None = None
    round: Literal[1, 2] = 1


class QuestionEvidence(BaseModel):
    paper_id: str
    candidate_index: int | None = None
    bears: Literal["supports", "opposes", "conditions"]
    evidence: str


class VocabularyPair(BaseModel):
    ours: str
    theirs: str


class QuestionReach(BaseModel):
    question: str
    form: str = ""
    candidates: list[str] = Field(default_factory=list)
    queries_r1: list[str] = Field(default_factory=list)
    queries_r2: list[str] = Field(default_factory=list)
    retrieved: int = 0
    selected: list[QuestionEvidence] = Field(default_factory=list)
    vocabulary: list[VocabularyPair] = Field(default_factory=list)
    reached: bool = False


NotepadPart = Literal["framing", "prior", "method", "expected"]

# Youngseung's baseline notepad: the researcher's position in four parts,
# written on the input screen and editable throughout the discussion.
NOTEPAD_PARTS: list[NotepadPart] = ["framing", "prior", "method", "expected"]
NOTEPAD_LABELS: dict[NotepadPart, str] = {
    "framing": "Framing",
    "prior": "Previous work",
    "method": "Methodology",
    "expected": "Expected results",
}


class NotepadDoc(BaseModel):
    """One four-part position. `v1` holds what the input screen captured."""

    framing: str = Field(default="", max_length=4000)
    prior: str = Field(default="", max_length=4000)
    method: str = Field(default="", max_length=4000)
    expected: str = Field(default="", max_length=4000)


AgendaPhase = Literal["feedback", "comparison", "complete"]
NotepadTurnKind = Literal[
    "feedback",
    "comparison",
    "researcher",
    "direct_reply",
    "summary",
    "system",
]


class NotepadAgenda(BaseModel):
    review_n: int = Field(default=1, ge=1)
    part: NotepadPart = "framing"
    phase: AgendaPhase = "feedback"
    subject_text: str = Field(default="", max_length=4000)
    participant_ids: list[str] = Field(default_factory=list)
    feedback_done_ids: list[str] = Field(default_factory=list)
    comparison_done_ids: list[str] = Field(default_factory=list)
    comparison_cycle: int = Field(default=1, ge=1)
    turn_budget: int = Field(default=4, ge=1, le=8)
    turns_emitted: int = Field(default=0, ge=0)
    completed_at: datetime | None = None


class NotepadVersion(BaseModel):
    """A named alternative. Versions are independent; these are the output."""

    id: str
    name: str = Field(min_length=1, max_length=40)
    doc: NotepadDoc = Field(default_factory=NotepadDoc)
    agenda: NotepadAgenda = Field(default_factory=NotepadAgenda)
    visible_turn_start: int = Field(default=0, ge=0)
    created_from: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class NotepadTurn(BaseModel):
    """One version-scoped line of the baseline discussion."""

    id: str
    version_id: str
    kind: NotepadTurnKind
    role: Literal["researcher", "perspective", "system", "summary"]
    author_id: str | None = None
    author_label: str = ""
    text: str = Field(default="", max_length=8000)
    citations: list[str] = Field(default_factory=list)
    review_n: int | None = Field(default=None, ge=1)
    part: NotepadPart | None = None
    comparison_cycle: int | None = Field(default=None, ge=1)
    reply_to_turn_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class NotepadFinalSnapshot(BaseModel):
    versions: list[NotepadVersion]
    finished_at: datetime = Field(default_factory=utcnow)


class NotepadState(BaseModel):
    """Versioned draft, baseline discussion, and terminal study snapshot."""

    id: str
    versions: list[NotepadVersion] = Field(default_factory=list)
    active_version_id: str | None = None
    turns: list[NotepadTurn] = Field(default_factory=list)
    in_chat: list[str] = Field(default_factory=list)
    final_snapshot: NotepadFinalSnapshot | None = None

    def active_version(self) -> NotepadVersion | None:
        for version in self.versions:
            if version.id == self.active_version_id:
                return version
        return self.versions[0] if self.versions else None


class SessionState(BaseModel):
    """Private aggregate for one baseline study."""

    id: str
    workspace_id: str
    created_at: datetime = Field(default_factory=utcnow)
    demo: bool = False
    problem: str = Field(default="", max_length=4000)
    research_questions: list[ResearchQuestion] = Field(default_factory=list)
    position: NotepadDoc = Field(default_factory=NotepadDoc)
    suggested_queries: list[SuggestedQuery] = Field(default_factory=list)
    searched_queries: list[SearchQuery] = Field(default_factory=list)
    question_reach: list[QuestionReach] = Field(default_factory=list)
    papers: list[ExpPaper] = Field(default_factory=list)
    clusters: list[ClusterCard] = Field(default_factory=list)
    unassigned_paper_ids: list[str] = Field(default_factory=list)
    perspectives: list[Perspective] = Field(default_factory=list)
    perspective_sequence: int = Field(default=0, ge=0)
    notepad: NotepadState | None = None
    searched: bool = False
    clustering: ClusteringDiagnostics | None = None

    @model_validator(mode="after")
    def validate_paper_partition(self) -> Self:
        known_papers = {paper.id for paper in self.papers}
        unassigned = set(self.unassigned_paper_ids)
        if len(unassigned) != len(self.unassigned_paper_ids):
            raise ValueError("unassigned paper IDs must be unique")
        if not unassigned <= known_papers:
            raise ValueError("unassigned IDs must reference retrieved papers")
        clustered_list = [
            paper_id for cluster in self.clusters for paper_id in cluster.paper_ids
        ]
        clustered = set(clustered_list)
        if len(clustered) != len(clustered_list):
            raise ValueError("a paper cannot belong to more than one cluster")
        if not clustered <= known_papers:
            raise ValueError("cluster IDs must reference retrieved papers")
        if unassigned & clustered:
            raise ValueError("a paper cannot be clustered and unassigned")
        if self.searched and clustered | unassigned != known_papers:
            raise ValueError("every retrieved paper must belong to a cluster")
        if any(
            perspective.anchor_paper_id not in known_papers
            for perspective in self.perspectives
        ):
            raise ValueError("Perspective anchors must reference retrieved papers")
        return self


class WorkspaceState(BaseModel):
    id: str
    created_at: datetime = Field(default_factory=utcnow)
    revision: int = Field(default=0, ge=0)
    schema_version: Literal[7]
    problem: str = Field(max_length=4000)
    root_investigation_id: str
    active_investigation_id: str
    investigation_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_single_study(self) -> Self:
        if self.investigation_ids != [self.root_investigation_id]:
            raise ValueError("a baseline workspace contains exactly one study")
        if self.active_investigation_id != self.root_investigation_id:
            raise ValueError("the baseline study must be active")
        return self


class PaperView(BaseModel):
    """Participant-visible paper metadata; internal retrieval fields stay hidden."""

    id: str
    title: str
    abstract: str | None = None
    abstract_sentences: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    authors: list[str] = Field(default_factory=list)
    tldr: str | None = None
    open_access_pdf_url: str | None = None


class PerspectiveView(BaseModel):
    """Participant-visible identity and anchor, never the hidden profile."""

    id: str
    name: str
    color: str
    summary: str = ""
    anchor_paper_id: str | None = None
    related_paper_count: int = Field(default=0, ge=0)


class SuggestedQueryView(BaseModel):
    query: SearchQuery
    rationale: str = ""


class SessionView(BaseModel):
    id: str
    workspace_id: str
    created_at: datetime
    problem: str
    position: NotepadDoc
    suggested_queries: list[SuggestedQueryView] = Field(default_factory=list)
    searched_queries: list[SearchQuery] = Field(default_factory=list)
    papers: list[PaperView] = Field(default_factory=list)
    perspectives: list[PerspectiveView] = Field(default_factory=list)
    notepad: NotepadState | None = None
    searched: bool = False


class WorkspaceSummary(BaseModel):
    id: str
    created_at: datetime
    revision: int
    problem: str


class WorkspaceView(BaseModel):
    workspace: WorkspaceSummary
    active: SessionView


# ---------------------------------------------------------------------------
# LLM structured-output schemas (one per 🔵 call that needs the model)
# ---------------------------------------------------------------------------


class QuerySuggestions(BaseModel):
    queries: list[SuggestedQuery] = Field(
        description="Five distinct literature-search queries, each reaching a "
        "different part of the literature rather than overlapping."
    )


class DerivedQuestions(BaseModel):
    questions: list[str] = Field(
        description="Two or three answerable research questions, each probing "
        "a distinct empirical uncertainty inside the research problem."
    )


class QuestionPlan(BaseModel):
    form: str = ""
    candidates: list[str] = Field(default_factory=list)
    queries: list[SuggestedQuery] = Field(default_factory=list)


class QuestionAssessment(BaseModel):
    selected: list[QuestionEvidence] = Field(default_factory=list)
    vocabulary: list[VocabularyPair] = Field(default_factory=list)


class QuestionExpansion(BaseModel):
    queries: list[SuggestedQuery] = Field(default_factory=list)


class ClusterNaming(BaseModel):
    name: str = Field(description="Short thematic name, 2-4 words.")
    blurb: str = Field(description="One-line description of the body of work.")


class ClusterNamings(BaseModel):
    clusters: list[ClusterNaming] = Field(
        description="One distinct name and blurb for each cluster, in input order."
    )


class FacetCandidate(BaseModel):
    """Model-proposed facet before server-side provenance validation."""

    facet: Facet
    text: str = Field(max_length=4000)
    paper_id: str
    sentence_index: int | None = None


class FacetExtraction(BaseModel):
    facets: list[FacetCandidate] = Field(
        description="Four abstract-grounded facets: scope, explanation, "
        "approach, and significance."
    )


class Statement(BaseModel):
    text: str = Field(description="One short spoken turn, 1-3 sentences.")
    relation: Literal["answer", "reply"] = "answer"
    citations: list[str] = Field(
        default_factory=list,
        description="Paper IDs or titles supporting the statement.",
    )


class ChatReply(BaseModel):
    text: str
    citations: list[str] = Field(default_factory=list)
