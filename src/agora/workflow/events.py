from datetime import datetime
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field


def event_id(
    run_id: str,
    kind: str,
    target_id: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            # legacy uuid5 seed; changing it invalidates persisted event ids
            f"parallax:{run_id}:{kind}:{target_id}",
        )
    )


class Event(BaseModel):
    id: str
    run_id: str
    investigation_id: str
    created_at: datetime
    caused_by: str | None = None


class ProposalsGenerated(Event):
    kind: Literal[
        "proposals_generated"
    ] = "proposals_generated"
    proposal_ids: list[str]
    perspective_ids: list[str]


class ReviewsGenerated(Event):
    kind: Literal[
        "reviews_generated"
    ] = "reviews_generated"
    review_ids: list[str]


class ProposalsRefined(Event):
    kind: Literal[
        "proposals_refined"
    ] = "proposals_refined"
    refinement_ids: list[str]
    proposal_ids: list[str]


class ProposalSelectionRequested(Event):
    kind: Literal[
        "proposal_selection_requested"
    ] = "proposal_selection_requested"
    proposal_ids: list[str]


class ProposalsSelected(Event):
    kind: Literal[
        "proposals_selected"
    ] = "proposals_selected"
    proposal_ids: list[str]


class DocumentInitialized(Event):
    kind: Literal[
        "document_initialized"
    ] = "document_initialized"
    document_id: str
    thread_ids: list[str]


class ThreadCreated(Event):
    kind: Literal[
        "thread_created"
    ] = "thread_created"
    thread_id: str


class ThreadOpened(Event):
    kind: Literal[
        "thread_opened"
    ] = "thread_opened"
    thread_id: str


class ParticipantsAssigned(Event):
    kind: Literal[
        "participants_assigned"
    ] = "participants_assigned"
    thread_id: str
    perspective_ids: list[str]


class ContributionAdded(Event):
    kind: Literal[
        "contribution_added"
    ] = "contribution_added"
    thread_id: str
    contribution_id: str
    contribution_kind: Literal[
        "answer",
        "reply",
        "support",
        "challenge",
    ]
    target_author_id: str | None = None
    mentioned_ids: list[str] = Field(default_factory=list)
    requires_response: bool = False


class EvidenceRequested(Event):
    kind: Literal[
        "evidence_requested"
    ] = "evidence_requested"
    thread_id: str
    perspective_id: str
    query: str
    target_id: str | None = None


class EvidenceRetrieved(Event):
    kind: Literal[
        "evidence_retrieved"
    ] = "evidence_retrieved"
    perspective_id: str
    query: str
    snippet_ids: list[str]
    thread_id: str | None = None
    target_id: str | None = None


class ResolutionRequested(Event):
    kind: Literal[
        "resolution_requested"
    ] = "resolution_requested"
    thread_id: str


class ResolutionProposed(Event):
    kind: Literal[
        "resolution_proposed"
    ] = "resolution_proposed"
    thread_id: str
    resolution_id: str


class ThreadClosed(Event):
    kind: Literal[
        "thread_closed"
    ] = "thread_closed"
    thread_id: str
    resolution_id: str
    perspective_ids: list[str]


class SuggestionCreated(Event):
    kind: Literal[
        "suggestion_created"
    ] = "suggestion_created"
    thread_id: str
    suggestion_id: str


class SuggestionDecided(Event):
    kind: Literal[
        "suggestion_decided"
    ] = "suggestion_decided"
    suggestion_id: str
    action: Literal[
        "accept",
        "edit",
        "reject",
    ]


class DocumentRevised(Event):
    kind: Literal[
        "document_revised"
    ] = "document_revised"
    document_id: str
    document_version: int
    revision_id: str


WorkflowEvent = (
    ProposalsGenerated
    | ReviewsGenerated
    | ProposalsRefined
    | ProposalSelectionRequested
    | ProposalsSelected
    | DocumentInitialized
    | ThreadCreated
    | ThreadOpened
    | ParticipantsAssigned
    | ContributionAdded
    | EvidenceRequested
    | EvidenceRetrieved
    | ResolutionRequested
    | ResolutionProposed
    | ThreadClosed
    | SuggestionCreated
    | SuggestionDecided
    | DocumentRevised
)
