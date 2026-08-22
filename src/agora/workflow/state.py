from typing import Literal

from pydantic import BaseModel, Field

RunStatus = Literal[
    "active",
    "waiting",
    "complete",
    "failed",
    "cancelled",
]

WorkflowStage = Literal[
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

WorkType = Literal[
    "assign_thread",
    "answer_thread",
    "reply_to_thread",
    "retrieve_evidence",
    "update_thread_response",
    "summarize_thread",
    "reflect_perspectives",
]


class Work(BaseModel):
    kind: WorkType
    thread_id: str
    perspective_ids: list[str] = Field(default_factory=list)
    target_id: str | None = None
    query: str | None = None
    decision_id: str | None = None


class WorkflowState(BaseModel):
    run_id: str
    investigation_id: str
    status: RunStatus
    stage: WorkflowStage
    current_node: str | None = None
    version: int = 0
    waiting_for: WaitingFor | None = None
    active_thread_id: str | None = None
    document_version: int | None = None
    failure: str | None = None
