"""Standalone focused-panel HTTP API."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agora.focused.agents import FocusedAgentError
from agora.focused.models import (
    DeliberationRating,
    FacetEvidence,
    HypothesisConfirmationMode,
    HypothesisDev,
    QuestionStatus,
    ResearchQuestion,
    SearchQuery,
    SessionState,
    WorkspaceView,
)
from agora.focused.service import (
    MAX_SUGGESTED_QUERIES,
    FocusedPanelService,
    SessionError,
)

focused_router = APIRouter(prefix="/focused", tags=["focused-panel"])

T = TypeVar("T")


def get_service(request: Request) -> FocusedPanelService:
    return request.app.state.focused


Service = Annotated[FocusedPanelService, Depends(get_service)]


@focused_router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


def _err(exc: SessionError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


def _guard(call: Callable[[], T]) -> T:
    try:
        return call()
    except SessionError as exc:
        raise _err(exc) from exc
    except FocusedAgentError as exc:
        raise HTTPException(
            status_code=503,
            detail="The live model request failed. Check the server logs and try again.",
        ) from exc


async def _acall(coro: Awaitable[T]) -> T:
    try:
        return await coro
    except SessionError as exc:
        raise _err(exc) from exc
    except FocusedAgentError as exc:
        raise HTTPException(
            status_code=503,
            detail="The live model request failed. Check the server logs and try again.",
        ) from exc


async def _acall_view(
    service: FocusedPanelService,
    coro: Awaitable[SessionState],
) -> WorkspaceView:
    state = await _acall(coro)
    return service.workspace_view(state.workspace_id)


def _guard_view(
    service: FocusedPanelService,
    call: Callable[[], SessionState],
) -> WorkspaceView:
    state = _guard(call)
    return service.workspace_view(state.workspace_id)


# --- request schemas ---------------------------------------------------------


class PositionRequest(BaseModel):
    framing: str = Field(default="", max_length=4000)
    prior: str = Field(default="", max_length=4000)
    method: str = Field(default="", max_length=4000)
    expected: str = Field(default="", max_length=4000)


class CreateWorkspaceRequest(BaseModel):
    problem: str = Field(min_length=3, max_length=4000)
    research_questions: list[ResearchQuestion] = Field(
        default_factory=list,
        max_length=20,
    )
    position: PositionRequest | None = None
    arm: Literal["baseline", "guided"] = "guided"
    demo: bool = True


class UpdateSessionRequest(BaseModel):
    problem: str = Field(min_length=3, max_length=4000)
    research_questions: list[ResearchQuestion] = Field(
        default_factory=list,
        max_length=20,
    )


class SearchRequest(BaseModel):
    queries: list[SearchQuery] = Field(min_length=1, max_length=MAX_SUGGESTED_QUERIES)
    progress_generation: int | None = Field(default=None, ge=1)


class PerspectiveRequest(BaseModel):
    cluster_id: str = Field(min_length=1, max_length=200)
    facets: list[FacetEvidence] | None = Field(default=None, max_length=4)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    invited_perspective_ids: list[str] | None = Field(
        default=None,
        max_length=12,
    )


class IntegrateChildRequest(BaseModel):
    invited_perspective_ids: list[str] | None = Field(
        default=None,
        max_length=12,
    )


class InitializeDeliberationRequest(BaseModel):
    lead_perspective_id: str = Field(min_length=1, max_length=200)


class RoundRequest(BaseModel):
    lead_iid: int
    thread_id: str = Field(min_length=1, max_length=200)
    progress_generation: int | None = Field(default=None, ge=1)


class ResolutionDecisionRequest(BaseModel):
    decision: Literal["accept", "edit", "keep_open"]
    summary: str | None = Field(default=None, max_length=2000)
    note: str = Field(default="", max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    deliberation_id: str
    target_iid: int | None = None
    proactivity: Literal["low", "med", "high"] = "med"


class QuestionStatusRequest(BaseModel):
    status: QuestionStatus


class MergeHypothesesRequest(BaseModel):
    target_investigation_id: str
    source_version_id: str
    hypothesis: HypothesisDev


class HypothesisRequest(BaseModel):
    hypothesis: HypothesisDev
    mode: HypothesisConfirmationMode


class CompleteDeliberationRequest(BaseModel):
    selected_question_ids: list[str] = Field(default_factory=list, max_length=50)


class DeliberationRatingRequest(BaseModel):
    divergent: int = Field(ge=1, le=7)
    convergent: int = Field(ge=1, le=7)
    note: str = Field(default="", max_length=1000)


class DialogueStartRequest(BaseModel):
    progress_generation: int | None = Field(default=None, ge=1)


class DialogueSelectionRequest(BaseModel):
    proposal_ids: list[str] = Field(min_length=1, max_length=12)
    progress_generation: int | None = Field(default=None, ge=1)


class DialogueThreadRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=200)
    progress_generation: int | None = Field(default=None, ge=1)


class DialogueMessageRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)
    reply_to: str | None = Field(default=None, max_length=200)
    progress_generation: int | None = Field(default=None, ge=1)


class DialogueDecisionRequest(BaseModel):
    resolution_id: str = Field(min_length=1, max_length=200)
    action: Literal["close", "edit_close", "keep_open", "request_evidence"]
    consensus: str | None = Field(default=None, max_length=4000)
    disagreement: str | None = Field(default=None, max_length=4000)
    open_question: str | None = Field(default=None, max_length=4000)
    progress_generation: int | None = Field(default=None, ge=1)


NotepadPartName = Literal["framing", "prior", "method", "expected"]


class NotepadEditRequest(BaseModel):
    part: NotepadPartName
    text: str = Field(default="", max_length=4000)


class NotepadVersionRequest(BaseModel):
    copy_current: bool = True


class NotepadParticipantRequest(BaseModel):
    perspective_id: str = Field(min_length=1, max_length=200)
    participating: bool


class NotepadDiscussRequest(BaseModel):
    turns: int = Field(default=4, ge=1, le=8)


class NotepadAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class NotepadSummarizeRequest(BaseModel):
    part: NotepadPartName


class NotepadDecisionRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=200)
    action: Literal["approve", "edit", "reject"]
    text: str | None = Field(default=None, max_length=4000)
    reason: str = Field(default="", max_length=2000)


class DialogueContinuationRequest(BaseModel):
    resolution_id: str = Field(min_length=1, max_length=200)


# --- stage ① perspective construction ---------------------------------------


@focused_router.post("/workspaces")
async def create_workspace(
    request: CreateWorkspaceRequest, service: Service
) -> WorkspaceView:
    return _guard(
        lambda: service.create_workspace(
            problem=request.problem,
            research_questions=request.research_questions,
            position=(request.position.model_dump() if request.position else None),
            arm=request.arm,
            demo=request.demo,
        )
    )


@focused_router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str, service: Service) -> WorkspaceView:
    return _guard(lambda: service.workspace_view(workspace_id))


@focused_router.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str, service: Service) -> dict[str, str]:
    _guard(lambda: service.delete_workspace(workspace_id))
    return {"deleted": workspace_id}


@focused_router.put(
    "/workspaces/{workspace_id}/investigations/{investigation_id}/active"
)
async def activate_investigation(
    workspace_id: str,
    investigation_id: str,
    service: Service,
) -> WorkspaceView:
    return _guard(
        lambda: service.activate_investigation(workspace_id, investigation_id)
    )


@focused_router.post(
    "/workspaces/{workspace_id}/investigations/"
    "{parent_investigation_id}/questions/{question_id}/child"
)
async def create_child_investigation(
    workspace_id: str,
    parent_investigation_id: str,
    question_id: str,
    service: Service,
) -> WorkspaceView:
    return await _acall(
        service.create_child_investigation(
            workspace_id,
            parent_investigation_id,
            question_id,
        )
    )


@focused_router.post(
    "/workspaces/{workspace_id}/investigations/{parent_investigation_id}/"
    "children/{child_investigation_id}/integrate"
)
async def integrate_child_investigation(
    workspace_id: str,
    parent_investigation_id: str,
    child_investigation_id: str,
    service: Service,
    request: IntegrateChildRequest | None = None,
) -> WorkspaceView:
    return await _acall(
        service.integrate_child_investigation(
            workspace_id,
            parent_investigation_id,
            child_investigation_id,
            invited_perspective_ids=(
                request.invited_perspective_ids if request is not None else None
            ),
        )
    )


@focused_router.patch(
    "/workspaces/{workspace_id}/investigations/"
    "{investigation_id}/questions/{question_id}"
)
async def update_question_status(
    workspace_id: str,
    investigation_id: str,
    question_id: str,
    request: QuestionStatusRequest,
    service: Service,
) -> WorkspaceView:
    return _guard(
        lambda: service.set_question_status(
            workspace_id,
            investigation_id,
            question_id,
            request.status,
        )
    )


@focused_router.put("/workspaces/{workspace_id}/hypotheses/{version_id}/promote")
async def promote_hypothesis(
    workspace_id: str,
    version_id: str,
    service: Service,
) -> WorkspaceView:
    return _guard(lambda: service.promote_hypothesis(workspace_id, version_id))


@focused_router.post("/workspaces/{workspace_id}/hypotheses/merge")
async def merge_hypotheses(
    workspace_id: str,
    request: MergeHypothesesRequest,
    service: Service,
) -> WorkspaceView:
    return _guard(
        lambda: service.merge_hypotheses(
            workspace_id,
            target_investigation_id=request.target_investigation_id,
            source_version_id=request.source_version_id,
            hypothesis=request.hypothesis,
        )
    )


@focused_router.delete("/workspaces/{workspace_id}/hypotheses/{version_id}")
async def archive_hypothesis(
    workspace_id: str,
    version_id: str,
    service: Service,
) -> WorkspaceView:
    return _guard(lambda: service.archive_hypothesis(workspace_id, version_id))


@focused_router.put("/workspaces/{workspace_id}/hypotheses/{version_id}/restore")
async def restore_hypothesis(
    workspace_id: str,
    version_id: str,
    service: Service,
) -> WorkspaceView:
    return _guard(lambda: service.restore_hypothesis(workspace_id, version_id))


@focused_router.get("/sessions/{session_id}")
async def get_session(session_id: str, service: Service) -> SessionState:
    return _guard(lambda: service.get(session_id))


@focused_router.post("/sessions/{session_id}/search-progress")
async def start_search_progress(
    session_id: str,
    service: Service,
) -> dict[str, int]:
    generation = _guard(lambda: service.start_search_progress(session_id))
    return {"generation": generation}


@focused_router.get("/sessions/{session_id}/search-progress")
async def search_progress(
    session_id: str,
    service: Service,
    generation: Annotated[int | None, Query(ge=1)] = None,
    after: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return _guard(
        lambda: service.search_progress(
            session_id,
            generation=generation,
            after=after,
        )
    )


@focused_router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    request: UpdateSessionRequest,
    service: Service,
) -> WorkspaceView:
    return _guard_view(
        service,
        lambda: service.update_brief(
            session_id,
            problem=request.problem,
            research_questions=request.research_questions,
        ),
    )


@focused_router.post("/sessions/{session_id}/suggest-queries")
async def suggest_queries(session_id: str, service: Service) -> WorkspaceView:
    return await _acall_view(service, service.suggest_queries(session_id))


@focused_router.post("/sessions/{session_id}/search")
async def run_search(
    session_id: str,
    request: SearchRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.run_search(
            session_id,
            request.queries,
            progress_generation=request.progress_generation,
        ),
    )


@focused_router.get("/sessions/{session_id}/papers/{paper_id}")
async def paper_detail(session_id: str, paper_id: str, service: Service):
    paper = await _acall(service.paper_detail(session_id, paper_id))
    state = _guard(lambda: service.get(session_id))
    hits = [
        {
            "facet": evidence.facet,
            "text": evidence.text,
            "sentence_index": evidence.sentence_index,
        }
        for cluster in state.clusters
        for evidence in cluster.facets
        if (evidence.paper_id == paper_id and evidence.sentence_index is not None)
    ]
    return {"paper": paper.model_dump(mode="json"), "facet_hits": hits}


@focused_router.post("/sessions/{session_id}/perspectives")
async def generate_perspective(
    session_id: str,
    request: PerspectiveRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.generate_perspective(
            session_id,
            invited_perspective_ids=request.invited_perspective_ids,
            cluster_id=request.cluster_id,
            facets=request.facets,
            name=request.name,
            description=request.description,
        ),
    )


@focused_router.delete("/sessions/{session_id}/perspectives/{perspective_id}")
async def remove_perspective(
    session_id: str,
    perspective_id: str,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.remove_perspective(session_id, perspective_id),
    )


# --- stage ② multi-agent deliberation ----------------------------------------


@focused_router.post("/sessions/{session_id}/agents/{iid}/hypothesis")
async def agent_hypothesis(
    session_id: str,
    iid: int,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.develop_agent_hypothesis(session_id, iid),
    )


@focused_router.post("/sessions/{session_id}/deliberations")
async def create_deliberation(
    session_id: str,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(service, service.create_deliberation(session_id))


@focused_router.post(
    "/sessions/{session_id}/deliberations/{deliberation_id}/initialize"
)
async def initialize_deliberation(
    session_id: str,
    deliberation_id: str,
    request: InitializeDeliberationRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.initialize_deliberation(
            session_id,
            deliberation_id,
            request.lead_perspective_id,
        ),
    )


@focused_router.post("/sessions/{session_id}/deliberations/{deliberation_id}/rounds")
async def run_round(
    session_id: str,
    deliberation_id: str,
    request: RoundRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.run_round(
            session_id,
            deliberation_id,
            lead_iid=request.lead_iid,
            thread_id=request.thread_id,
            progress_generation=request.progress_generation,
        ),
    )


@focused_router.post("/sessions/{session_id}/dialogue/start")
async def start_dialogue(
    session_id: str,
    request: DialogueStartRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.start_dialogue(
            session_id,
            progress_generation=request.progress_generation,
        ),
    )


@focused_router.post("/sessions/{session_id}/dialogue/selection")
async def select_dialogue_directions(
    session_id: str,
    request: DialogueSelectionRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.select_dialogue_directions(
            session_id,
            proposal_ids=request.proposal_ids,
            progress_generation=request.progress_generation,
        ),
    )


@focused_router.post("/sessions/{session_id}/dialogue/threads/open")
async def open_dialogue_thread(
    session_id: str,
    request: DialogueThreadRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.open_dialogue_thread(
            session_id,
            thread_id=request.thread_id,
            progress_generation=request.progress_generation,
        ),
    )


@focused_router.post("/sessions/{session_id}/dialogue/messages")
async def message_dialogue_thread(
    session_id: str,
    request: DialogueMessageRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.message_dialogue_thread(
            session_id,
            thread_id=request.thread_id,
            message=request.message,
            reply_to=request.reply_to,
            progress_generation=request.progress_generation,
        ),
    )


@focused_router.post("/sessions/{session_id}/dialogue/decisions")
async def decide_dialogue_thread(
    session_id: str,
    request: DialogueDecisionRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.decide_dialogue_thread(
            session_id,
            resolution_id=request.resolution_id,
            action=request.action,
            consensus=request.consensus,
            disagreement=request.disagreement,
            open_question=request.open_question,
            progress_generation=request.progress_generation,
        ),
    )


@focused_router.post("/sessions/{session_id}/dialogue/threads/continue")
async def continue_dialogue_from_resolution(
    session_id: str,
    request: DialogueContinuationRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.continue_dialogue_from_resolution(
            session_id,
            resolution_id=request.resolution_id,
        ),
    )


@focused_router.get("/sessions/{session_id}/dialogue/report")
async def dialogue_report(
    session_id: str,
    service: Service,
) -> dict[str, str]:
    return _guard(lambda: {"report": service.dialogue_report(session_id)})


@focused_router.post("/sessions/{session_id}/notepad/start")
async def start_notepad(session_id: str, service: Service) -> WorkspaceView:
    return await _acall_view(service, service.start_notepad(session_id))


@focused_router.patch("/sessions/{session_id}/notepad/part")
async def edit_notepad_part(
    session_id: str, request: NotepadEditRequest, service: Service
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.edit_notepad_part(session_id, part=request.part, text=request.text),
    )


@focused_router.post("/sessions/{session_id}/notepad/versions")
async def add_notepad_version(
    session_id: str, request: NotepadVersionRequest, service: Service
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.add_notepad_version(session_id, copy_current=request.copy_current),
    )


@focused_router.put("/sessions/{session_id}/notepad/versions/{version_id}")
async def switch_notepad_version(
    session_id: str, version_id: str, service: Service
) -> WorkspaceView:
    return await _acall_view(
        service, service.switch_notepad_version(session_id, version_id=version_id)
    )


@focused_router.delete("/sessions/{session_id}/notepad/versions/{version_id}")
async def delete_notepad_version(
    session_id: str, version_id: str, service: Service
) -> WorkspaceView:
    return await _acall_view(
        service, service.delete_notepad_version(session_id, version_id=version_id)
    )


@focused_router.put("/sessions/{session_id}/notepad/participants")
async def set_notepad_participant(
    session_id: str, request: NotepadParticipantRequest, service: Service
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.set_notepad_participant(
            session_id,
            perspective_id=request.perspective_id,
            participating=request.participating,
        ),
    )


@focused_router.post("/sessions/{session_id}/notepad/discuss")
async def discuss_notepad(
    session_id: str, request: NotepadDiscussRequest, service: Service
) -> WorkspaceView:
    return await _acall_view(
        service, service.discuss_notepad(session_id, turns=request.turns)
    )


@focused_router.post("/sessions/{session_id}/notepad/messages")
async def ask_notepad(
    session_id: str, request: NotepadAskRequest, service: Service
) -> WorkspaceView:
    return await _acall_view(
        service, service.ask_notepad(session_id, message=request.message)
    )


@focused_router.post("/sessions/{session_id}/notepad/summaries")
async def summarize_notepad(
    session_id: str, request: NotepadSummarizeRequest, service: Service
) -> WorkspaceView:
    return await _acall_view(
        service, service.summarize_notepad(session_id, part=request.part)
    )


@focused_router.post("/sessions/{session_id}/notepad/decisions")
async def decide_notepad_proposal(
    session_id: str, request: NotepadDecisionRequest, service: Service
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.decide_notepad_proposal(
            session_id,
            proposal_id=request.proposal_id,
            action=request.action,
            text=request.text,
            reason=request.reason,
        ),
    )


@focused_router.delete("/sessions/{session_id}/notepad/chat")
async def clear_notepad_chat(session_id: str, service: Service) -> WorkspaceView:
    return await _acall_view(service, service.clear_notepad_chat(session_id))


@focused_router.put(
    "/sessions/{session_id}/deliberations/{deliberation_id}/rounds/{round_n}/resolution"
)
async def decide_thread_resolution(
    session_id: str,
    deliberation_id: str,
    round_n: int,
    request: ResolutionDecisionRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.decide_thread_resolution(
            session_id,
            deliberation_id,
            round_n,
            decision=request.decision,
            summary=request.summary,
            note=request.note,
        ),
    )


@focused_router.put("/sessions/{session_id}/deliberations/{deliberation_id}/hypothesis")
async def confirm_deliberation_hypothesis(
    session_id: str,
    deliberation_id: str,
    request: HypothesisRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.confirm_deliberation_hypothesis(
            session_id,
            deliberation_id,
            request.hypothesis,
            mode=request.mode,
        ),
    )


@focused_router.post(
    "/sessions/{session_id}/deliberations/{deliberation_id}/hypothesis/checkpoint"
)
async def save_deliberation_hypothesis(
    session_id: str,
    deliberation_id: str,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.save_deliberation_hypothesis(
            session_id,
            deliberation_id,
        ),
    )


@focused_router.post("/sessions/{session_id}/deliberations/{deliberation_id}/complete")
async def complete_deliberation(
    session_id: str,
    deliberation_id: str,
    service: Service,
    request: CompleteDeliberationRequest | None = None,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.complete_deliberation(
            session_id,
            deliberation_id,
            request.selected_question_ids if request is not None else [],
        ),
    )


@focused_router.put("/sessions/{session_id}/deliberations/{deliberation_id}/rating")
async def rate_deliberation(
    session_id: str,
    deliberation_id: str,
    request: DeliberationRatingRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.rate_deliberation(
            session_id,
            deliberation_id,
            DeliberationRating(
                divergent=request.divergent,
                convergent=request.convergent,
                note=request.note,
            ),
        ),
    )


@focused_router.get("/workspaces/{workspace_id}/export")
async def export_workspace(workspace_id: str, service: Service):
    return _guard(lambda: service.export_workspace(workspace_id))


@focused_router.post("/sessions/{session_id}/chat")
async def chat(
    session_id: str,
    request: ChatRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.chat(
            session_id,
            request.deliberation_id,
            message=request.message,
            target_iid=request.target_iid,
            proactivity=request.proactivity,
        ),
    )
