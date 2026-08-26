"""Domain contracts for abstract-grounded, facet-led perspective deliberation."""

from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agora.schemas.deliberation import (
    Contribution as CanonContribution,
)
from agora.schemas.deliberation import (
    PanelReview as CanonPanelReview,
)
from agora.schemas.deliberation import (
    PerspectiveState as CanonPerspectiveState,
)
from agora.schemas.deliberation import (
    Proposal as CanonProposal,
)
from agora.schemas.deliberation import (
    Refinement as CanonRefinement,
)
from agora.schemas.deliberation import (
    Reflection as CanonReflection,
)
from agora.schemas.deliberation import (
    Resolution as CanonResolution,
)
from agora.schemas.deliberation import (
    Revision as CanonRevision,
)
from agora.schemas.deliberation import (
    Suggestion as CanonSuggestion,
)
from agora.schemas.deliberation import (
    Thread as CanonThread,
)
from agora.schemas.deliberation import (
    WorkingDocument as CanonWorkingDocument,
)
from agora.schemas.panel import Observation as CanonObservation

Facet = Literal["scope", "explanation", "approach", "significance"]
ResearchQuestion = Annotated[str, Field(min_length=1, max_length=4000)]
RetrievalTier = Literal["answer", "problem", "candidate"]
SearchQuery = Annotated[str, Field(min_length=1, max_length=500)]

# Stable wire and display order. A Perspective always carries all four facets;
# each deliberation round activates exactly one.
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


class HypothesisDev(BaseModel):
    """One testable solution candidate for the research problem."""

    model_config = ConfigDict(extra="forbid")

    hypothesis: str = Field(min_length=1, max_length=4000)


HypothesisPart = Literal["hypothesis"]
HypothesisConfirmationMode = Literal[
    "apply_pending",
    "edit_applied",
    "reject_pending",
]
HypothesisDecision = Literal["accepted", "edited", "rejected"]


class HypothesisVersion(BaseModel):
    """An immutable, traceable hypothesis checkpoint in a workspace."""

    id: str
    workspace_id: str
    investigation_id: str
    parent_ids: list[str] = Field(default_factory=list)
    steps: HypothesisDev
    step_sources: dict[HypothesisPart, str] = Field(default_factory=dict)
    source_kind: Literal["applied", "edit", "merge"] = "applied"
    source_deliberation_id: str | None = None
    source_round: int | None = None
    archived: bool = False
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def validate_ancestry(self) -> Self:
        if len(set(self.parent_ids)) != len(self.parent_ids):
            raise ValueError("hypothesis parent IDs must be unique")
        if self.id in self.parent_ids:
            raise ValueError("a hypothesis cannot be its own parent")
        return self


class TurnKind(str, Enum):
    open = "open"
    answer = "answer"
    support = "support"
    user = "user"
    system = "system"
    challenge = "challenge"
    reply = "reply"


class Turn(BaseModel):
    id: int
    agent_iid: int | None = None
    agent_label: str = ""
    role: Literal["lead", "other", "user", "system"] = "other"
    kind: TurnKind
    facet: Facet | None = None
    text: str
    citations: list[str] = Field(default_factory=list)
    exchange_n: int | None = Field(default=None, ge=1)
    reply_to_turn_id: int | None = None
    relation: Literal["answer", "reply", "support", "challenge"] | None = None
    assumption: str = ""
    hypothesis_fragments: list[str] = Field(default_factory=list)


class ThreadVerdict(BaseModel):
    """Moderator finding for one scientific Thread.

    ``facets`` is traceability metadata: it names the Perspective facets the
    finding touches. It never constrains what the Thread may discuss.
    """

    facets: list[Facet] = Field(default_factory=list, max_length=4)
    status: Literal["consensus", "disagreement", "unsettled"]
    summary: str
    proposed_shared_ground: str = ""
    consensus: str = ""
    disagreement: str = ""
    unsettled: str = ""
    supporting: list[str] = Field(default_factory=list)
    contested_by: list[str] = Field(default_factory=list)
    positions: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, list[str]] = Field(default_factory=dict)


