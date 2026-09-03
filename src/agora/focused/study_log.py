"""Privacy-bounded assignment and interaction records for baseline studies.

These are observational attempt records, not the event-sourced workflow domain
events in ``agora.workflow.events``. Workflow events use deterministic IDs and
may contain research content; focused study events need per-attempt outcomes,
durations, privacy-safe metadata, and Supabase persistence.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PARTICIPANT_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
CONDITION_PATTERN: Final = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class StudyAction(StrEnum):
    WORKSPACE_CREATE = "workspace.create"
    WORKSPACE_DELETE = "workspace.delete"
    QUERIES_SUGGEST = "queries.suggest"
    PAPERS_SEARCH = "papers.search"
    PAPER_VIEW = "paper.view"
    PERSPECTIVE_CREATE = "perspective.create"
    PERSPECTIVE_REMOVE = "perspective.remove"
    DISCUSSION_START = "discussion.start"
    DOCUMENT_EDIT = "document.edit"
    VERSION_CREATE = "version.create"
    VERSION_SWITCH = "version.switch"
    VERSION_DELETE = "version.delete"
    CHAT_CLEAR = "chat.clear"
    DISCUSSION_RUN = "discussion.run"
    QUESTION_SEND = "question.send"
    SUMMARY_CREATE = "summary.create"
    REVIEW_RESTART = "review.restart"
    STUDY_FINISH = "study.finish"


class StudyStage(StrEnum):
    LIFECYCLE = "lifecycle"
    RETRIEVAL = "retrieval"
    PERSPECTIVES = "perspectives"
    DISCUSSION = "discussion"
    COMPLETION = "completion"


class StudyOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class StudyErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    MODEL_FAILURE = "model_failure"
    STORAGE_FAILURE = "storage_failure"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


ACTION_STAGES: Final[dict[StudyAction, StudyStage]] = {
    StudyAction.WORKSPACE_CREATE: StudyStage.LIFECYCLE,
    StudyAction.WORKSPACE_DELETE: StudyStage.LIFECYCLE,
    StudyAction.QUERIES_SUGGEST: StudyStage.RETRIEVAL,
    StudyAction.PAPERS_SEARCH: StudyStage.RETRIEVAL,
    StudyAction.PAPER_VIEW: StudyStage.RETRIEVAL,
    StudyAction.PERSPECTIVE_CREATE: StudyStage.PERSPECTIVES,
    StudyAction.PERSPECTIVE_REMOVE: StudyStage.PERSPECTIVES,
    StudyAction.DISCUSSION_START: StudyStage.DISCUSSION,
    StudyAction.DOCUMENT_EDIT: StudyStage.DISCUSSION,
    StudyAction.VERSION_CREATE: StudyStage.DISCUSSION,
    StudyAction.VERSION_SWITCH: StudyStage.DISCUSSION,
    StudyAction.VERSION_DELETE: StudyStage.DISCUSSION,
    StudyAction.CHAT_CLEAR: StudyStage.DISCUSSION,
    StudyAction.DISCUSSION_RUN: StudyStage.DISCUSSION,
    StudyAction.QUESTION_SEND: StudyStage.DISCUSSION,
    StudyAction.SUMMARY_CREATE: StudyStage.DISCUSSION,
    StudyAction.REVIEW_RESTART: StudyStage.DISCUSSION,
    StudyAction.STUDY_FINISH: StudyStage.COMPLETION,
}

_SAFE_DETAIL_KEYS: Final[dict[StudyAction, frozenset[str]]] = {
    StudyAction.WORKSPACE_CREATE: frozenset({"problem_characters", "demo"}),
    StudyAction.PAPERS_SEARCH: frozenset({"query_count"}),
    StudyAction.PERSPECTIVE_CREATE: frozenset(
        {"custom_name", "description_characters"}
    ),
    StudyAction.DOCUMENT_EDIT: frozenset({"part", "text_characters"}),
    StudyAction.VERSION_CREATE: frozenset({"copy_current"}),
    StudyAction.DISCUSSION_RUN: frozenset({"turns_requested"}),
    StudyAction.QUESTION_SEND: frozenset({"message_characters"}),
}

_OBJECT_ARGUMENTS: Final[
    dict[StudyAction, tuple[Literal["paper", "perspective", "version"], str]]
] = {
    StudyAction.PAPER_VIEW: ("paper", "paper_id"),
    StudyAction.PERSPECTIVE_CREATE: ("paper", "paper_id"),
    StudyAction.PERSPECTIVE_REMOVE: ("perspective", "perspective_id"),
    StudyAction.DOCUMENT_EDIT: ("version", "version_id"),
    StudyAction.VERSION_SWITCH: ("version", "version_id"),
    StudyAction.VERSION_DELETE: ("version", "version_id"),
    StudyAction.DISCUSSION_RUN: ("version", "version_id"),
    StudyAction.QUESTION_SEND: ("version", "version_id"),
    StudyAction.SUMMARY_CREATE: ("version", "version_id"),
    StudyAction.REVIEW_RESTART: ("version", "version_id"),
}


class StudyAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    workspace_id: str = Field(min_length=1, max_length=128)
    participant_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=PARTICIPANT_ID_PATTERN,
    )
    condition: str = Field(
        min_length=1,
        max_length=64,
        pattern=CONDITION_PATTERN,
    )
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("participant_id", "condition", mode="before")
    @classmethod
    def strip_identifiers(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class StudyEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    event_id: str = Field(
        default_factory=lambda: uuid4().hex,
        pattern=r"^[0-9a-f]{32}$",
    )
    event_seq: int | None = Field(default=None, ge=1)
    workspace_id: str = Field(min_length=1, max_length=128)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    participant_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=PARTICIPANT_ID_PATTERN,
    )
    condition: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=CONDITION_PATTERN,
    )
    action: StudyAction
    stage: StudyStage
    outcome: StudyOutcome
    occurred_at: datetime
    recorded_at: datetime | None = None
    duration_ms: int = Field(ge=0)
    revision_before: int | None = Field(default=None, ge=0)
    revision_after: int | None = Field(default=None, ge=0)
    object_type: Literal["paper", "perspective", "version"] | None = None
    object_id: str | None = Field(default=None, min_length=1, max_length=200)
    error_code: StudyErrorCode | None = None
    details: dict[str, str | int | bool] = Field(default_factory=dict)

    @field_validator("event_id", mode="before")
    @classmethod
    def normalize_event_id(cls, value: object) -> object:
        if isinstance(value, (str, UUID)):
            try:
                return UUID(str(value)).hex
            except ValueError:
                pass
        return value

    @model_validator(mode="after")
    def validate_closed_envelope(self) -> StudyEvent:
        if self.stage != ACTION_STAGES[self.action]:
            raise ValueError("study event stage does not match its action")
        if (self.object_type is None) != (self.object_id is None):
            raise ValueError("study event object type and ID must appear together")
        if self.outcome == StudyOutcome.SUCCESS and self.error_code is not None:
            raise ValueError("successful study events cannot have an error code")
        if self.outcome == StudyOutcome.FAILURE and self.error_code is None:
            raise ValueError("failed study events require an error code")
        unknown = set(self.details) - _SAFE_DETAIL_KEYS.get(self.action, frozenset())
        if unknown:
            raise ValueError(f"unsupported study event details: {sorted(unknown)}")
        if any(
            isinstance(value, str) and len(value) > 200
            for value in self.details.values()
        ):
            raise ValueError(
                "study event detail strings must be at most 200 characters"
            )
        return self


def safe_event_details(
    action: StudyAction,
    arguments: Mapping[str, object],
) -> dict[str, str | int | bool]:
    if action == StudyAction.WORKSPACE_CREATE:
        problem = arguments.get("problem")
        return {
            "problem_characters": len(problem) if isinstance(problem, str) else 0,
            "demo": arguments.get("demo") is True,
        }
    if action == StudyAction.PAPERS_SEARCH:
        queries = arguments.get("queries")
        return {"query_count": len(queries) if isinstance(queries, list) else 0}
    if action == StudyAction.PERSPECTIVE_CREATE:
        name = arguments.get("name")
        description = arguments.get("description")
        return {
            "custom_name": isinstance(name, str) and bool(name.strip()),
            "description_characters": (
                len(description) if isinstance(description, str) else 0
            ),
        }
    if action == StudyAction.DOCUMENT_EDIT:
        part = arguments.get("part")
        text = arguments.get("text")
        return {
            "part": str(part) if part is not None else "unknown",
            "text_characters": len(text) if isinstance(text, str) else 0,
        }
    if action == StudyAction.VERSION_CREATE:
        return {"copy_current": arguments.get("copy_current") is True}
    if action == StudyAction.DISCUSSION_RUN:
        turns = arguments.get("turns")
        return {"turns_requested": turns if isinstance(turns, int) else 0}
    if action == StudyAction.QUESTION_SEND:
        message = arguments.get("message")
        return {"message_characters": len(message) if isinstance(message, str) else 0}
    return {}


def build_study_event(
    *,
    event_id: str,
    action: StudyAction,
    assignment: StudyAssignment | None,
    workspace_id: str,
    session_id: str | None,
    outcome: StudyOutcome,
    occurred_at: datetime,
    duration_ms: int,
    revision_before: int | None,
    revision_after: int | None,
    arguments: Mapping[str, object],
    error_code: StudyErrorCode | None = None,
) -> StudyEvent:
    object_type: Literal["paper", "perspective", "version"] | None = None
    object_id: str | None = None
    object_argument = _OBJECT_ARGUMENTS.get(action)
    if outcome == StudyOutcome.SUCCESS and object_argument is not None:
        object_type, argument_name = object_argument
        candidate = arguments.get(argument_name)
        if isinstance(candidate, str) and candidate:
            object_id = candidate
        else:
            object_type = None

    return StudyEvent(
        event_id=event_id,
        workspace_id=workspace_id,
        session_id=session_id,
        participant_id=assignment.participant_id if assignment else None,
        condition=assignment.condition if assignment else None,
        action=action,
        stage=ACTION_STAGES[action],
        outcome=outcome,
        occurred_at=occurred_at,
        duration_ms=duration_ms,
        revision_before=revision_before,
        revision_after=revision_after,
        object_type=object_type,
        object_id=object_id,
        error_code=error_code,
        details=safe_event_details(action, arguments),
    )
