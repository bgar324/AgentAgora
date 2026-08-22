from agora.workflow.events import (
    ContributionAdded,
    EvidenceRequested,
    EvidenceRetrieved,
    Event,
    ParticipantsAssigned,
    ResolutionRequested,
    ThreadClosed,
    ThreadCreated,
    ThreadOpened,
)
from agora.workflow.state import Work, WorkflowState


def route(
    event: Event,
    state: WorkflowState,
) -> list[Work]:
    if state.stage != "deliberation":
        return []

    if isinstance(event, (ThreadCreated, ThreadOpened)):
        return [
            Work(
                kind="assign_thread",
                thread_id=event.thread_id,
            )
        ]

    if isinstance(event, ParticipantsAssigned):
        return [
            Work(
                kind="answer_thread",
                thread_id=event.thread_id,
                perspective_ids=event.perspective_ids,
            )
        ]

    if isinstance(event, ContributionAdded):
        if not event.requires_response:
            return []

        perspective_ids = list(
            dict.fromkeys(
                [
                    *(
                        [event.target_author_id]
                        if event.target_author_id
                        else []
                    ),
                    *event.mentioned_ids,
                ]
            )
        )

        if perspective_ids:
            return [
                Work(
                    kind="reply_to_thread",
                    thread_id=event.thread_id,
                    perspective_ids=perspective_ids,
                    target_id=event.contribution_id,
                )
            ]

        return []

    if isinstance(event, EvidenceRequested):
        return [
            Work(
                kind="retrieve_evidence",
                thread_id=event.thread_id,
                perspective_ids=[event.perspective_id],
                target_id=event.target_id,
                query=event.query,
            )
        ]

    if isinstance(event, EvidenceRetrieved) and event.thread_id is not None:
        return [
            Work(
                kind="update_thread_response",
                thread_id=event.thread_id,
                perspective_ids=[event.perspective_id],
                target_id=event.target_id,
            )
        ]

    if isinstance(event, ResolutionRequested):
        return [
            Work(
                kind="summarize_thread",
                thread_id=event.thread_id,
            )
        ]

    if isinstance(event, ThreadClosed):
        return [
            Work(
                kind="reflect_perspectives",
                thread_id=event.thread_id,
                perspective_ids=event.perspective_ids,
                decision_id=event.caused_by,
            ),
        ]

    return []