class SharedGroundAssent(BaseModel):
    agent_iid: int
    agent_label: str
    decision: Literal["accept", "qualify", "reject"]
    reason: str = ""
    challenge_turn_id: int | None = None
    challenge: str = ""


class ModeratorCheck(BaseModel):
    exchange_n: int = Field(ge=1)
    proposed_shared_ground: str
    verdict: ThreadVerdict
    assents: list[SharedGroundAssent] = Field(default_factory=list)
    unanimous: bool = False

    @model_validator(mode="after")
    def validate_unanimous(self) -> Self:
        expected = bool(self.proposed_shared_ground.strip()) and bool(self.assents)
        expected = expected and all(
            assent.decision == "accept" for assent in self.assents
        )
        if self.unanimous != expected:
            raise ValueError("unanimous must match the recorded assents")
        return self


class DeliberationPoint(BaseModel):
    facets: list[Facet] = Field(default_factory=list, max_length=4)
    text: str
    rationale: str = ""
    perspective_names: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class ThreadPerspectiveLink(BaseModel):
    """Which fragments of one Perspective a Thread relates to (traceability)."""

    perspective_name: str = Field(min_length=1, max_length=200)
    facets: list[Facet] = Field(default_factory=list, max_length=4)


class DeliberationThread(BaseModel):
    """One scientific issue, disagreement, or open question under deliberation.

    The ``question`` drives the discussion. ``related`` and ``facets`` are the
    representation/traceability layer: they surface where Perspectives differ
    and what changed afterward, but never determine the conversation.
    """

    id: str
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=1000)
    context: str = Field(default="", max_length=2000)
    facets: list[Facet] = Field(default_factory=list, max_length=4)
    related: list[ThreadPerspectiveLink] = Field(default_factory=list)
    perspective_names: list[str] = Field(default_factory=list)
    hypothesis_fragments: list[str] = Field(default_factory=list)
    source_round: int | None = Field(default=None, ge=1)


class RoundResolution(BaseModel):
    summary: str = Field(
        description=(
            "Two or three sentences: how the discussion developed, what evidence "
            "mattered, and the resulting conclusion."
        ),
        max_length=2000,
    )
    consensus_points: list[DeliberationPoint] = Field(default_factory=list)
    disagreement_points: list[DeliberationPoint] = Field(default_factory=list)
    unsettled_points: list[DeliberationPoint] = Field(default_factory=list)


class FacetDistance(BaseModel):
    facet: Facet
    distance: float = Field(ge=0.0, le=2.0)
    participant_count: int = Field(ge=0)


class RoundMetrics(BaseModel):
    method: str
    before: list[FacetDistance] = Field(default_factory=list)
    after: list[FacetDistance] = Field(default_factory=list)
    overall_before: float | None = Field(default=None, ge=0.0, le=2.0)
    overall_after: float | None = Field(default=None, ge=0.0, le=2.0)
    delta: float | None = Field(default=None, ge=-2.0, le=2.0)
    direction: Literal["convergent", "divergent", "stable", "insufficient"] = (
        "insufficient"
    )


class FacetRevision(BaseModel):
    facet: Facet
    text: str


class ParticipantReflection(BaseModel):
    agent_iid: int
    perspective_name: str
    decision: Literal["unchanged", "revised"]
    reason: str
    revisions: list[FacetRevision] = Field(default_factory=list)


class DeliberationRating(BaseModel):
    divergent: int = Field(ge=1, le=7)
    convergent: int = Field(ge=1, le=7)
    note: str = Field(default="", max_length=1000)
    submitted_at: datetime = Field(default_factory=utcnow)


