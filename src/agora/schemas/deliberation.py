from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from agora.schemas.panel import Observation, ResearcherProfile

EvidenceRelation = Literal[
    "support",
    "qualify",
]

FacetName = Literal[
    "scope",
    "explanation",
    "approach",
    "significance",
]


class Evidence(BaseModel):
    observation_id: str
    relation: EvidenceRelation


class Claim(BaseModel):
    id: str
    text: str


class Argument(BaseModel):
    id: str
    claim_id: str
    reasoning: str
    evidence: list[Evidence]


class Proposal(BaseModel):
    id: str
    version: int
    perspective_id: str
    perspective_version: int
    claim: Claim
    argument: Argument


class ProposalInput(BaseModel):
    proposal_id: str
    perspective_id: str
    perspective_version: int
    profile: ResearcherProfile
    observations: list[Observation]
    source_ids: list[str]


class ProposalResult(BaseModel):
    proposal: Proposal
    observations: list[Observation]
    new_observations: list[Observation] = Field(default_factory=list)
    snippet_ids: list[str] = Field(default_factory=list)
    observation_snippets: dict[str, str] = Field(default_factory=dict)


class ProposalContext(BaseModel):
    question: str
    corpus_id: str
    deliberation_version: int
    perspectives: list[ProposalInput]


class PerspectiveState(BaseModel):
    id: str
    version: int
    profile: ResearcherProfile
    observations: list[Observation]
    source_ids: list[str]
    label: str = ""
    subthemes: list[str] = Field(default_factory=list)


class ReviewAssignment(BaseModel):
    proposal_id: str
    author_id: str
    reviewer_id: str


class PanelReview(BaseModel):
    id: str
    proposal_id: str
    proposal_version: int
    reviewer_id: str
    response: str
    question: str | None = None
    observation_ids: list[str] = Field(default_factory=list)


class FacetRevision(BaseModel):
    facet: FacetName
    text: str


class Refinement(BaseModel):
    id: str
    proposal_id: str
    from_version: int
    origin_ids: list[str] = Field(default_factory=list)
    decision: Literal["unchanged", "revise"]
    reason: str
    open_question: str | None = None
    facet_revisions: list[FacetRevision] = Field(default_factory=list)
    profile: ResearcherProfile
    proposal: Proposal


class Reflection(BaseModel):
    id: str
    thread_id: str
    perspective_id: str
    from_version: int
    perspective_version: int
    decision: Literal["unchanged", "revise"]
    reason: str
    open_question: str | None = None
    facet_revisions: list[FacetRevision] = Field(default_factory=list)
    profile: ResearcherProfile


class Objective(BaseModel):
    id: str
    text: str
    proposal_ids: list[str]


class DocumentSection(BaseModel):
    id: str
    version: int
    title: str
    text: str = ""


class WorkingDocument(BaseModel):
    id: str
    version: int
    investigation_id: str
    title: str
    objectives: list[Objective] = Field(default_factory=list)
    sections: list[DocumentSection] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class ThreadAssignment(BaseModel):
    perspective_id: str
    question: str


class Thread(BaseModel):
    id: str
    version: int
    status: Literal[
        "suggested",
        "open",
        "closed",
    ]
    title: str
    question: str
    context: str
    origin_ids: list[str] = Field(default_factory=list)
    assignments: list[ThreadAssignment] = Field(default_factory=list)
    section_id: str | None = None
    resolution_id: str | None = None
    created_by: str
    created_at: datetime


class EvidenceRequest(BaseModel):
    need: str
    query: str


class Contribution(BaseModel):
    id: str
    thread_id: str
    author_id: str
    kind: Literal[
        "answer",
        "reply",
        "support",
        "challenge",
    ]
    text: str = ""
    observation_ids: list[str] = Field(default_factory=list)
    evidence_requests: list[EvidenceRequest] = Field(default_factory=list)
    reply_to: str | None = None
    created_at: datetime


class EvidenceResult(BaseModel):
    observations: list[Observation] = Field(default_factory=list)
    new_observations: list[Observation] = Field(default_factory=list)
    snippet_ids: list[str] = Field(default_factory=list)
    observation_snippets: dict[str, str] = Field(default_factory=dict)


class Resolution(BaseModel):
    id: str
    version: int
    status: Literal[
        "pending",
        "accepted",
        "rejected",
    ]
    thread_id: str
    consensus: str | None = None
    disagreement: str | None = None
    open_question: str | None = None
    contribution_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)


class Suggestion(BaseModel):
    id: str
    version: int
    status: Literal[
        "pending",
        "accepted",
        "edited",
        "rejected",
    ]
    author_id: str
    thread_id: str
    resolution_id: str
    section_id: str
    section_version: int
    current_text: str
    proposed_text: str
    reason: str
    observation_ids: list[str] = Field(default_factory=list)


class Revision(BaseModel):
    id: str
    document_id: str
    previous_document_version: int
    document_version: int
    section_id: str
    previous_text: str
    proposed_text: str
    accepted_text: str
    suggestion_id: str
    decision_id: str
    created_at: datetime
