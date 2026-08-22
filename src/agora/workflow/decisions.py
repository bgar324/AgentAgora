from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class VersionRef(BaseModel):
    id: str
    version: int


class ProposalSelection(BaseModel):
    id: str
    run_id: str
    actor_id: str
    proposals: list[VersionRef]
    expected_version: int
    submitted_at: datetime


class ThreadDecision(BaseModel):
    id: str
    run_id: str
    actor_id: str
    thread: VersionRef
    resolution: VersionRef | None = None
    action: Literal[
        "close",
        "edit_close",
        "keep_open",
        "request_evidence",
        "reopen",
    ]
    consensus: str | None = None
    disagreement: str | None = None
    open_question: str | None = None
    query: str | None = None
    perspective_ids: list[str] = Field(default_factory=list)
    expected_version: int
    submitted_at: datetime


class SuggestionDecision(BaseModel):
    id: str
    run_id: str
    actor_id: str
    suggestion: VersionRef
    section_version: int
    action: Literal[
        "accept",
        "edit",
        "reject",
    ]
    text: str | None = None
    expected_version: int
    submitted_at: datetime