class DeliberationRound(BaseModel):
    n: int
    lead_iid: int
    participant_iids: list[int] = Field(default_factory=list)
    facets: list[Facet] = Field(default_factory=list, max_length=4)
    thread_id: str | None = None
    turns: list[Turn] = Field(default_factory=list)
    verdict: ThreadVerdict | None = None
    resolution: RoundResolution | None = None
    reflections: list[ParticipantReflection] = Field(default_factory=list)
    metrics: RoundMetrics | None = None
    completed: bool = False
    hypothesis_before: HypothesisDev | None = None
    hypothesis_proposal: HypothesisDev | None = None
    hypothesis_decision: HypothesisDecision | None = None
    moderator_checks: list[ModeratorCheck] = Field(default_factory=list)
    stop_reason: Literal["unanimous", "exchange_limit"] | None = None
    resolution_decision: Literal["accepted", "edited", "kept_open"] | None = None
    resolution_note: str = Field(default="", max_length=2000)


QuestionStatus = Literal["open", "investigating", "addressed", "archived"]


class RecommendedQuestion(BaseModel):
    id: str = ""
    question: ResearchQuestion
    rationale: str = Field(max_length=4000)
    source_kind: Literal["disagreement", "unsettled"]
    source_point: str = Field(max_length=4000)
    facets: list[Facet] = Field(default_factory=list)
    source_round: int | None = Field(default=None, ge=1)
    status: QuestionStatus = "open"
    child_investigation_id: str | None = None
    selected_for_followup: bool = False

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "open" and self.child_investigation_id is not None:
            raise ValueError("an open question cannot already have a child")
        if (
            self.status in {"investigating", "addressed"}
            and self.child_investigation_id is None
        ):
            raise ValueError(f"{self.status} questions require a child Investigation")
        return self


class DocumentSection(BaseModel):
    """One resolved Thread rendered as a substantive research section."""

    thread_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    hypothesis: str = Field(min_length=1, max_length=4000)
    explanation: str = Field(default="", max_length=4000)


class DeliberationDocument(BaseModel):
    """The researcher-approved outcome of deliberation.

    Resolved Threads contribute hypotheses and explanations; unresolved
    scientific issues remain as open questions.
    """

    title: str = Field(min_length=1, max_length=4000)
    sections: list[DocumentSection] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class DeliberationCompletion(BaseModel):
    archived_at: datetime = Field(default_factory=utcnow)
    reason: Literal["completed", "restarted"] = "completed"
    completed_at: datetime | None = None
    final_hypothesis_version_id: str | None = None
    round_count: int = Field(default=0, ge=0)
    chat_count: int = Field(default=0, ge=0)
    agent_iids: list[int] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)
    lead_perspective_id: str | None = None
    threads: list[DeliberationThread] = Field(default_factory=list)
    baseline_hypothesis: HypothesisDev | None = None
    selected_question_ids: list[str] = Field(default_factory=list)
    document: DeliberationDocument | None = None
    rating: DeliberationRating | None = None
    rounds: list[DeliberationRound] = Field(default_factory=list)
    recommended_questions: list[RecommendedQuestion] = Field(default_factory=list)
    chat: list[Turn] = Field(default_factory=list)
    revised_perspective: Perspective | None = None
    hypothesis: HypothesisDev | None = None
    applied_hypothesis_version_id: str | None = None
    applied_hypothesis: HypothesisDev | None = None
    hypothesis_confirmed: bool = False
    no_agreement: bool = False

    @model_validator(mode="after")
    def validate_archive(self) -> Self:
        if self.reason == "completed" and (
            self.completed_at is None or self.final_hypothesis_version_id is None
        ):
            raise ValueError("a completed archive requires its final hypothesis")
        if self.hypothesis_confirmed and (
            self.hypothesis is None
            or self.applied_hypothesis is None
            or self.hypothesis != self.applied_hypothesis
        ):
            raise ValueError(
                "a confirmed archived hypothesis must equal its applied hypothesis"
            )
        if self.rounds and self.round_count != len(self.rounds):
            raise ValueError("archive round count must match its stored rounds")
        if self.chat and self.chat_count != len(self.chat):
            raise ValueError("archive chat count must match its stored chat")
        return self


