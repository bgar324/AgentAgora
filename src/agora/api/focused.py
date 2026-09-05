"""HTTP contract for the single baseline Hypothesis Studio product."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from agora.focused.agents import FocusedAgentError
from agora.focused.models import PaperView, SearchQuery, SessionState, WorkspaceView
from agora.focused.service import FocusedPanelService, SessionError
from agora.focused.study_log import CONDITION_PATTERN, PARTICIPANT_ID_PATTERN

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


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PositionRequest(RequestModel):
    framing: str = Field(default="", max_length=4000)
    prior: str = Field(default="", max_length=4000)
    method: str = Field(default="", max_length=4000)
    expected: str = Field(default="", max_length=4000)


class CreateWorkspaceRequest(RequestModel):
    problem: str = Field(min_length=3, max_length=4000)
    position: PositionRequest | None = None
    demo: bool = False
    participant_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=PARTICIPANT_ID_PATTERN,
    )
    condition: str = Field(
        default="baseline",
        min_length=1,
        max_length=64,
        pattern=CONDITION_PATTERN,
    )


class SearchRequest(RequestModel):
    queries: list[SearchQuery] = Field(min_length=1, max_length=10)
    progress_generation: int | None = Field(default=None, ge=1)


class PerspectiveRequest(RequestModel):
    paper_id: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class NotepadEditRequest(RequestModel):
    version_id: str = Field(min_length=1, max_length=200)
    part: Literal["framing", "prior", "method", "expected"]
    text: str = Field(max_length=4000)


class NotepadVersionRequest(RequestModel):
    copy_current: bool = True


class NotepadDiscussRequest(RequestModel):
    version_id: str = Field(min_length=1, max_length=200)
    turns: int = Field(default=4, ge=1, le=8)


class NotepadAskRequest(RequestModel):
    version_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)
    topic_id: str | None = Field(default=None, min_length=1, max_length=200)


class NotepadVersionCommand(RequestModel):
    version_id: str = Field(min_length=1, max_length=200)


@focused_router.post("/workspaces")
async def create_workspace(
    request: CreateWorkspaceRequest,
    service: Service,
) -> WorkspaceView:
    return _guard(
        lambda: service.create_workspace(
            problem=request.problem,
            position=request.position.model_dump() if request.position else None,
            demo=request.demo,
            participant_id=request.participant_id,
            condition=request.condition,
        )
    )


@focused_router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str, service: Service) -> WorkspaceView:
    return _guard(lambda: service.workspace_view(workspace_id))


@focused_router.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str, service: Service) -> dict[str, str]:
    _guard(lambda: service.delete_workspace(workspace_id))
    return {"deleted": workspace_id}


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
async def paper_detail(
    session_id: str,
    paper_id: str,
    service: Service,
) -> dict[str, PaperView]:
    paper = await _acall(service.paper_detail(session_id, paper_id))
    return {"paper": PaperView.model_validate(paper.model_dump(mode="json"))}


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
            paper_id=request.paper_id,
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


@focused_router.post("/sessions/{session_id}/notepad/start")
async def start_notepad(session_id: str, service: Service) -> WorkspaceView:
    return await _acall_view(service, service.start_notepad(session_id))


@focused_router.post("/sessions/{session_id}/notepad/topics")
async def generate_notepad_topics(session_id: str, service: Service) -> WorkspaceView:
    return await _acall_view(service, service.generate_notepad_topics(session_id))


@focused_router.patch("/sessions/{session_id}/notepad/part")
async def edit_notepad_part(
    session_id: str,
    request: NotepadEditRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.edit_notepad_part(
            session_id,
            version_id=request.version_id,
            part=request.part,
            text=request.text,
        ),
    )


@focused_router.post("/sessions/{session_id}/notepad/versions")
async def add_notepad_version(
    session_id: str,
    request: NotepadVersionRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.add_notepad_version(
            session_id,
            copy_current=request.copy_current,
        ),
    )


@focused_router.put("/sessions/{session_id}/notepad/versions/{version_id}")
async def switch_notepad_version(
    session_id: str,
    version_id: str,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.switch_notepad_version(session_id, version_id=version_id),
    )


@focused_router.delete("/sessions/{session_id}/notepad/versions/{version_id}")
async def delete_notepad_version(
    session_id: str,
    version_id: str,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.delete_notepad_version(session_id, version_id=version_id),
    )


@focused_router.post("/sessions/{session_id}/notepad/discuss")
async def discuss_notepad(
    session_id: str,
    request: NotepadDiscussRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.discuss_notepad(
            session_id,
            version_id=request.version_id,
            turns=request.turns,
        ),
    )


@focused_router.post("/sessions/{session_id}/notepad/messages")
async def ask_notepad(
    session_id: str,
    request: NotepadAskRequest,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.ask_notepad(
            session_id,
            version_id=request.version_id,
            message=request.message,
            topic_id=request.topic_id,
        ),
    )


@focused_router.post("/sessions/{session_id}/notepad/summaries")
async def summarize_notepad(
    session_id: str,
    request: NotepadVersionCommand,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.summarize_notepad(
            session_id,
            version_id=request.version_id,
        ),
    )


@focused_router.post("/sessions/{session_id}/notepad/restart")
async def restart_notepad_review(
    session_id: str,
    request: NotepadVersionCommand,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(
        service,
        service.restart_notepad_review(
            session_id,
            version_id=request.version_id,
        ),
    )


@focused_router.post("/sessions/{session_id}/notepad/finish")
async def finish_notepad_study(
    session_id: str,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(service, service.finish_notepad_study(session_id))


@focused_router.delete("/sessions/{session_id}/notepad/chat")
async def clear_notepad_chat(
    session_id: str,
    service: Service,
) -> WorkspaceView:
    return await _acall_view(service, service.clear_notepad_chat(session_id))
