"""Baseline study orchestration for retrieval, Perspectives, and draft review."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from pydantic import ValidationError

from agora.focused import agents
from agora.focused.clustering import density_partition
from agora.focused.demo_data import (
    DEMO_PAPERS,
)
from agora.focused.models import (
    FACETS,
    PERSONA_COLORS,
    ClusterCard,
    ClusteringDiagnostics,
    DiscussionTopic,
    ExpPaper,
    Facet,
    FacetEvidence,
    NotepadDoc,
    NotepadPart,
    PaperView,
    Perspective,
    PerspectiveView,
    QuestionReach,
    RetrievalTier,
    SessionState,
    SessionView,
    SuggestedQueryView,
    WorkspaceState,
    WorkspaceSummary,
    WorkspaceView,
)
from agora.focused.notepad import MAX_PERSPECTIVES, reconcile_roster
from agora.focused.study_log import (
    StudyAction,
    StudyAssignment,
    StudyErrorCode,
    StudyEvent,
    StudyOutcome,
    build_study_event,
)

if TYPE_CHECKING:
    from agora.focused.persistence import WorkspacePersistence
    from agora.focused.provider import FocusedProvider

from agora.focused.persistence import PersistenceConflict

logger = logging.getLogger(__name__)
MAX_SUGGESTED_QUERIES = 5
PAPERS_PER_QUERY = 20
MAX_RETRIEVED_PAPERS = 200
TARGET_CLUSTER_PAPERS = 30
MAX_CLUSTERS = 6
CLUSTER_REPRESENTATIVE_PAPERS = 5

MIN_CLUSTERING_CORPUS = 90
MIN_THREE_CLUSTER_PAPERS = 15
MAX_SEARCH_PROGRESS_EVENTS = 192
SearchProgressKind = Literal[
    "query_started",
    "query_completed",
    "query_failed",
    "retrieval_completed",
    "clustering_started",
    "clustering_completed",
]


@dataclass(frozen=True)
class QuestionRetrieval:
    answering: dict[str, ExpPaper]
    candidates: dict[str, ExpPaper]
    succeeded: bool
    expansion_queries: list[str]


@dataclass
class _StudyOperation:
    event_id: str
    action: StudyAction
    assignment: StudyAssignment | None
    workspace_id: str
    session_id: str | None
    occurred_at: datetime
    started_at: float
    revision_before: int | None
    arguments: Mapping[str, object]
    persisted: bool = False


_current_study_operation: ContextVar[_StudyOperation | None] = ContextVar(
    "focused_study_operation",
    default=None,
)


class SessionError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class WorkspaceConflict(SessionError):
    def __init__(self) -> None:
        super().__init__(
            "This workspace changed in another process. Its latest state was reloaded.",
            status=409,
        )


def _serialized_session_mutation(action: StudyAction):
    def decorate(method):
        signature = inspect.signature(method)

        @wraps(method)
        async def wrapped(
            self: FocusedPanelService,
            session_id: str,
            *args,
            **kwargs,
        ):
            session = self._require(session_id)
            workspace_id = session.state.workspace_id
            async with self._workspace_lock(workspace_id):
                session = self._require(session_id)
                async with session.lock:
                    snapshot = self._snapshot_workspace(workspace_id)
                    bound = signature.bind(self, session_id, *args, **kwargs)
                    operation = _StudyOperation(
                        event_id=uuid.uuid4().hex,
                        action=action,
                        assignment=self._study_assignments.get(workspace_id),
                        workspace_id=workspace_id,
                        session_id=session_id,
                        occurred_at=datetime.now(UTC),
                        started_at=time.monotonic(),
                        revision_before=snapshot[0].revision,
                        arguments={
                            name: value
                            for name, value in bound.arguments.items()
                            if name not in {"self", "session_id"}
                        },
                    )
                    token = _current_study_operation.set(operation)
                    try:
                        result = await method(self, session_id, *args, **kwargs)
                    except WorkspaceConflict as error:
                        self._record_study_failure(operation, error)
                        raise
                    except BaseException as error:
                        self._restore_workspace(snapshot)
                        self._record_study_failure(operation, error)
                        raise
                    else:
                        if not operation.persisted:
                            revision = self._require_workspace(workspace_id).revision
                            self._record_study_success(
                                operation,
                                revision_after=revision,
                            )
                        return result
                    finally:
                        _current_study_operation.reset(token)

        return wrapped

    return decorate


class _Session:
    def __init__(self, state: SessionState) -> None:
        self.state = state
        current_sequence = max(
            (
                int(perspective.id.split("-", 2)[1])
                for perspective in state.perspectives
                if perspective.id.startswith("persp-")
                and perspective.id.split("-", 2)[1].isdigit()
            ),
            default=0,
        )
        self._persp_seq = max(state.perspective_sequence, current_sequence)
        self.state.perspective_sequence = self._persp_seq
        self.lock = asyncio.Lock()

    def snapshot(self) -> tuple[SessionState, int]:
        return self.state.model_copy(deep=True), self._persp_seq

    def restore(self, snapshot: tuple[SessionState, int]) -> None:
        self.state, self._persp_seq = snapshot

    def next_perspective_id(self) -> str:
        self._persp_seq += 1
        self.state.perspective_sequence = self._persp_seq
        return f"persp-{self._persp_seq}"


class FocusedPanelService:
    def __init__(
        self,
        *,
        provider: FocusedProvider | None = None,
        embedder: Callable[[list[str]], Awaitable[np.ndarray]] | None = None,
        embedding_model: str = "unconfigured",
        s2: Any | None = None,
        persistence: WorkspacePersistence | None = None,
        retain_search_embeddings: bool = False,
    ) -> None:
        self._sessions: dict[str, _Session] = {}
        self._workspaces: dict[str, WorkspaceState] = {}
        self._workspace_locks: dict[str, asyncio.Lock] = {}
        self._study_assignments: dict[str, StudyAssignment] = {}
        self._retain_search_embeddings = retain_search_embeddings
        self._search_progress: dict[str, list[dict[str, Any]]] = {}
        self._search_progress_sequence: dict[str, int] = {}
        self._search_progress_generation: dict[str, int] = {}
        self._search_progress_active_generation: dict[str, int] = {}
        self._durable_snapshots: dict[
            str,
            tuple[
                WorkspaceState,
                dict[str, tuple[SessionState, int, int, int, int]],
            ],
        ] = {}
        self._provider = provider
        self._embedder = embedder
        self._embedding_model = embedding_model
        self._s2 = s2
        self._persistence = persistence
        if persistence is not None:
            workspaces, investigations = persistence.load()
            states = {state.id: state for state in investigations}
            for workspace in workspaces:
                self._workspaces[workspace.id] = workspace
                self._workspace_locks[workspace.id] = asyncio.Lock()
                for investigation_id in workspace.investigation_ids:
                    self._sessions[investigation_id] = _Session(
                        states[investigation_id]
                    )
                self._remember_durable(workspace.id)
            current_workspace_ids = set(self._workspaces)
            self._study_assignments = {
                assignment.workspace_id: assignment
                for assignment in persistence.load_study_assignments()
                if assignment.workspace_id in current_workspace_ids
            }

    @staticmethod
    def _study_error_code(error: BaseException) -> StudyErrorCode:
        if isinstance(error, asyncio.CancelledError):
            return StudyErrorCode.CANCELLED
        if isinstance(error, WorkspaceConflict):
            return StudyErrorCode.CONFLICT
        if isinstance(error, SessionError):
            if error.status == 404:
                return StudyErrorCode.NOT_FOUND
            if error.status == 409:
                return StudyErrorCode.CONFLICT
            return StudyErrorCode.INVALID_REQUEST
        if isinstance(error, agents.FocusedAgentError):
            return StudyErrorCode.MODEL_FAILURE
        if isinstance(error, PersistenceConflict):
            return StudyErrorCode.STORAGE_FAILURE
        return StudyErrorCode.INTERNAL_ERROR

    @staticmethod
    def _terminal_study_event(
        operation: _StudyOperation,
        *,
        outcome: StudyOutcome,
        revision_after: int | None,
        error_code: StudyErrorCode | None = None,
    ) -> StudyEvent:
        return build_study_event(
            event_id=operation.event_id,
            action=operation.action,
            assignment=operation.assignment,
            workspace_id=operation.workspace_id,
            session_id=operation.session_id,
            outcome=outcome,
            occurred_at=operation.occurred_at,
            duration_ms=max(
                0,
                int((time.monotonic() - operation.started_at) * 1000),
            ),
            revision_before=operation.revision_before,
            revision_after=revision_after,
            arguments=operation.arguments,
            error_code=error_code,
        )

    def _append_terminal_study_event(
        self,
        operation: _StudyOperation,
        *,
        outcome: StudyOutcome,
        revision_after: int | None,
        error_code: StudyErrorCode | None = None,
    ) -> None:
        if self._persistence is None:
            return
        try:
            event = self._terminal_study_event(
                operation,
                outcome=outcome,
                revision_after=revision_after,
                error_code=error_code,
            )
            self._persistence.append_study_event(event)
        except Exception:
            logger.exception(
                "Failed to append focused study event %s for workspace %s",
                operation.action.value,
                operation.workspace_id,
            )

    def _record_study_success(
        self,
        operation: _StudyOperation,
        *,
        revision_after: int | None,
    ) -> None:
        self._append_terminal_study_event(
            operation,
            outcome=StudyOutcome.SUCCESS,
            revision_after=revision_after,
        )

    def _record_study_failure(
        self,
        operation: _StudyOperation,
        error: BaseException,
    ) -> None:
        self._append_terminal_study_event(
            operation,
            outcome=StudyOutcome.FAILURE,
            revision_after=operation.revision_before,
            error_code=self._study_error_code(error),
        )

    # -- plumbing ----------------------------------------------------------

    def _require(self, session_id: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionError(f"session '{session_id}' not found", status=404)
        return session

    def start_search_progress(self, session_id: str) -> int:
        self._require(session_id)
        generation = self._search_progress_generation.get(session_id, 0) + 1
        self._search_progress_generation[session_id] = generation
        self._search_progress[session_id] = []
        self._search_progress_sequence[session_id] = 0
        return generation

    def search_progress(
        self,
        session_id: str,
        *,
        generation: int | None = None,
        after: int = 0,
    ) -> dict[str, Any]:
        self._require(session_id)
        current_generation = self._search_progress_generation.get(session_id, 0)
        if generation is not None and generation != current_generation:
            return {
                "generation": current_generation,
                "items": [],
                "next": after,
            }
        items = [
            item
            for item in self._search_progress.get(session_id, [])
            if item["sequence"] > after
        ]
        return {
            "generation": current_generation,
            "items": items,
            "next": items[-1]["sequence"] if items else after,
        }

    def _publish_search_progress(
        self,
        session_id: str,
        kind: SearchProgressKind,
        message: str,
        **details: Any,
    ) -> int | None:
        generation = self._search_progress_active_generation.get(session_id)
        if generation != self._search_progress_generation.get(session_id):
            return None
        sequence = self._search_progress_sequence.get(session_id, 0) + 1
        self._search_progress_sequence[session_id] = sequence
        payload = {
            "generation": generation,
            "sequence": sequence,
            "kind": kind,
            "message": message,
            **details,
        }
        history = self._search_progress.setdefault(session_id, [])
        history.append(payload)
        if len(history) > MAX_SEARCH_PROGRESS_EVENTS:
            del history[:-MAX_SEARCH_PROGRESS_EVENTS]
        return sequence

    def _forget_search_progress(self, session_id: str) -> None:
        self._search_progress.pop(session_id, None)
        self._search_progress_sequence.pop(session_id, None)
        self._search_progress_generation.pop(session_id, None)
        self._search_progress_active_generation.pop(session_id, None)

    def _workspace_lock(self, workspace_id: str) -> asyncio.Lock:
        return self._workspace_locks.setdefault(workspace_id, asyncio.Lock())

    def _require_workspace(self, workspace_id: str) -> WorkspaceState:
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise SessionError(f"workspace '{workspace_id}' not found", status=404)
        return workspace

    def _snapshot_workspace(
        self,
        workspace_id: str,
    ) -> tuple[
        WorkspaceState,
        dict[str, tuple[SessionState, int]],
    ]:
        workspace = self._require_workspace(workspace_id)
        return (
            workspace.model_copy(deep=True),
            {
                investigation_id: self._require(investigation_id).snapshot()
                for investigation_id in workspace.investigation_ids
            },
        )

    def _restore_workspace(
        self,
        snapshot: tuple[
            WorkspaceState,
            dict[str, tuple[SessionState, int]],
        ],
    ) -> None:
        workspace, sessions = snapshot
        restored_workspace = workspace.model_copy(deep=True)
        restored_sessions = {
            investigation_id: (
                session_snapshot[0].model_copy(deep=True),
                *session_snapshot[1:],
            )
            for investigation_id, session_snapshot in sessions.items()
        }
        for investigation_id, session in list(self._sessions.items()):
            if (
                session.state.workspace_id == restored_workspace.id
                and investigation_id not in restored_sessions
            ):
                self._sessions.pop(investigation_id)
                self._forget_search_progress(investigation_id)
        self._workspaces[restored_workspace.id] = restored_workspace
        for investigation_id, session_snapshot in restored_sessions.items():
            session = self._sessions.get(investigation_id)
            if session is None:
                session = _Session(session_snapshot[0])
                self._sessions[investigation_id] = session
            session.restore(session_snapshot)

    def _remember_durable(self, workspace_id: str) -> None:
        self._durable_snapshots[workspace_id] = self._snapshot_workspace(workspace_id)

    def _restore_durable(self, workspace_id: str) -> None:
        snapshot = self._durable_snapshots.get(workspace_id)
        if snapshot is not None:
            self._restore_workspace(snapshot)

    def _reload_workspace(self, workspace_id: str) -> None:
        if self._persistence is None:
            return
        workspaces, investigations = self._persistence.load()
        workspace = next(
            (item for item in workspaces if item.id == workspace_id),
            None,
        )
        for investigation_id, session in list(self._sessions.items()):
            if session.state.workspace_id == workspace_id:
                self._sessions.pop(investigation_id)
                self._forget_search_progress(investigation_id)
        if workspace is None:
            self._workspaces.pop(workspace_id, None)
            self._workspace_locks.pop(workspace_id, None)
            self._durable_snapshots.pop(workspace_id, None)
            self._study_assignments.pop(workspace_id, None)
            return
        states = {
            state.id: state
            for state in investigations
            if state.workspace_id == workspace_id
        }
        self._workspaces[workspace_id] = workspace
        for investigation_id in workspace.investigation_ids:
            self._sessions[investigation_id] = _Session(states[investigation_id])
        self._remember_durable(workspace_id)

    def _ensure_workspace_idle(self, workspace: WorkspaceState) -> None:
        if self._workspace_lock(workspace.id).locked() or any(
            self._require(investigation_id).lock.locked()
            for investigation_id in workspace.investigation_ids
        ):
            raise SessionError(
                "Wait for the current workspace action to finish.",
                status=409,
            )

    def _validated_workspace_state(
        self,
        workspace: WorkspaceState,
    ) -> tuple[WorkspaceState, list[SessionState]]:
        validated_workspace = WorkspaceState.model_validate(workspace.model_dump())
        investigations = [
            SessionState.model_validate(
                self._require(investigation_id).state.model_dump()
            )
            for investigation_id in workspace.investigation_ids
        ]
        return validated_workspace, investigations

    def _persist_workspace(self, workspace_id: str) -> None:
        workspace = self._require_workspace(workspace_id)
        expected_revision = workspace.revision
        workspace.revision += 1
        operation = _current_study_operation.get()
        event: StudyEvent | None = None
        try:
            validated_workspace, investigations = self._validated_workspace_state(
                workspace
            )
            if operation is not None and operation.workspace_id == workspace_id:
                event = self._terminal_study_event(
                    operation,
                    outcome=StudyOutcome.SUCCESS,
                    revision_after=workspace.revision,
                )
            if self._persistence is not None:
                self._persistence.save(
                    validated_workspace,
                    investigations,
                    expected_revision=expected_revision,
                    event=event,
                )
                if operation is not None and event is not None:
                    operation.persisted = True
        except PersistenceConflict as error:
            workspace.revision = expected_revision
            self._reload_workspace(workspace_id)
            raise WorkspaceConflict() from error
        except Exception:
            workspace.revision = expected_revision
            self._restore_durable(workspace_id)
            raise
        self._remember_durable(workspace_id)

    def _save_state(self, state: SessionState) -> SessionState:
        self._persist_workspace(state.workspace_id)
        return self._require(state.id).state

    @staticmethod
    def _session_view(state: SessionState) -> SessionView:
        notepad = state.notepad.model_copy(deep=True) if state.notepad else None
        if notepad is not None:
            boundaries = {
                version.id: version.visible_turn_start for version in notepad.versions
            }
            counts: dict[str, int] = {}
            visible_turns = []
            for turn in notepad.turns:
                index = counts.get(turn.version_id, 0)
                counts[turn.version_id] = index + 1
                if index < boundaries.get(turn.version_id, 0):
                    continue
                turn.citations = []
                visible_turns.append(turn)
            notepad.turns = visible_turns
            for version in notepad.versions:
                version.visible_turn_start = 0
            if notepad.final_snapshot is not None:
                for version in notepad.final_snapshot.versions:
                    version.visible_turn_start = 0
        return SessionView(
            id=state.id,
            workspace_id=state.workspace_id,
            created_at=state.created_at,
            problem=state.problem,
            position=state.position.model_copy(deep=True),
            suggested_queries=[
                SuggestedQueryView.model_validate(query.model_dump())
                for query in state.suggested_queries
            ],
            searched_queries=list(state.searched_queries),
            papers=[
                PaperView.model_validate(paper.model_dump()) for paper in state.papers
            ],
            perspectives=[
                PerspectiveView.model_validate(perspective.model_dump())
                for perspective in state.perspectives
            ],
            notepad=notepad,
            searched=state.searched,
        )

    def workspace_view(self, workspace_id: str) -> WorkspaceView:
        workspace = self._require_workspace(workspace_id)
        active = self._require(workspace.active_investigation_id).state
        return WorkspaceView(
            workspace=WorkspaceSummary(
                id=workspace.id,
                created_at=workspace.created_at,
                revision=workspace.revision,
                problem=workspace.problem,
            ),
            active=self._session_view(active),
        )

    def _demo(self, session: _Session) -> bool:
        return session.state.demo

    def _provider_for(self, session: _Session) -> FocusedProvider | None:
        return None if session.state.demo else self._provider

    def get(self, session_id: str) -> SessionState:
        """Return private server state for trusted in-process integrations."""
        return self._require(session_id).state

    # -- stage ① perspective construction ----------------------------------

    def create_workspace(
        self,
        *,
        problem: str,
        position: dict[str, str] | None = None,
        demo: bool,
        participant_id: str | None = None,
        condition: str = "baseline",
    ) -> WorkspaceView:
        clean_problem = problem.strip()
        if len(clean_problem) < 3:
            raise SessionError("Problem must be at least three characters.")
        workspace_id = uuid.uuid4().hex
        investigation_id = uuid.uuid4().hex
        try:
            assignment = StudyAssignment(
                workspace_id=workspace_id,
                participant_id=participant_id,
                condition=condition,
            )
        except ValidationError as error:
            raise SessionError("Invalid study assignment.", status=422) from error
        operation = _StudyOperation(
            event_id=uuid.uuid4().hex,
            action=StudyAction.WORKSPACE_CREATE,
            assignment=assignment,
            workspace_id=workspace_id,
            session_id=investigation_id,
            occurred_at=datetime.now(UTC),
            started_at=time.monotonic(),
            revision_before=None,
            arguments={"problem": clean_problem, "demo": demo},
        )
        state = SessionState(
            id=investigation_id,
            workspace_id=workspace_id,
            problem=clean_problem,
            position=NotepadDoc(**(position or {})),
            demo=demo,
        )
        workspace = WorkspaceState(
            id=workspace_id,
            schema_version=7,
            problem=clean_problem,
            root_investigation_id=investigation_id,
            active_investigation_id=investigation_id,
            investigation_ids=[investigation_id],
        )
        self._sessions[state.id] = _Session(state)
        self._workspaces[workspace.id] = workspace
        self._workspace_locks[workspace.id] = asyncio.Lock()
        self._study_assignments[workspace.id] = assignment
        try:
            if self._persistence is not None:
                validated_workspace, investigations = self._validated_workspace_state(
                    workspace
                )
                event = self._terminal_study_event(
                    operation,
                    outcome=StudyOutcome.SUCCESS,
                    revision_after=workspace.revision,
                )
                self._persistence.create(
                    validated_workspace,
                    investigations,
                    assignment=assignment,
                    event=event,
                )
                operation.persisted = True
            self._remember_durable(workspace.id)
        except Exception as error:
            self._sessions.pop(state.id, None)
            self._forget_search_progress(state.id)
            self._workspaces.pop(workspace.id, None)
            self._workspace_locks.pop(workspace.id, None)
            self._study_assignments.pop(workspace.id, None)
            self._durable_snapshots.pop(workspace.id, None)
            self._record_study_failure(operation, error)
            raise
        return self.workspace_view(workspace.id)

    def delete_workspace(self, workspace_id: str) -> None:
        workspace = self._require_workspace(workspace_id)
        operation = _StudyOperation(
            event_id=uuid.uuid4().hex,
            action=StudyAction.WORKSPACE_DELETE,
            assignment=self._study_assignments.get(workspace_id),
            workspace_id=workspace_id,
            session_id=workspace.active_investigation_id,
            occurred_at=datetime.now(UTC),
            started_at=time.monotonic(),
            revision_before=workspace.revision,
            arguments={},
        )
        try:
            self._ensure_workspace_idle(workspace)
            if self._persistence is not None:
                event = self._terminal_study_event(
                    operation,
                    outcome=StudyOutcome.SUCCESS,
                    revision_after=None,
                )
                self._persistence.delete(
                    workspace.id,
                    expected_revision=workspace.revision,
                    event=event,
                )
                operation.persisted = True
        except PersistenceConflict as error:
            self._reload_workspace(workspace_id)
            conflict = WorkspaceConflict()
            self._record_study_failure(operation, conflict)
            raise conflict from error
        except BaseException as error:
            self._record_study_failure(operation, error)
            raise
        for investigation_id in workspace.investigation_ids:
            self._sessions.pop(investigation_id, None)
            self._forget_search_progress(investigation_id)
        self._workspaces.pop(workspace.id, None)
        self._workspace_locks.pop(workspace.id, None)
        self._study_assignments.pop(workspace.id, None)
        self._durable_snapshots.pop(workspace.id, None)

    @staticmethod
    def _retryable_empty_search(state: SessionState) -> bool:
        return (
            state.searched
            and not state.papers
            and not state.clusters
            and not state.perspectives
            and state.notepad is None
        )

    def _ensure_searchable(self, state: SessionState) -> None:
        if state.searched and not self._retryable_empty_search(state):
            raise SessionError(
                "This study already has literature. Start over to replace it."
            )

    @_serialized_session_mutation(StudyAction.QUERIES_SUGGEST)
    async def suggest_queries(self, session_id: str) -> SessionState:
        session = self._require(session_id)
        state = session.state
        self._ensure_searchable(state)
        reaches: list[QuestionReach] = []
        if not state.research_questions:
            # Users provide the four-part position, not retrieval questions.
            state.research_questions = await agents.derive_research_questions(
                state.problem,
                position=state.position,
                provider=self._provider_for(session),
            )
        problem_suggestions = [
            suggestion.model_copy(
                update={"kind": "problem", "question_index": None, "round": 1}
            )
            for suggestion in await agents.suggest_queries(
                state.problem,
                state.research_questions,
                position=state.position,
                provider=self._provider_for(session),
                count=3 if state.research_questions else MAX_SUGGESTED_QUERIES,
            )
        ]
        question_suggestions = []
        for question_index, question in enumerate(state.research_questions):
            plan = await agents.plan_question_search(
                state.problem,
                question,
                provider=self._provider_for(session),
            )
            reaches.append(
                QuestionReach(
                    question=question,
                    form=plan.form,
                    candidates=plan.candidates,
                )
            )
            question_suggestions.append(
                [
                    query.model_copy(
                        update={
                            "kind": "question",
                            "question_index": question_index,
                            "round": 1,
                        }
                    )
                    for query in plan.queries
                ]
            )
        suggestions = [queries[0] for queries in question_suggestions if queries]
        suggestions.extend(problem_suggestions)
        suggestions.extend(
            query for queries in question_suggestions for query in queries[1:]
        )
        deduped = []
        seen = set()
        for suggestion in suggestions:
            clean_query = " ".join(suggestion.query.split())
            suggestion = suggestion.model_copy(update={"query": clean_query})
            key = clean_query.casefold()
            if clean_query and key not in seen and len(deduped) < MAX_SUGGESTED_QUERIES:
                seen.add(key)
                deduped.append(suggestion)
        if len(deduped) < MAX_SUGGESTED_QUERIES:
            fallbacks = await agents.suggest_queries(
                state.problem,
                state.research_questions,
                position=state.position,
                provider=None,
                count=MAX_SUGGESTED_QUERIES,
            )
            for suggestion in fallbacks:
                clean_query = " ".join(suggestion.query.split())
                key = clean_query.casefold()
                if clean_query and key not in seen:
                    seen.add(key)
                    deduped.append(
                        suggestion.model_copy(
                            update={
                                "query": clean_query,
                                "kind": "problem",
                                "question_index": None,
                                "round": 1,
                            }
                        )
                    )
                if len(deduped) == MAX_SUGGESTED_QUERIES:
                    break
        state.suggested_queries = deduped
        state.question_reach = reaches
        return self._save_state(state)

    def _demo_retrieve(self, queries: list[str]) -> list[ExpPaper]:
        scored: list[tuple[float, ExpPaper]] = []
        for paper in DEMO_PAPERS:
            text = f"{paper.title} {paper.abstract or ''}".lower()
            score = sum(
                len([w for w in agents._content_words(q) if w in text]) for q in queries
            )
            if score > 0:
                scored.append((score, paper))
        scored.sort(key=lambda pair: -pair[0])
        return [p.model_copy(deep=True) for _, p in scored[:20]]

    async def _live_retrieve(
        self,
        queries: list[str],
        *,
        session_id: str | None = None,
    ) -> tuple[list[ExpPaper], bool]:
        async def retrieve_one(
            query: str,
            query_run_id: int | None,
        ) -> tuple[list[ExpPaper], bool]:
            query_papers: dict[str, ExpPaper] = {}
            retrieved_for_query = 0
            succeeded = False
            failure_reason: str | None = None
            variants = [query]
            relaxed = agents.relaxed_search_query(query)
            if relaxed and relaxed.casefold() != query.casefold():
                variants.append(relaxed)
            for variant in variants:
                try:
                    results = await self._s2.search(
                        variant,
                        limit=PAPERS_PER_QUERY,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "focused paper search failed for %r: %s",
                        variant,
                        exc,
                    )
                    if " returned 429:" in str(exc):
                        failure_reason = "rate_limited"
                        break
                    failure_reason = "unavailable"
                    continue
                succeeded = True
                failure_reason = None
                retrieved_for_query = len(results)
                for result in results:
                    if result.id in query_papers:
                        continue
                    abstract_sentences = agents.split_sentences(result.abstract)
                    query_papers[result.id] = ExpPaper(
                        id=result.id,
                        title=result.title,
                        abstract=result.abstract,
                        abstract_sentences=abstract_sentences,
                        year=result.year,
                        venue=result.venue,
                        authors=[author.name for author in result.authors[:4]],
                        source_query=variant,
                        tldr=result.tldr,
                        open_access_pdf_url=result.open_access_pdf_url,
                        specter_v2=result.specter_v2,
                    )
                if results:
                    break
            if session_id is not None:
                if failure_reason is None:
                    self._publish_search_progress(
                        session_id,
                        "query_completed",
                        f"Searched {query}...retrieved {retrieved_for_query} papers",
                        query=query,
                        retrieved=retrieved_for_query,
                        query_run_id=query_run_id,
                    )
                else:
                    self._publish_search_progress(
                        session_id,
                        "query_failed",
                        f"Search stopped for {query}.",
                        query=query,
                        reason=failure_reason,
                        query_run_id=query_run_id,
                    )
            return list(query_papers.values()), succeeded

        query_runs = [
            (
                query,
                (
                    self._publish_search_progress(
                        session_id,
                        "query_started",
                        f"Searching papers for {query}.",
                        query=query,
                    )
                    if session_id is not None
                    else None
                ),
            )
            for query in queries
        ]
        tasks = []
        try:
            async with asyncio.TaskGroup() as task_group:
                tasks = [
                    task_group.create_task(retrieve_one(query, query_run_id))
                    for query, query_run_id in query_runs
                ]
        except* Exception as errors:  # noqa: BLE001
            raise errors.exceptions[0]

        papers: dict[str, ExpPaper] = {}
        search_succeeded = False
        for task in tasks:
            query_papers, succeeded = task.result()
            search_succeeded = search_succeeded or succeeded
            for paper in query_papers:
                papers.setdefault(paper.id, paper)
        return list(papers.values())[:MAX_RETRIEVED_PAPERS], search_succeeded

    async def _retrieve_queries(
        self, session: _Session, queries: list[str]
    ) -> tuple[list[ExpPaper], bool]:
        clean = [query.strip() for query in queries if query.strip()]
        if not clean:
            return [], False
        if self._demo(session):
            for query in clean:
                query_run_id = self._publish_search_progress(
                    session.state.id,
                    "query_started",
                    f"Searching papers for {query}.",
                    query=query,
                )
                retrieved = len(self._demo_retrieve([query]))
                self._publish_search_progress(
                    session.state.id,
                    "query_completed",
                    f"Searched {query}...retrieved {retrieved} papers",
                    query=query,
                    retrieved=retrieved,
                    query_run_id=query_run_id,
                )
            return self._demo_retrieve(clean), True

        return await self._live_retrieve(clean, session_id=session.state.id)

    @staticmethod
    def _bounded_corpus(
        answering: dict[str, ExpPaper],
        angle: dict[str, ExpPaper],
        candidate_groups: list[list[ExpPaper]],
    ) -> list[ExpPaper]:
        selected: dict[str, ExpPaper] = {}

        def add(paper: ExpPaper, tier: RetrievalTier) -> None:
            if paper.id not in selected and len(selected) < MAX_RETRIEVED_PAPERS:
                selected[paper.id] = paper.model_copy(
                    deep=True,
                    update={"retrieval_tier": tier},
                )

        for paper in answering.values():
            add(paper, "answer")
        for paper in angle.values():
            add(paper, "problem")
        depth = max((len(group) for group in candidate_groups), default=0)
        for rank in range(depth):
            for group in candidate_groups:
                if rank < len(group):
                    add(group[rank], "candidate")
        return list(selected.values())

    @staticmethod
    def _target_cluster_count(paper_count: int) -> int:
        if paper_count < 2:
            return 1
        if paper_count < MIN_THREE_CLUSTER_PAPERS:
            return 2
        return max(
            3,
            min(
                MAX_CLUSTERS,
                (paper_count + TARGET_CLUSTER_PAPERS - 1) // TARGET_CLUSTER_PAPERS,
            ),
        )

    @staticmethod
    def _kmeans_clusters(papers: list[ExpPaper], k: int) -> list[list[ExpPaper]]:
        from sklearn.cluster import KMeans
        from sklearn.feature_extraction.text import TfidfVectorizer

        texts = [f"{p.title} {p.abstract or ''}" for p in papers]
        matrix = TfidfVectorizer(stop_words="english", max_features=512).fit_transform(
            texts
        )
        k = (
            max(2, min(k, len(papers) - 1))
            if len(papers) > k
            else max(2, len(papers) - 1)
        )
        labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(matrix)
        groups: list[list[ExpPaper]] = [[] for _ in range(k)]
        for paper, label in zip(papers, labels):
            groups[int(label)].append(paper)
        return [g for g in groups if g]

    @staticmethod
    def _embedding_clusters(
        papers: list[ExpPaper],
        k: int = 6,
    ) -> list[list[ExpPaper]]:
        """Cluster complete SPECTERv2 embeddings with local dependencies only."""
        if len(papers) < 4 or not all(paper.specter_v2 for paper in papers):
            return []
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import normalize

        matrix = normalize(
            np.asarray([paper.specter_v2 for paper in papers], dtype=np.float32)
        )
        n_clusters = max(2, min(k, len(papers) - 1))
        labels = KMeans(
            n_clusters=n_clusters,
            n_init=10,
            random_state=0,
        ).fit_predict(matrix)
        groups: list[list[ExpPaper]] = [[] for _ in range(n_clusters)]
        for paper, label in zip(papers, labels):
            groups[int(label)].append(paper)
        return [group for group in groups if group]

    @staticmethod
    def _balanced_fallback_clusters(
        papers: list[ExpPaper],
        k: int,
    ) -> list[list[ExpPaper]]:
        count = max(1, min(k, len(papers)))
        groups: list[list[ExpPaper]] = [[] for _ in range(count)]
        for index, paper in enumerate(papers):
            groups[index % count].append(paper)
        return [group for group in groups if group]

    @staticmethod
    def _attach_unassigned_papers(
        groups: list[list[ExpPaper]],
        unassigned: list[ExpPaper],
    ) -> list[list[ExpPaper]]:
        """Attach density-noise papers to the nearest group deterministically."""
        if not groups or not unassigned:
            return groups
        centroids: list[np.ndarray | None] = []
        terms: list[set[str]] = []
        for group in groups:
            vectors = [
                np.asarray(paper.specter_v2, dtype=np.float32)
                for paper in group
                if paper.specter_v2
            ]
            centroids.append(
                np.mean(vectors, axis=0) if len(vectors) == len(group) else None
            )
            terms.append(
                set(
                    agents._content_words(
                        " ".join(
                            f"{paper.title} {paper.abstract or ''}" for paper in group
                        )
                    )
                )
            )
        for paper in unassigned:
            paper_terms = set(
                agents._content_words(f"{paper.title} {paper.abstract or ''}")
            )
            vector = (
                np.asarray(paper.specter_v2, dtype=np.float32)
                if paper.specter_v2
                else None
            )
            scores: list[tuple[float, int, int, int]] = []
            for index, centroid in enumerate(centroids):
                if (
                    vector is not None
                    and centroid is not None
                    and vector.shape == centroid.shape
                ):
                    denominator = float(
                        np.linalg.norm(vector) * np.linalg.norm(centroid)
                    )
                    cosine = (
                        float(np.dot(vector, centroid) / denominator)
                        if denominator
                        else -1.0
                    )
                else:
                    cosine = -1.0
                scores.append((cosine, len(paper_terms & terms[index]), -index, index))
            destination = max(scores)[3]
            groups[destination].append(paper)
        return groups

    @staticmethod
    def _centroid_order(papers: list[ExpPaper]) -> list[ExpPaper]:
        """Typical-first: papers nearest the cluster's embedding centroid
        first (the mentor's 'centroid papers'). Papers without embeddings
        keep their order at the end."""
        if not papers or not all(p.specter_v2 for p in papers):
            return papers
        matrix = np.array([p.specter_v2 for p in papers], dtype=np.float32)
        centroid = matrix.mean(axis=0)
        distances = np.linalg.norm(matrix - centroid, axis=1)
        return [p for _, p in sorted(zip(distances, papers), key=lambda x: x[0])]

    def _clustering_diagnostics(
        self,
        method: str,
        papers: list[ExpPaper],
        groups: list[list[ExpPaper]],
        *,
        requested_clusters: int,
    ) -> ClusteringDiagnostics:
        """Record what actually ran: method, embedding coverage, sizes, and
        a cosine silhouette when there are ≥2 valid clusters.

        Comparability: silhouettes in different feature spaces are not
        comparable across methods, so whenever embedding coverage is FULL
        the score is computed on the shared SPECTERv2 representation —
        whichever method produced the labels. A TF-IDF labeling scored on
        SPECTER answers the question the evaluation actually asks: how well
        does the lexical partition align with citation-space structure?
        Partial coverage falls back to the TF-IDF matrix (comparable only
        among TF-IDF runs)."""
        lookup = {p.id: gi for gi, g in enumerate(groups) for p in g}
        ordered = [p for p in papers if p.id in lookup]
        labels = [lookup[p.id] for p in ordered]
        silhouette: float | None = None
        if 2 <= len(set(labels)) <= len(ordered) - 1:
            try:
                from sklearn.metrics import silhouette_score

                full_coverage = all(p.specter_v2 for p in ordered)
                if full_coverage:
                    matrix = np.array([p.specter_v2 for p in ordered], dtype=np.float32)
                else:
                    from sklearn.feature_extraction.text import TfidfVectorizer

                    matrix = TfidfVectorizer(
                        stop_words="english", max_features=512
                    ).fit_transform([f"{p.title} {p.abstract or ''}" for p in ordered])
                silhouette = float(silhouette_score(matrix, labels, metric="cosine"))
            except Exception:  # noqa: BLE001 — diagnostics never fail the search
                silhouette = None
        return ClusteringDiagnostics(
            method=method,  # type: ignore[arg-type]
            embedded=sum(1 for p in papers if p.specter_v2),
            total=len(papers),
            requested_clusters=requested_clusters,
            cluster_sizes=[len(g) for g in groups],
            silhouette=silhouette,
            retrieval_tier_counts={
                tier: sum(paper.retrieval_tier == tier for paper in papers)
                for tier in ("answer", "problem", "candidate")
                if any(paper.retrieval_tier == tier for paper in papers)
            },
        )

    @staticmethod
    def _validate_facet_source(
        evidence: FacetEvidence, papers: dict[str, ExpPaper]
    ) -> FacetEvidence:
        if evidence.edited:
            return evidence.model_copy(
                update={"paper_id": None, "sentence_index": None, "sentence": None}
            )
        if not evidence.paper_id or evidence.paper_id not in papers:
            return evidence.model_copy(
                update={
                    "text": "",
                    "paper_id": None,
                    "sentence_index": None,
                    "sentence": None,
                }
            )
        paper = papers[evidence.paper_id]
        mapped = agents.map_facet_to_sentence(
            paper,
            evidence.model_copy(update={"sentence_index": None, "sentence": None}),
        )
        if mapped.sentence_index is None:
            return evidence.model_copy(
                update={
                    "text": "",
                    "paper_id": None,
                    "sentence_index": None,
                    "sentence": None,
                }
            )
        return mapped

    async def _retrieve_question(
        self,
        session: _Session,
        reach: QuestionReach,
        round1_queries: list[str],
    ) -> QuestionRetrieval:
        reach.queries_r1 = list(round1_queries)
        round1_papers, round1_succeeded = await self._retrieve_queries(
            session,
            round1_queries,
        )
        hits = {paper.id: paper for paper in round1_papers}
        assessment = await agents.assess_question_papers(
            reach.question,
            reach.candidates,
            list(hits.values()),
            provider=self._provider_for(session),
        )
        reach.vocabulary = assessment.vocabulary
        selected: dict[str, Any] = {item.paper_id: item for item in assessment.selected}
        selected_papers = [hits[paper_id] for paper_id in selected if paper_id in hits]
        expansion = await agents.expand_question_search(
            reach.question,
            reach.candidates,
            reach.vocabulary,
            selected_papers,
            provider=self._provider_for(session),
        )
        round2_queries = list(
            dict.fromkeys(
                query.query.strip()
                for query in expansion
                if query.query.strip() and query.query.strip() not in round1_queries
            )
        )
        reach.queries_r2 = round2_queries
        round2_papers, round2_succeeded = await self._retrieve_queries(
            session,
            round2_queries,
        )
        fresh = [paper for paper in round2_papers if paper.id not in hits]
        if fresh:
            follow_up = await agents.assess_question_papers(
                reach.question,
                reach.candidates,
                fresh,
                provider=self._provider_for(session),
            )
            for item in follow_up.selected:
                selected.setdefault(item.paper_id, item)
            for paper in fresh:
                hits.setdefault(paper.id, paper)
        reach.retrieved = len(hits)
        reach.selected = list(selected.values())
        reach.reached = bool(reach.selected)
        answering = {
            paper_id: hits[paper_id] for paper_id in selected if paper_id in hits
        }
        return QuestionRetrieval(
            answering=answering,
            candidates=hits,
            succeeded=round1_succeeded or round2_succeeded,
            expansion_queries=round2_queries,
        )

    @_serialized_session_mutation(StudyAction.PAPERS_SEARCH)
    async def run_search(
        self,
        session_id: str,
        queries: list[str],
        *,
        progress_generation: int | None = None,
    ) -> SessionState:
        session = self._require(session_id)
        state = session.state
        if progress_generation is None:
            self.start_search_progress(state.id)
        elif self._search_progress_generation.get(state.id) != progress_generation:
            raise SessionError("Search progress generation is stale.", status=409)
        self._search_progress_active_generation[state.id] = (
            self._search_progress_generation[state.id]
        )
        self._ensure_searchable(state)
        queries = [q.strip() for q in queries if q.strip()]
        if not queries:
            raise SessionError("Pick at least one query to search.")

        selected_queries = set(queries)
        known_queries = {suggestion.query for suggestion in state.suggested_queries}
        angle_queries = list(
            dict.fromkeys(
                [
                    suggestion.query
                    for suggestion in state.suggested_queries
                    if suggestion.query in selected_queries
                    and suggestion.kind == "problem"
                ]
                + [query for query in queries if query not in known_queries]
            )
        )
        angle_papers, search_succeeded = await self._retrieve_queries(
            session,
            angle_queries,
        )
        angle_by_id = {paper.id: paper for paper in angle_papers}
        answering_by_id: dict[str, ExpPaper] = {}
        question_candidate_groups: list[list[ExpPaper]] = []

        reaches = [
            reach.model_copy(
                deep=True,
                update={
                    "queries_r1": [],
                    "queries_r2": [],
                    "retrieved": 0,
                    "selected": [],
                    "vocabulary": [],
                    "reached": False,
                },
            )
            for reach in state.question_reach
        ]
        while len(reaches) < len(state.research_questions):
            question = state.research_questions[len(reaches)]
            reaches.append(QuestionReach(question=question, candidates=[question]))

        question_tasks = []
        try:
            async with asyncio.TaskGroup() as task_group:
                for question_index, reach in enumerate(reaches):
                    round1 = list(
                        dict.fromkeys(
                            suggestion.query
                            for suggestion in state.suggested_queries
                            if suggestion.query in selected_queries
                            and suggestion.kind == "question"
                            and suggestion.question_index == question_index
                        )
                    )
                    question_tasks.append(
                        task_group.create_task(
                            self._retrieve_question(session, reach, round1)
                        )
                    )
        except* Exception as errors:  # noqa: BLE001
            raise errors.exceptions[0]

        automatic_queries: list[str] = []
        for task in question_tasks:
            retrieval = task.result()
            search_succeeded = search_succeeded or retrieval.succeeded
            automatic_queries.extend(retrieval.expansion_queries)
            question_candidate_groups.append(list(retrieval.candidates.values()))
            for paper_id, paper in retrieval.answering.items():
                answering_by_id.setdefault(paper_id, paper)
        state.question_reach = reaches
        papers = self._bounded_corpus(
            answering_by_id,
            angle_by_id,
            question_candidate_groups,
        )
        rate_limited = any(
            item.get("kind") == "query_failed" and item.get("reason") == "rate_limited"
            for item in self._search_progress.get(session_id, [])
        )
        if len(papers) < MIN_CLUSTERING_CORPUS and not rate_limited:
            prior_queries = list(dict.fromkeys([*queries, *automatic_queries]))
            corpus_expansion = await agents.expand_corpus_search(
                state.problem,
                state.research_questions,
                prior_queries,
                [pair for reach in reaches for pair in reach.vocabulary],
                current_papers=len(papers),
                target_papers=MIN_CLUSTERING_CORPUS,
                provider=self._provider_for(session),
            )
            expansion_queries = [suggestion.query for suggestion in corpus_expansion]
            expansion_papers, expansion_succeeded = await self._retrieve_queries(
                session,
                expansion_queries,
            )
            search_succeeded = search_succeeded or expansion_succeeded
            if expansion_papers:
                question_candidate_groups.append(expansion_papers)
            automatic_queries.extend(expansion_queries)
            papers = self._bounded_corpus(
                answering_by_id,
                angle_by_id,
                question_candidate_groups,
            )
        failed_searches = [
            item
            for item in self._search_progress.get(session_id, [])
            if item.get("kind") == "query_failed"
        ]
        rate_limited = any(
            item.get("reason") == "rate_limited" for item in failed_searches
        )
        if not papers:
            if rate_limited:
                raise SessionError(
                    "Paper search is temporarily rate-limited. "
                    "Wait a minute and try again.",
                    status=503,
                )
            if not search_succeeded:
                raise SessionError(
                    "Paper search is temporarily unavailable. Try again.",
                    status=503,
                )
            raise SessionError(
                "No papers matched those searches. The search was not saved; "
                "try again with shorter academic keywords.",
                status=422,
            )
        completed_searches = [
            item
            for item in self._search_progress.get(session_id, [])
            if item.get("kind") == "query_completed"
        ]
        finished_searches = [
            item
            for item in self._search_progress.get(session_id, [])
            if item.get("kind") in {"query_completed", "query_failed"}
        ]
        retrieved_total = sum(
            int(item.get("retrieved", 0)) for item in completed_searches
        )
        self._publish_search_progress(
            session_id,
            "retrieval_completed",
            (
                f"Searched {retrieved_total} papers; retained {len(papers)} "
                "after deduplication."
            ),
            retrieved=retrieved_total,
            retained=len(papers),
            query_count=len(finished_searches),
        )

        requested_clusters = self._target_cluster_count(len(papers))
        self._publish_search_progress(
            session_id,
            "clustering_started",
            (
                f"Clustering {len(papers)} retained papers into "
                f"{requested_clusters} groups."
            ),
            papers=len(papers),
            requested_clusters=requested_clusters,
        )

        partition_representatives: list[list[ExpPaper]] | None = None
        unassigned_papers: list[ExpPaper] = []
        required_clusters = min(
            requested_clusters,
            3 if len(papers) >= MIN_THREE_CLUSTER_PAPERS else 2,
        )
        partition = density_partition(
            papers,
            requested_clusters=requested_clusters,
        )
        if partition is not None and len(partition.groups) >= required_clusters:
            groups = partition.groups
            partition_representatives = partition.representatives
            unassigned_papers = partition.unassigned
            method = "specter_hdbscan_dpp"
        elif requested_clusters == 1:
            groups = [papers]
            method = "single_group"
        else:
            groups = self._embedding_clusters(papers, k=requested_clusters)
            method = "specter_kmeans"
            if len(groups) < required_clusters:
                groups = (
                    self._kmeans_clusters(papers, k=requested_clusters)
                    if len(papers) >= 4
                    else []
                )
                method = "tfidf_kmeans"
            if len(groups) < required_clusters:
                groups = self._balanced_fallback_clusters(
                    papers,
                    requested_clusters,
                )
                method = "balanced_fallback"
        groups = self._attach_unassigned_papers(groups, unassigned_papers)

        state.clustering = self._clustering_diagnostics(
            method,
            papers,
            groups,
            requested_clusters=requested_clusters,
        )

        state.papers = papers
        state.unassigned_paper_ids = []
        state.searched = True
        state.searched_queries = list(dict.fromkeys([*queries, *automatic_queries]))

        clusters: list[ClusterCard] = []
        ordered_groups = [self._centroid_order(group) for group in groups]
        namings = await agents.name_clusters(
            ordered_groups,
            provider=self._provider_for(session),
        )
        for idx, group in enumerate(ordered_groups):
            naming = namings[idx] if idx < len(namings) else None
            representatives = (
                partition_representatives[idx]
                if partition_representatives is not None
                and idx < len(partition_representatives)
                else group[:CLUSTER_REPRESENTATIVE_PAPERS]
            )
            facets = await agents.extract_cluster_facets(
                representatives,
                provider=self._provider_for(session),
            )
            # Provenance is enforced against the abstracts the model read.
            by_id = {paper.id: paper for paper in representatives}
            grounded_by_facet: dict[Facet, FacetEvidence] = {}
            for evidence in facets:
                if evidence.facet in grounded_by_facet:
                    continue
                validated = self._validate_facet_source(evidence, by_id)
                if validated.text.strip():
                    grounded_by_facet[evidence.facet] = validated
            fallback_by_facet = {
                evidence.facet: evidence
                for evidence in agents.fallback_cluster_facets(representatives)
            }
            grounded = [
                grounded_by_facet.get(facet)
                or fallback_by_facet.get(facet)
                or FacetEvidence(facet=facet, text="")
                for facet in FACETS
            ]
            clusters.append(
                ClusterCard(
                    id=f"cluster-{idx + 1}",
                    name=naming.name if naming else f"Literature group {idx + 1}",
                    blurb=naming.blurb if naming else "",
                    facets=grounded,
                    paper_ids=[p.id for p in group],
                    representative_paper_ids=[p.id for p in representatives],
                )
            )
        known_ids = {paper.id for paper in state.papers}
        clustered_ids = {
            paper_id for cluster in clusters for paper_id in cluster.paper_ids
        }
        unassigned_ids = set(state.unassigned_paper_ids)
        if (
            clustered_ids & unassigned_ids
            or clustered_ids | unassigned_ids != known_ids
        ):
            raise RuntimeError(
                "clustering must assign or explicitly unassign every paper"
            )
        self._publish_search_progress(
            session_id,
            "clustering_completed",
            (
                f"Created {len(clusters)} clusters; "
                f"{len(unassigned_papers)} papers unassigned."
            ),
            papers=len(papers),
            clusters=len(clusters),
            unassigned=len(unassigned_papers),
            method=method,
        )
        if not self._retain_search_embeddings:
            for paper in state.papers:
                paper.specter_v2 = None
        state.clusters = clusters
        return self._save_state(state)

    async def paper_detail(self, session_id: str, paper_id: str) -> ExpPaper:
        session = self._require(session_id)
        state = session.state
        workspace = self._require_workspace(state.workspace_id)
        operation = _StudyOperation(
            event_id=uuid.uuid4().hex,
            action=StudyAction.PAPER_VIEW,
            assignment=self._study_assignments.get(workspace.id),
            workspace_id=workspace.id,
            session_id=session_id,
            occurred_at=datetime.now(UTC),
            started_at=time.monotonic(),
            revision_before=workspace.revision,
            arguments={"paper_id": paper_id},
        )
        try:
            paper = next(item for item in state.papers if item.id == paper_id)
        except StopIteration:
            error = SessionError(
                f"paper '{paper_id}' not in this session",
                status=404,
            )
            self._record_study_failure(operation, error)
            raise error from None
        self._record_study_success(
            operation,
            revision_after=workspace.revision,
        )
        return paper

    @_serialized_session_mutation(StudyAction.PERSPECTIVE_CREATE)
    async def generate_perspective(
        self,
        session_id: str,
        *,
        paper_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> SessionState:
        session = self._require(session_id)
        state = session.state
        if state.notepad is not None and state.notepad.final_snapshot is not None:
            raise SessionError("This study is finished and read-only.", status=409)
        if len(state.perspectives) >= MAX_PERSPECTIVES:
            raise SessionError("A study supports at most six Perspectives.", status=409)
        paper = next((item for item in state.papers if item.id == paper_id), None)
        if paper is None:
            raise SessionError(f"paper '{paper_id}' not found", status=404)
        perspective_name = (name or paper.title).strip()
        if not perspective_name:
            raise SessionError("A Perspective Job requires text.", status=422)
        if len(perspective_name) > 200:
            raise SessionError(
                "A Perspective Job must be at most 200 characters.",
                status=422,
            )
        origin = f"paper:{paper.id}"

        def source_in_matrix() -> bool:
            return any(
                perspective.origin == origin for perspective in state.perspectives
            )

        if source_in_matrix():
            raise SessionError("This paper already has a Perspective.", status=409)

        cluster = next(
            (item for item in state.clusters if paper.id in item.paper_ids),
            None,
        )
        if cluster is None and state.clusters:
            paper_terms = set(
                agents._content_words(f"{paper.title} {paper.abstract or ''}")
            )

            def overlap(candidate: ClusterCard) -> int:
                candidate_papers = [
                    item for item in state.papers if item.id in candidate.paper_ids
                ]
                cluster_terms = set(
                    agents._content_words(
                        " ".join(
                            f"{item.title} {item.abstract or ''}"
                            for item in candidate_papers
                        )
                    )
                )
                return len(paper_terms & cluster_terms)

            cluster = max(state.clusters, key=overlap)
            cluster.paper_ids.append(paper.id)
            state.unassigned_paper_ids = [
                identifier
                for identifier in state.unassigned_paper_ids
                if identifier != paper.id
            ]
        if cluster is None:
            raise SessionError(
                "This paper has no literature cluster.",
                status=409,
            )

        source_papers = {
            item.id: item for item in state.papers if item.id in cluster.paper_ids
        }
        by_facet: dict[Facet, FacetEvidence] = {}
        for evidence in cluster.facets:
            if evidence.facet in by_facet:
                continue
            validated = self._validate_facet_source(evidence, source_papers)
            if validated.text.strip():
                by_facet[evidence.facet] = validated
        fallback = {
            evidence.facet: evidence
            for evidence in agents.fallback_cluster_facets(list(source_papers.values()))
        }
        for facet in FACETS:
            if facet not in by_facet and facet in fallback:
                by_facet[facet] = fallback[facet]
        missing = [facet for facet in FACETS if facet not in by_facet]
        if missing:
            raise SessionError(
                "A Perspective needs Scope, Explanation, Approach, and "
                f"Significance; missing {missing}."
            )

        perspective = Perspective(
            id=session.next_perspective_id(),
            name=perspective_name,
            color=PERSONA_COLORS[len(state.perspectives) % len(PERSONA_COLORS)],
            facets=by_facet,
            sources=sorted(source_papers),
            anchor_paper_id=paper.id,
            related_paper_count=max(len(cluster.paper_ids) - 1, 0),
            cluster_id=cluster.id,
            origin=origin,
        )
        perspective.framing = await agents.derive_framing(
            perspective,
            provider=self._provider_for(session),
        )
        orientation = (description or "").strip()
        perspective.summary = orientation or perspective.framing.framing

        if len(state.perspectives) >= MAX_PERSPECTIVES:
            raise SessionError("A study supports at most six Perspectives.", status=409)
        if source_in_matrix():
            raise SessionError("This paper already has a Perspective.", status=409)
        state.perspectives.append(perspective)
        if state.notepad is not None and state.notepad.final_snapshot is None:
            state.notepad.in_chat.append(perspective.id)
            reconcile_roster(state)
        return self._save_state(state)

    @_serialized_session_mutation(StudyAction.PERSPECTIVE_REMOVE)
    async def remove_perspective(
        self, session_id: str, perspective_id: str
    ) -> SessionState:
        session = self._require(session_id)
        state = session.state
        if not any(item.id == perspective_id for item in state.perspectives):
            raise SessionError("Unknown Perspective.", status=404)
        if state.notepad is not None and state.notepad.final_snapshot is not None:
            raise SessionError("This study is finished and read-only.", status=409)
        state.perspectives = [
            perspective
            for perspective in state.perspectives
            if perspective.id != perspective_id
        ]
        if state.notepad is not None:
            state.notepad.in_chat = [
                item for item in state.notepad.in_chat if item != perspective_id
            ]
            reconcile_roster(state)
        return self._save_state(state)

    # -- baseline discussion -------------------------------------------------
    @staticmethod
    def _canonical_citations(
        state: SessionState,
        citations: list[str],
        allowed_ids: set[str],
    ) -> list[str]:
        by_title = {paper.title.casefold(): paper.id for paper in state.papers}
        out: list[str] = []
        for citation in citations:
            paper_id = (
                citation
                if citation in allowed_ids
                else by_title.get(citation.strip().casefold())
            )
            if paper_id and paper_id in allowed_ids and paper_id not in out:
                out.append(paper_id)
        return out

    @staticmethod
    def _participant_text(state: SessionState, text: str) -> str:
        cleaned = text
        for paper_id in sorted(
            (paper.id for paper in state.papers),
            key=len,
            reverse=True,
        ):
            escaped = re.escape(paper_id)
            cleaned = re.sub(
                rf"\[\s*{escaped}\s*\]",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(
                rf"(?<!\w){escaped}(?!\w)",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
        cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
        cleaned = " ".join(cleaned.split())
        if not cleaned:
            raise SessionError("Agent feedback contained no participant-visible text.")
        return cleaned

    # -- four-part draft review ---------------------------------------------

    def _notepad_call(self, session_id: str, run):
        from agora.focused import notepad as notepad_module

        session = self._require(session_id)
        try:
            run(notepad_module, session.state)
        except notepad_module.NotepadError as error:
            raise SessionError(str(error), status=error.status) from error
        return self._save_state(session.state)

    @_serialized_session_mutation(StudyAction.DISCUSSION_START)
    async def start_notepad(self, session_id: str) -> SessionState:
        """Open the discussion and seed v1 from the input screen."""
        return self._notepad_call(
            session_id, lambda mod, state: mod.start_notepad(state)
        )

    @_serialized_session_mutation(StudyAction.TOPICS_GENERATE)
    async def generate_notepad_topics(self, session_id: str) -> SessionState:
        session = self._require(session_id)
        state = session.state
        notepad = state.notepad
        if notepad is None:
            raise SessionError("The discussion has not started yet.")
        if notepad.final_snapshot is not None:
            raise SessionError("This study is finished and read-only.", status=409)
        if not state.perspectives:
            raise SessionError("Build at least one Perspective first.")
        proposed = {topic.perspective_id for topic in notepad.topics}
        missing = [
            perspective
            for perspective in state.perspectives
            if perspective.id not in proposed
        ]
        if not missing:
            return state
        provider = self._provider_for(session)
        if not state.demo and provider is None:
            raise SessionError("The live model is not configured.", status=503)
        drafts = await agents.generate_discussion_topics(
            problem=state.problem,
            position=state.position,
            perspectives=missing,
            papers=state.papers,
            existing_topics=notepad.topics,
            provider=provider,
        )
        notepad.topics.extend(
            DiscussionTopic(
                **draft.model_dump(),
                id=f"topic-{uuid.uuid4().hex[:12]}",
            )
            for draft in drafts
        )
        return self._save_state(state)

    @_serialized_session_mutation(StudyAction.DOCUMENT_EDIT)
    async def edit_notepad_part(
        self,
        session_id: str,
        *,
        version_id: str,
        part: NotepadPart,
        text: str,
    ) -> SessionState:
        """Researcher edit. Never reviewed."""
        return self._notepad_call(
            session_id,
            lambda mod, state: mod.edit_part(
                state,
                version_id=version_id,
                part=part,
                text=text,
            ),
        )

    @_serialized_session_mutation(StudyAction.VERSION_CREATE)
    async def add_notepad_version(
        self, session_id: str, *, copy_current: bool
    ) -> SessionState:
        return self._notepad_call(
            session_id,
            lambda mod, state: mod.add_version(state, copy_current=copy_current),
        )

    @_serialized_session_mutation(StudyAction.VERSION_SWITCH)
    async def switch_notepad_version(
        self, session_id: str, *, version_id: str
    ) -> SessionState:
        return self._notepad_call(
            session_id,
            lambda mod, state: mod.switch_version(state, version_id=version_id),
        )

    @_serialized_session_mutation(StudyAction.VERSION_DELETE)
    async def delete_notepad_version(
        self, session_id: str, *, version_id: str
    ) -> SessionState:
        return self._notepad_call(
            session_id,
            lambda mod, state: mod.delete_version(state, version_id=version_id),
        )

    @_serialized_session_mutation(StudyAction.CHAT_CLEAR)
    async def clear_notepad_chat(self, session_id: str) -> SessionState:
        return self._notepad_call(session_id, lambda mod, state: mod.clear_chat(state))

    @_serialized_session_mutation(StudyAction.DISCUSSION_RUN)
    async def discuss_notepad(
        self,
        session_id: str,
        *,
        version_id: str,
        turns: int,
    ) -> SessionState:
        from agora.focused import notepad as notepad_module

        session = self._require(session_id)
        state = session.state
        try:
            remaining = notepad_module.remaining_review_turns(
                state,
                version_id=version_id,
            )
        except notepad_module.NotepadError as error:
            raise SessionError(str(error), status=error.status) from error
        if remaining == 0:
            raise SessionError("This draft review is complete.")
        if turns > remaining:
            raise SessionError(
                f"Only {remaining} review turn{'s' if remaining != 1 else ''} "
                f"{'remain' if remaining != 1 else 'remains'}. "
                "Choose that many or fewer."
            )
        for _ in range(turns):
            try:
                plan = notepad_module.plan_review_turn(
                    state,
                    version_id=version_id,
                    turns=turns,
                )
            except notepad_module.NotepadError as error:
                raise SessionError(str(error), status=error.status) from error
            if plan.phase == "feedback":
                statement = await agents.review_draft_element(
                    plan.speaker,
                    plan.part,
                    plan.subject_text,
                    provider=self._provider_for(session),
                )
            else:
                statement = await agents.compare_draft_feedback(
                    plan.speaker,
                    plan.part,
                    plan.subject_text,
                    list(plan.feedback),
                    provider=self._provider_for(session),
                )
            statement = statement.model_copy(
                update={
                    "text": self._participant_text(state, statement.text),
                    "citations": self._canonical_citations(
                        state,
                        statement.citations,
                        set(plan.speaker.sources),
                    ),
                }
            )
            notepad_module.record_review_turn(
                state,
                plan=plan,
                statement=statement,
            )
            version = next(
                item for item in state.notepad.versions if item.id == version_id
            )
            if version.agenda.phase == "complete":
                break
        return self._save_state(state)

    @_serialized_session_mutation(StudyAction.QUESTION_SEND)
    async def ask_notepad(
        self,
        session_id: str,
        *,
        version_id: str,
        message: str,
        topic_id: str | None = None,
    ) -> SessionState:
        from agora.focused import notepad as notepad_module

        session = self._require(session_id)
        state = session.state
        clean_message = " ".join(message.split())
        if not clean_message:
            raise SessionError("A message requires text.", status=422)
        try:
            speakers = notepad_module.next_direct_speakers(state)
        except notepad_module.NotepadError as error:
            raise SessionError(str(error), status=error.status) from error
        notepad = state.notepad
        if notepad is None:
            raise SessionError("The discussion has not started yet.")
        version = next(
            (item for item in notepad.versions if item.id == version_id),
            None,
        )
        if version is None:
            raise SessionError("Unknown Document version.")
        topic = None
        if topic_id is not None:
            topic = next(
                (item for item in notepad.topics if item.id == topic_id),
                None,
            )
            if topic is None:
                raise SessionError("Unknown discussion topic.", status=404)
        version_turns = [
            turn for turn in notepad.turns if turn.version_id == version_id
        ]
        history = [
            f"{turn.author_label}: {turn.text}"
            for turn in version_turns[version.visible_turn_start :]
        ][-8:]
        if topic is not None:
            history.append(
                f"Selected discussion topic: {topic.title}\n"
                f"Question: {topic.question}\n"
                f"Tentative hypothesis to examine, not an established finding: "
                f"{topic.hypothesis}\n"
                f"Evidence motivation: {topic.rationale}"
            )
        replies = await asyncio.gather(
            *[
                agents.reply_to_user(
                    speaker,
                    clean_message,
                    history,
                    provider=self._provider_for(session),
                )
                for speaker in speakers
            ]
        )
        grounded = [
            (
                speaker,
                reply.model_copy(
                    update={
                        "text": self._participant_text(state, reply.text),
                        "citations": self._canonical_citations(
                            state,
                            reply.citations,
                            set(speaker.sources),
                        ),
                    }
                ),
            )
            for speaker, reply in zip(speakers, replies, strict=True)
        ]
        notepad_module.record_direct_exchange(
            state,
            version_id=version_id,
            message=clean_message,
            replies=grounded,
            topic_id=topic_id,
        )
        return self._save_state(state)

    @_serialized_session_mutation(StudyAction.SUMMARY_CREATE)
    async def summarize_notepad(
        self,
        session_id: str,
        *,
        version_id: str,
    ) -> SessionState:
        from agora.focused import notepad as notepad_module

        session = self._require(session_id)
        state = session.state
        notepad = state.notepad
        if notepad is None:
            raise SessionError("The discussion has not started yet.")
        if notepad.final_snapshot is not None:
            raise SessionError("This study is finished and read-only.", status=409)
        version = next(
            (item for item in notepad.versions if item.id == version_id),
            None,
        )
        if version is None:
            raise SessionError("Unknown Document version.")
        version_turns = [
            turn for turn in notepad.turns if turn.version_id == version_id
        ]
        visible = version_turns[version.visible_turn_start :]
        if len([turn for turn in visible if turn.role == "perspective"]) < 2:
            raise SessionError("Not much to summarize yet.")
        statement = await agents.summarize_notepad_turns(
            visible,
            provider=self._provider_for(session),
        )
        statement = statement.model_copy(
            update={
                "text": self._participant_text(state, statement.text),
                "citations": self._canonical_citations(
                    state,
                    statement.citations,
                    {paper.id for paper in state.papers},
                ),
            }
        )
        notepad_module.record_summary(
            state,
            version_id=version_id,
            statement=statement,
        )
        return self._save_state(state)

    @_serialized_session_mutation(StudyAction.REVIEW_RESTART)
    async def restart_notepad_review(
        self,
        session_id: str,
        *,
        version_id: str,
    ) -> SessionState:
        return self._notepad_call(
            session_id,
            lambda mod, state: mod.restart_review(state, version_id=version_id),
        )

    @_serialized_session_mutation(StudyAction.STUDY_FINISH)
    async def finish_notepad_study(self, session_id: str) -> SessionState:
        state = self._require(session_id).state
        if state.notepad is not None and state.notepad.final_snapshot is not None:
            return state
        return self._notepad_call(
            session_id,
            lambda mod, current: mod.finish_study(current),
        )