class DeliberationState(BaseModel):
    id: str
    threads: list[DeliberationThread] = Field(default_factory=list)
    agent_iids: list[int] = Field(default_factory=list)
    lead_perspective_id: str | None = None
    baseline_hypothesis: HypothesisDev | None = None
    selected_question_ids: list[str] = Field(default_factory=list)
    document: DeliberationDocument | None = None
    rounds: list[DeliberationRound] = Field(default_factory=list)
    revised_perspective: Perspective | None = None
    hypothesis: HypothesisDev | None = None
    applied_hypothesis: HypothesisDev | None = None
    hypothesis_confirmed: bool = False
    working_hypothesis_source_kind: Literal["applied", "edit"] | None = None
    working_hypothesis_source_round: int | None = Field(default=None, ge=1)
    no_agreement: bool = False
    recommended_questions: list[RecommendedQuestion] = Field(default_factory=list)
    questions_generated: bool = False
    chat: list[Turn] = Field(default_factory=list)
    completed_at: datetime | None = None
    final_hypothesis_version_id: str | None = None
    rating: DeliberationRating | None = None
    completion_history: list[DeliberationCompletion] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_hypothesis_state(self) -> Self:
        if self.completed_at is None and (
            self.final_hypothesis_version_id is not None or self.rating is not None
        ):
            raise ValueError(
                "final hypothesis and rating require a completed deliberation"
            )
        if self.completed_at is not None and self.final_hypothesis_version_id is None:
            raise ValueError("a completed deliberation requires a final hypothesis")
        if self.hypothesis_confirmed and (
            self.hypothesis is None
            or self.applied_hypothesis is None
            or self.hypothesis != self.applied_hypothesis
        ):
            raise ValueError("a confirmed hypothesis must equal the applied hypothesis")
        source = (
            self.working_hypothesis_source_kind,
            self.working_hypothesis_source_round,
        )
        if any(source) and (not all(source) or self.applied_hypothesis is None):
            raise ValueError(
                "unsaved hypothesis provenance requires an applied working hypothesis"
            )
        return self


class AgentState(BaseModel):
    iid: int
    perspective_id: str
    label: str
    facets: dict[Facet, FacetEvidence] = Field(default_factory=dict)
    facet_version: int = 1
    hypothesis: HypothesisDev | None = None


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


DialogueStage = Literal["opening", "selection", "deliberation"]
DialogueWaiting = Literal["proposal_selection", "resolution_decision"]


class DialogueState(BaseModel):
    """Canonical Perspectra-style deliberation state for one Investigation.

    Every collection holds objects from ``agora.schemas.deliberation``
    verbatim, so the engine, the wire format, and persistence share one
    contract. Versioned objects are append-only: the latest version of an
    id wins, and history stays readable.
    """

    id: str
    stage: DialogueStage = "opening"
    waiting_for: DialogueWaiting | None = None
    active_thread_id: str | None = None
    perspective_states: list[CanonPerspectiveState] = Field(default_factory=list)
    observations: list[CanonObservation] = Field(default_factory=list)
    proposals: list[CanonProposal] = Field(default_factory=list)
    reviews: list[CanonPanelReview] = Field(default_factory=list)
    refinements: list[CanonRefinement] = Field(default_factory=list)
    selected_proposal_ids: list[str] = Field(default_factory=list)
    document: CanonWorkingDocument | None = None
    threads: list[CanonThread] = Field(default_factory=list)
    contributions: list[CanonContribution] = Field(default_factory=list)
    resolutions: list[CanonResolution] = Field(default_factory=list)
    suggestions: list[CanonSuggestion] = Field(default_factory=list)
    revisions: list[CanonRevision] = Field(default_factory=list)
    reflections: list[CanonReflection] = Field(default_factory=list)

    def latest_thread(self, thread_id: str) -> CanonThread | None:
        for thread in reversed(self.threads):
            if thread.id == thread_id:
                return thread
        return None

    def latest_resolution(self, resolution_id: str) -> CanonResolution | None:
        for resolution in reversed(self.resolutions):
            if resolution.id == resolution_id:
                return resolution
        return None

    def current_threads(self) -> list[CanonThread]:
        latest: dict[str, CanonThread] = {}
        for thread in self.threads:
            latest[thread.id] = thread
        return list(latest.values())


class SessionState(BaseModel):
    """Full wire state for one focused-panel Investigation."""

    id: str
    workspace_id: str
    created_at: datetime = Field(default_factory=utcnow)
    demo: bool = True
    problem: str = Field(default="", max_length=4000)
    research_questions: list[ResearchQuestion] = Field(default_factory=list)
    parent_investigation_id: str | None = None
    origin_question_id: str | None = None
    origin_question: ResearchQuestion | None = None
    integrated_into_parent_at: datetime | None = None
    applied_hypothesis: HypothesisDev | None = None
    applied_hypothesis_version_id: str | None = None
    suggested_queries: list[SuggestedQuery] = Field(default_factory=list)
    searched_queries: list[SearchQuery] = Field(default_factory=list)
    question_reach: list[QuestionReach] = Field(default_factory=list)
    papers: list[ExpPaper] = Field(default_factory=list)
    clusters: list[ClusterCard] = Field(default_factory=list)
    unassigned_paper_ids: list[str] = Field(default_factory=list)
    perspectives: list[Perspective] = Field(default_factory=list)
    agents: list[AgentState] = Field(default_factory=list)
    deliberations: list[DeliberationState] = Field(default_factory=list)
    dialogue: DialogueState | None = None
    searched: bool = False
    clustering: ClusteringDiagnostics | None = None

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        if (self.applied_hypothesis is None) != (
            self.applied_hypothesis_version_id is None
        ):
            raise ValueError(
                "applied hypothesis and version ID must be present together"
            )
        origin = (self.origin_question_id, self.origin_question)
        if self.parent_investigation_id is None and any(origin):
            raise ValueError("a root Investigation cannot have an origin question")
        if self.parent_investigation_id is not None and not all(origin):
            raise ValueError("a child Investigation requires its origin question")
        if (
            self.integrated_into_parent_at is not None
            and self.parent_investigation_id is None
        ):
            raise ValueError("only a child Investigation can be integrated")
        known_papers = {paper.id for paper in self.papers}
        unassigned = set(self.unassigned_paper_ids)
        if len(unassigned) != len(self.unassigned_paper_ids):
            raise ValueError("unassigned paper IDs must be unique")
        if not unassigned <= known_papers:
            raise ValueError("unassigned IDs must reference retrieved papers")
        clustered = {
            paper_id for cluster in self.clusters for paper_id in cluster.paper_ids
        }
        if unassigned & clustered:
            raise ValueError("a paper cannot be clustered and unassigned")
        return self


class InvestigationSummary(BaseModel):
    id: str
    parent_investigation_id: str | None = None
    origin_question_id: str | None = None
    origin_question: str | None = None
    created_at: datetime
    searched: bool
    paper_count: int
    perspective_count: int
    completed_rounds: int
    open_question_count: int
    applied_hypothesis_version_id: str | None = None


class WorkspaceState(BaseModel):
    id: str
    created_at: datetime = Field(default_factory=utcnow)
    revision: int = Field(default=0, ge=0)
    schema_version: Literal[6] = 6
    problem: str = Field(max_length=4000)
    root_investigation_id: str
    active_investigation_id: str
    investigation_ids: list[str] = Field(default_factory=list)
    promoted_hypothesis_version_id: str | None = None
    hypothesis_versions: list[HypothesisVersion] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        investigation_ids = set(self.investigation_ids)
        if len(investigation_ids) != len(self.investigation_ids):
            raise ValueError("Investigation IDs must be unique")
        if self.root_investigation_id not in investigation_ids:
            raise ValueError("workspace root must belong to the workspace")
        if self.active_investigation_id not in investigation_ids:
            raise ValueError("active Investigation must belong to the workspace")
        versions = {version.id: version for version in self.hypothesis_versions}
        if len(versions) != len(self.hypothesis_versions):
            raise ValueError("hypothesis version IDs must be unique")
        for version in self.hypothesis_versions:
            if version.workspace_id != self.id:
                raise ValueError("hypothesis version belongs to another workspace")
            if version.investigation_id not in investigation_ids:
                raise ValueError("hypothesis version owner is outside the workspace")
            if any(parent_id not in versions for parent_id in version.parent_ids):
                raise ValueError("hypothesis parent is missing from the workspace")
            if any(
                source_id not in versions for source_id in version.step_sources.values()
            ):
                raise ValueError("hypothesis step source is missing from the workspace")
        if self.promoted_hypothesis_version_id is not None:
            promoted = versions.get(self.promoted_hypothesis_version_id)
            if promoted is None or promoted.archived:
                raise ValueError("promoted hypothesis must exist and be active")
        return self


class WorkspaceView(BaseModel):
    workspace: WorkspaceState
    investigations: list[InvestigationSummary]
    active: SessionState


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
    assumption: str = Field(
        default="",
        description="The assumption or causal belief supporting this turn.",
    )
    relation: Literal["answer", "reply", "support", "challenge"] = "answer"
    hypothesis_fragments: list[str] = Field(
        default_factory=list,
        description="Exact excerpts from the current hypothesis addressed by the turn.",
    )
    citations: list[str] = Field(
        default_factory=list,
        description="Paper IDs or titles supporting the statement.",
    )


class SupportSearch(BaseModel):
    query: str = Field(description="A literature-search query for the claim.")


class SupportPassage(BaseModel):
    passage: str = Field(description="The passage worth citing, verbatim.")
    reason: str = Field(description="Why this passage supports the statement.")


class ThreadVerdictDraft(BaseModel):
    status: Literal["consensus", "disagreement", "unsettled"]
    summary: str
    proposed_shared_ground: str = ""
    consensus: str = ""
    disagreement: str = ""
    unsettled: str = ""
    supporting: list[str] = Field(default_factory=list)
    contested_by: list[str] = Field(default_factory=list)


class ThreadVerdictOutput(BaseModel):
    verdict: ThreadVerdictDraft


class SharedGroundAssentDraft(BaseModel):
    decision: Literal["accept", "qualify", "reject"]
    reason: str
    challenge_turn_id: int | None = None
    challenge: str = ""


class DeliberationThreadDraft(BaseModel):
    title: str
    question: str
    context: str
    related: list[ThreadPerspectiveLink] = Field(
        default_factory=list,
        description="Per-Perspective fragments this Thread relates to.",
    )
    facets: list[Facet] = Field(default_factory=list, max_length=4)
    perspective_names: list[str] = Field(default_factory=list)
    hypothesis_fragments: list[str] = Field(default_factory=list)


class DeliberationThreads(BaseModel):
    threads: list[DeliberationThreadDraft] = Field(default_factory=list)


class DocumentSectionDraft(BaseModel):
    thread_title: str = Field(description="The resolved Thread's topic title.")
    hypothesis: str = Field(description="The hypothesis this Thread supports.")
    explanation: str = Field(
        description="Why the hypothesis is warranted, without the transcript."
    )


class DocumentDraft(BaseModel):
    sections: list[DocumentSectionDraft] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class ReflectionDraft(BaseModel):
    decision: Literal["unchanged", "revised"]
    reason: str
    revisions: list[FacetRevision] = Field(default_factory=list)


class QuestionRecommendations(BaseModel):
    questions: list[RecommendedQuestion] = Field(default_factory=list)


class HypothesisSteps(BaseModel):
    steps: HypothesisDev


class ChatReply(BaseModel):
    text: str
    citations: list[str] = Field(default_factory=list)


def session_snapshot(state: SessionState) -> dict[str, Any]:
    return state.model_dump(mode="json")
