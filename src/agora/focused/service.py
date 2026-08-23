"""Focused-panel orchestration for the four-facet iterative study protocol.

Sessions remain backend-authoritative. Kat's evidence, moderator, reflection,
and resolution concepts are adapted behind Benjamin's existing panel workflow
rather than exposing a separate product.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from agora.focused import agents
from agora.focused.demo_data import (
    DEMO_CLUSTERS,
    DEMO_FACETS,
    DEMO_PAPERS,
    DEMO_QUERY_SUGGESTIONS,
    DEMO_RESEARCH_QUESTIONS,
    DEMO_SHARED_GROUND,
)
from agora.focused.models import (
    FACETS,
    PERSONA_COLORS,
    AgentState,
    ClusterCard,
    ClusteringDiagnostics,
    DeliberationRating,
    DeliberationRound,
    DeliberationState,
    ExpPaper,
    Facet,
    FacetDistance,
    FacetEvidence,
    HypothesisConfirmationMode,
    HypothesisDev,
    HypothesisPart,
    HypothesisVersion,
    InvestigationSummary,
    Perspective,
    QuestionReach,
    QuestionStatus,
    RecommendedQuestion,
    RoundMetrics,
    SessionState,
    Turn,
    TurnKind,
    WorkspaceState,
    WorkspaceView,
    utcnow,
)

if TYPE_CHECKING:
    from agora.focused.persistence import WorkspacePersistence
    from agora.focused.provider import FocusedProvider

from agora.focused.persistence import PersistenceConflict

logger = logging.getLogger(__name__)
MAX_SUGGESTED_QUERIES = 5


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


def _serialized_session_mutation(method):
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
                try:
                    return await method(self, session_id, *args, **kwargs)
                except WorkspaceConflict:
                    raise
                except BaseException:
                    self._restore_workspace(snapshot)
                    raise

    return wrapped


def _serialized_parent_mutation(method):
    @wraps(method)
    async def wrapped(
        self: FocusedPanelService,
        workspace_id: str,
        parent_investigation_id: str,
        *args,
        **kwargs,
    ):
        parent = self._require(parent_investigation_id)
        if parent.state.workspace_id != workspace_id:
            raise SessionError(
                f"investigation '{parent_investigation_id}' is not in this workspace",
                status=404,
            )
        async with self._workspace_lock(workspace_id):
            parent = self._require(parent_investigation_id)
            async with parent.lock:
                snapshot = self._snapshot_workspace(workspace_id)
                try:
                    return await method(
                        self,
                        workspace_id,
                        parent_investigation_id,
                        *args,
                        **kwargs,
                    )
                except WorkspaceConflict:
                    raise
                except BaseException:
                    self._restore_workspace(snapshot)
                    raise

    return wrapped


class _Session:
    def __init__(self, state: SessionState) -> None:
        self.state = state
        self._turn_seq = max(
            (
                turn.id
                for deliberation in state.deliberations
                for turn in [
                    *deliberation.chat,
                    *(
                        turn
                        for round_state in deliberation.rounds
                        for turn in round_state.turns
                    ),
                ]
            ),
            default=0,
        )
        self._persp_seq = max(
            (
                int(perspective.id.split("-", 2)[1])
                for perspective in state.perspectives
                if perspective.id.startswith("persp-")
                and perspective.id.split("-", 2)[1].isdigit()
            ),
            default=0,
        )
        self._agent_seq = max((agent.iid for agent in state.agents), default=0)
        self._delib_seq = max(
            (
                int(deliberation.id.removeprefix("delib-"))
                for deliberation in state.deliberations
                if deliberation.id.removeprefix("delib-").isdigit()
            ),
            default=0,
        )
        self.lock = asyncio.Lock()

    def snapshot(self) -> tuple[SessionState, int, int, int, int]:
        return (
            self.state.model_copy(deep=True),
            self._turn_seq,
            self._persp_seq,
            self._agent_seq,
            self._delib_seq,
        )

    def restore(
        self,
        snapshot: tuple[SessionState, int, int, int, int],
    ) -> None:
        (
            self.state,
            self._turn_seq,
            self._persp_seq,
            self._agent_seq,
            self._delib_seq,
        ) = snapshot

    def next_turn_id(self) -> int:
        self._turn_seq += 1
        return self._turn_seq

    def next_perspective_id(self) -> str:
        self._persp_seq += 1
        return f"persp-{self._persp_seq}"

    def next_agent_iid(self) -> int:
        self._agent_seq += 1
        return self._agent_seq

    def next_deliberation_id(self) -> str:
        self._delib_seq += 1
        return f"delib-{self._delib_seq}"


class FocusedPanelService:
    def __init__(
        self,
        *,
        provider: FocusedProvider | None = None,
        embedder: Callable[[list[str]], Awaitable[np.ndarray]] | None = None,
        embedding_model: str = "unconfigured",
        s2: Any | None = None,
        persistence: WorkspacePersistence | None = None,
    ) -> None:
        self._sessions: dict[str, _Session] = {}
        self._workspaces: dict[str, WorkspaceState] = {}
        self._workspace_locks: dict[str, asyncio.Lock] = {}
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

    # -- plumbing ----------------------------------------------------------

    def _require(self, session_id: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionError(f"session '{session_id}' not found", status=404)
        return session

    def _workspace_lock(self, workspace_id: str) -> asyncio.Lock:
        return self._workspace_locks.setdefault(workspace_id, asyncio.Lock())

    def _require_workspace(self, workspace_id: str) -> WorkspaceState:
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise SessionError(f"workspace '{workspace_id}' not found", status=404)
        return workspace

    def _workspace_for(self, state: SessionState) -> WorkspaceState:
        return self._require_workspace(state.workspace_id)

    def _snapshot_workspace(
        self,
        workspace_id: str,
    ) -> tuple[
        WorkspaceState,
        dict[str, tuple[SessionState, int, int, int, int]],
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
            dict[str, tuple[SessionState, int, int, int, int]],
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
        if workspace is None:
            self._workspaces.pop(workspace_id, None)
            self._workspace_locks.pop(workspace_id, None)
            self._durable_snapshots.pop(workspace_id, None)
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
        if self._persistence is None:
            try:
                self._validated_workspace_state(workspace)
            except Exception:
                self._restore_durable(workspace_id)
                raise
            self._remember_durable(workspace_id)
            return
        expected_revision = workspace.revision
        workspace.revision += 1
        try:
            validated_workspace, investigations = self._validated_workspace_state(
                workspace
            )
            self._persistence.save(
                validated_workspace,
                investigations,
                expected_revision=expected_revision,
            )
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

    def _save_view(self, workspace_id: str) -> WorkspaceView:
        self._persist_workspace(workspace_id)
        return self.workspace_view(workspace_id)

    @staticmethod
    def _investigation_summary(state: SessionState) -> InvestigationSummary:
        completed_rounds = sum(
            round_state.completed
            for deliberation in state.deliberations
            for round_state in deliberation.rounds
        )
        open_questions = sum(
            question.status == "open"
            for deliberation in state.deliberations
            for question in deliberation.recommended_questions
        )
        return InvestigationSummary(
            id=state.id,
            parent_investigation_id=state.parent_investigation_id,
            origin_question_id=state.origin_question_id,
            origin_question=state.origin_question,
            created_at=state.created_at,
            searched=state.searched,
            paper_count=len(state.papers),
            perspective_count=len(state.perspectives),
            completed_rounds=completed_rounds,
            open_question_count=open_questions,
            applied_hypothesis_version_id=state.applied_hypothesis_version_id,
        )

    def workspace_view(self, workspace_id: str) -> WorkspaceView:
        workspace = self._require_workspace(workspace_id)
        investigations = [
            self._investigation_summary(self._require(investigation_id).state)
            for investigation_id in workspace.investigation_ids
        ]
        active = self._require(workspace.active_investigation_id).state
        return WorkspaceView(
            workspace=workspace,
            investigations=investigations,
            active=active,
        )

    def activate_investigation(
        self,
        workspace_id: str,
        investigation_id: str,
    ) -> WorkspaceView:
        workspace = self._require_workspace(workspace_id)
        self._ensure_workspace_idle(workspace)
        if investigation_id not in workspace.investigation_ids:
            raise SessionError(
                f"investigation '{investigation_id}' is not in this workspace",
                status=404,
            )
        workspace.active_investigation_id = investigation_id
        return self._save_view(workspace_id)

    @staticmethod
    def _recommended_question(
        state: SessionState,
        question_id: str,
    ) -> tuple[DeliberationState, RecommendedQuestion]:
        for deliberation in state.deliberations:
            for question in deliberation.recommended_questions:
                if question.id == question_id:
                    return deliberation, question
        raise SessionError(f"open question '{question_id}' not found", status=404)

    @staticmethod
    def _hypothesis_version(
        workspace: WorkspaceState,
        version_id: str,
    ) -> HypothesisVersion:
        version = next(
            (item for item in workspace.hypothesis_versions if item.id == version_id),
            None,
        )
        if version is None:
            raise SessionError(
                f"hypothesis version '{version_id}' not found",
                status=404,
            )
        return version

    def _record_hypothesis(
        self,
        state: SessionState,
        deliberation: DeliberationState | None,
        hypothesis: HypothesisDev,
        *,
        source_kind: Literal["applied", "edit", "merge"] = "applied",
        parent_ids: list[str] | None = None,
        step_sources: dict[HypothesisPart, str] | None = None,
        source_round: int | None = None,
    ) -> HypothesisVersion:
        workspace = self._workspace_for(state)
        current_version = (
            self._hypothesis_version(
                workspace,
                state.applied_hypothesis_version_id,
            )
            if state.applied_hypothesis_version_id
            else None
        )
        parents = (
            list(parent_ids)
            if parent_ids is not None
            else ([current_version.id] if current_version is not None else [])
        )
        version_id = f"H{len(workspace.hypothesis_versions) + 1}"
        if step_sources is None:
            step_sources = {}
            for part in (
                "problem",
                "previous_work",
                "reasoning",
                "hypothesis",
            ):
                if current_version is not None and getattr(
                    current_version.steps, part
                ) == getattr(hypothesis, part):
                    step_sources[part] = current_version.step_sources.get(
                        part,
                        current_version.id,
                    )
                else:
                    step_sources[part] = version_id
        version = HypothesisVersion(
            id=version_id,
            workspace_id=workspace.id,
            investigation_id=state.id,
            parent_ids=list(dict.fromkeys(parents)),
            steps=hypothesis.model_copy(deep=True),
            step_sources=step_sources,
            source_kind=source_kind,
            source_deliberation_id=deliberation.id if deliberation else None,
            source_round=(
                source_round
                if source_round is not None
                else (
                    deliberation.rounds[-1].n
                    if deliberation is not None and deliberation.rounds
                    else None
                )
            ),
        )
        workspace.hypothesis_versions.append(version)
        state.applied_hypothesis = hypothesis.model_copy(deep=True)
        state.applied_hypothesis_version_id = version.id
        if deliberation is not None:
            deliberation.hypothesis = hypothesis.model_copy(deep=True)
            deliberation.applied_hypothesis = hypothesis.model_copy(deep=True)
            deliberation.hypothesis_confirmed = True
            deliberation.working_hypothesis_source_kind = None
            deliberation.working_hypothesis_source_round = None
        if workspace.promoted_hypothesis_version_id is None:
            workspace.promoted_hypothesis_version_id = version.id
        return version

    def _address_contributing_questions(
        self,
        workspace: WorkspaceState,
        version: HypothesisVersion,
    ) -> None:
        versions = {item.id: item for item in workspace.hypothesis_versions}
        pending = [version.id]
        visited: set[str] = set()
        while pending:
            version_id = pending.pop()
            if version_id in visited:
                continue
            visited.add(version_id)
            contribution = versions[version_id]
            investigation = self._require(contribution.investigation_id).state
            if (
                investigation.parent_investigation_id
                and investigation.origin_question_id
            ):
                parent = self._require(investigation.parent_investigation_id).state
                _, question = self._recommended_question(
                    parent,
                    investigation.origin_question_id,
                )
                question.status = "addressed"
            pending.extend(contribution.parent_ids)

    def _demo(self, session: _Session) -> bool:
        return session.state.demo or self._provider is None

    def _provider_for(self, session: _Session) -> FocusedProvider | None:
        return None if session.state.demo else self._provider

    def get(self, session_id: str) -> SessionState:
        return self._require(session_id).state

    # -- stage ① perspective construction ----------------------------------

    def create_workspace(
        self,
        *,
        problem: str,
        research_questions: list[str],
        demo: bool,
    ) -> WorkspaceView:
        clean_problem = problem.strip()
        if len(clean_problem) < 3:
            raise SessionError("Problem must be at least three characters.")
        workspace_id = uuid.uuid4().hex
        investigation_id = uuid.uuid4().hex
        state = SessionState(
            id=investigation_id,
            workspace_id=workspace_id,
            problem=clean_problem,
            research_questions=[q.strip() for q in research_questions if q.strip()],
            demo=demo or self._provider is None,
        )
        workspace = WorkspaceState(
            id=workspace_id,
            problem=clean_problem,
            root_investigation_id=investigation_id,
            active_investigation_id=investigation_id,
            investigation_ids=[investigation_id],
        )
        self._sessions[state.id] = _Session(state)
        self._workspaces[workspace.id] = workspace
        self._workspace_locks[workspace.id] = asyncio.Lock()
        try:
            if self._persistence is not None:
                validated_workspace, investigations = self._validated_workspace_state(
                    workspace
                )
                self._persistence.create(validated_workspace, investigations)
            self._remember_durable(workspace.id)
        except Exception:
            self._sessions.pop(state.id, None)
            self._workspaces.pop(workspace.id, None)
            self._workspace_locks.pop(workspace.id, None)
            self._durable_snapshots.pop(workspace.id, None)
            raise
        return self.workspace_view(workspace.id)

    @_serialized_parent_mutation
    async def create_child_investigation(
        self,
        workspace_id: str,
        parent_investigation_id: str,
        question_id: str,
    ) -> WorkspaceView:
        workspace = self._require_workspace(workspace_id)
        if parent_investigation_id not in workspace.investigation_ids:
            raise SessionError(
                f"investigation '{parent_investigation_id}' is not in this workspace",
                status=404,
            )
        parent = self._require(parent_investigation_id)
        _, question = self._recommended_question(parent.state, question_id)
        if question.status != "open":
            raise SessionError(
                "Only an open question can start a child Investigation.",
                status=409,
            )

        child_id = uuid.uuid4().hex
        child_state = SessionState(
            id=child_id,
            workspace_id=workspace.id,
            problem=workspace.problem,
            research_questions=[question.question],
            parent_investigation_id=parent.state.id,
            origin_question_id=question.id,
            origin_question=question.question,
            demo=parent.state.demo,
            applied_hypothesis=(
                parent.state.applied_hypothesis.model_copy(deep=True)
                if parent.state.applied_hypothesis is not None
                else None
            ),
            applied_hypothesis_version_id=parent.state.applied_hypothesis_version_id,
        )
        self._sessions[child_id] = _Session(child_state)
        workspace.investigation_ids.append(child_id)
        workspace.active_investigation_id = child_id
        question.status = "investigating"
        question.child_investigation_id = child_id

        return self._save_view(workspace.id)

    def set_question_status(
        self,
        workspace_id: str,
        investigation_id: str,
        question_id: str,
        status: QuestionStatus,
    ) -> WorkspaceView:
        workspace = self._require_workspace(workspace_id)
        self._ensure_workspace_idle(workspace)
        if investigation_id not in workspace.investigation_ids:
            raise SessionError(
                f"investigation '{investigation_id}' is not in this workspace",
                status=404,
            )
        _, question = self._recommended_question(
            self._require(investigation_id).state,
            question_id,
        )
        if status == question.status:
            return self.workspace_view(workspace.id)
        allowed: dict[QuestionStatus, set[QuestionStatus]] = {
            "open": {"archived"},
            "investigating": {"addressed", "archived"},
            "addressed": {"investigating", "archived"},
            "archived": (
                {"open"}
                if question.child_investigation_id is None
                else {"investigating", "addressed"}
            ),
        }
        if status not in allowed[question.status]:
            raise SessionError(
                f"Question cannot move from {question.status} to {status}.",
                status=409,
            )
        question.status = status
        return self._save_view(workspace.id)

    def promote_hypothesis(
        self,
        workspace_id: str,
        version_id: str,
    ) -> WorkspaceView:
        workspace = self._require_workspace(workspace_id)
        self._ensure_workspace_idle(workspace)
        version = self._hypothesis_version(workspace, version_id)
        if version.archived:
            raise SessionError("An archived hypothesis cannot be promoted.", status=409)
        investigation = self._require(version.investigation_id).state
        if investigation.applied_hypothesis_version_id != version.id:
            raise SessionError(
                "Only an Investigation's current checkpoint can be promoted.",
                status=409,
            )
        if workspace.promoted_hypothesis_version_id == version.id:
            return self.workspace_view(workspace.id)
        workspace.promoted_hypothesis_version_id = version.id
        workspace.active_investigation_id = version.investigation_id
        self._address_contributing_questions(workspace, version)
        return self._save_view(workspace.id)

    def merge_hypotheses(
        self,
        workspace_id: str,
        *,
        target_investigation_id: str,
        source_version_id: str,
        parts_from_source: list[HypothesisPart],
    ) -> WorkspaceView:
        workspace = self._require_workspace(workspace_id)
        self._ensure_workspace_idle(workspace)
        if target_investigation_id not in workspace.investigation_ids:
            raise SessionError(
                f"investigation '{target_investigation_id}' is not in this workspace",
                status=404,
            )
        target_state = self._require(target_investigation_id).state
        deliberation = (
            target_state.deliberations[-1] if target_state.deliberations else None
        )
        if (
            deliberation is not None
            and deliberation.hypothesis is not None
            and not deliberation.hypothesis_confirmed
        ):
            raise SessionError(
                "Apply or edit the pending hypothesis before merging into this "
                "Investigation.",
                status=409,
            )
        if target_state.applied_hypothesis_version_id is None:
            raise SessionError(
                "The target Investigation has no applied hypothesis to merge into.",
                status=409,
            )
        target_version = self._hypothesis_version(
            workspace,
            target_state.applied_hypothesis_version_id,
        )
        source_version = self._hypothesis_version(workspace, source_version_id)
        if source_version.archived:
            raise SessionError("An archived hypothesis cannot be merged.", status=409)
        selected = list(dict.fromkeys(parts_from_source))
        if not selected:
            raise SessionError("Select at least one hypothesis step to merge.")
        if source_version.id == target_version.id:
            raise SessionError("Choose a different hypothesis branch to merge.")

        merged = target_version.steps.model_dump()
        source = source_version.steps.model_dump()
        for part in selected:
            merged[part] = source[part]
        hypothesis = HypothesisDev(**merged)
        if hypothesis == target_version.steps:
            return self.workspace_view(workspace.id)
        step_sources = {
            part: target_version.step_sources.get(part, target_version.id)
            for part in (
                "problem",
                "previous_work",
                "reasoning",
                "hypothesis",
            )
        }
        for part in selected:
            step_sources[part] = source_version.step_sources.get(
                part,
                source_version.id,
            )
        promoted_target = workspace.promoted_hypothesis_version_id == target_version.id
        version = self._record_hypothesis(
            target_state,
            deliberation,
            hypothesis,
            source_kind="merge",
            parent_ids=[target_version.id, source_version.id],
            step_sources=step_sources,
        )
        if promoted_target:
            workspace.promoted_hypothesis_version_id = version.id
            self._address_contributing_questions(workspace, version)
        workspace.active_investigation_id = target_state.id
        return self._save_view(workspace.id)

    def archive_hypothesis(
        self,
        workspace_id: str,
        version_id: str,
    ) -> WorkspaceView:
        workspace = self._require_workspace(workspace_id)
        self._ensure_workspace_idle(workspace)
        version = self._hypothesis_version(workspace, version_id)
        if version.archived:
            return self.workspace_view(workspace.id)
        if workspace.promoted_hypothesis_version_id == version.id:
            raise SessionError(
                "Promote another hypothesis before archiving this one.",
                status=409,
            )
        if any(
            self._require(investigation_id).state.applied_hypothesis_version_id
            == version.id
            for investigation_id in workspace.investigation_ids
        ):
            raise SessionError(
                "An Investigation's current checkpoint cannot be archived.",
                status=409,
            )
        version.archived = True
        return self._save_view(workspace.id)

    def restore_hypothesis(
        self,
        workspace_id: str,
        version_id: str,
    ) -> WorkspaceView:
        workspace = self._require_workspace(workspace_id)
        self._ensure_workspace_idle(workspace)
        version = self._hypothesis_version(workspace, version_id)
        if not version.archived:
            return self.workspace_view(workspace.id)
        version.archived = False
        return self._save_view(workspace.id)

    def delete_workspace(self, workspace_id: str) -> None:
        workspace = self._require_workspace(workspace_id)
        self._ensure_workspace_idle(workspace)
        if self._persistence is not None:
            try:
                self._persistence.delete(
                    workspace.id,
                    expected_revision=workspace.revision,
                )
            except PersistenceConflict as error:
                self._reload_workspace(workspace_id)
                raise WorkspaceConflict() from error
        for investigation_id in workspace.investigation_ids:
            self._sessions.pop(investigation_id, None)
        self._workspaces.pop(workspace.id, None)
        self._workspace_locks.pop(workspace.id, None)
        self._durable_snapshots.pop(workspace.id, None)

    def update_brief(
        self,
        session_id: str,
        *,
        problem: str,
        research_questions: list[str],
    ) -> SessionState:
        session = self._require(session_id)
        state = session.state
        workspace = self._workspace_for(state)
        self._ensure_workspace_idle(workspace)
        if state.searched:
            raise SessionError(
                "Start a new investigation to change the brief after retrieving papers.",
                status=409,
            )
        clean_problem = problem.strip()
        if len(clean_problem) < 3:
            raise SessionError("Problem must be at least three characters.")
        if (
            state.id != workspace.root_investigation_id
            and clean_problem != workspace.problem
        ):
            raise SessionError(
                "The research problem is shared by the workspace. "
                "Edit the child Investigation's research question instead.",
                status=409,
            )
        if state.id == workspace.root_investigation_id:
            workspace.problem = clean_problem
        state.problem = workspace.problem
        state.research_questions = [
            question.strip() for question in research_questions if question.strip()
        ]
        state.suggested_queries = []
        state.searched_queries = []
        state.question_reach = []
        return self._save_state(state)

    @staticmethod
    def _ensure_searchable(state: SessionState) -> None:
        if state.searched:
            raise SessionError(
                "This Investigation already has literature. Start a child "
                "Investigation to search new papers without replacing it."
            )

    @_serialized_session_mutation
    async def suggest_queries(self, session_id: str) -> SessionState:
        session = self._require(session_id)
        state = session.state
        self._ensure_searchable(state)
        reaches: list[QuestionReach] = []
        if self._demo(session):
            paired_questions = state.research_questions == DEMO_RESEARCH_QUESTIONS
            suggestions = []
            for suggestion in DEMO_QUERY_SUGGESTIONS:
                if (
                    not paired_questions
                    or suggestion.question_index is None
                    or suggestion.question_index >= len(state.research_questions)
                ):
                    suggestions.append(
                        suggestion.model_copy(
                            deep=True,
                            update={"kind": "problem", "question_index": None},
                        )
                    )
                else:
                    suggestions.append(suggestion.model_copy(deep=True))
            demo_terms: dict[int, list[str]] = {}
            for suggestion in suggestions:
                if (
                    suggestion.kind == "question"
                    and suggestion.question_index is not None
                ):
                    demo_terms.setdefault(suggestion.question_index, []).append(
                        suggestion.query
                    )
            reaches = [
                QuestionReach(
                    question=question,
                    candidates=[question, *demo_terms.get(index, [])],
                )
                for index, question in enumerate(state.research_questions)
            ]
        else:
            problem_suggestions = [
                suggestion.model_copy(
                    update={"kind": "problem", "question_index": None, "round": 1}
                )
                for suggestion in await agents.suggest_queries(
                    state.problem,
                    state.research_questions,
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

    async def _live_retrieve(self, queries: list[str]) -> list[ExpPaper]:
        papers: dict[str, ExpPaper] = {}
        for query in queries:
            try:
                results = await self._s2.search(query, limit=8)
            except Exception as exc:
                logger.warning("focused paper search failed for %r: %s", query, exc)
                if " returned 429:" in str(exc):
                    raise SessionError(
                        "Paper search is temporarily rate-limited. "
                        "Wait a minute and try again.",
                        status=503,
                    ) from exc
                continue
            for r in results:
                if r.id in papers:
                    continue
                abstract_sentences = agents.split_sentences(r.abstract)
                papers[r.id] = ExpPaper(
                    id=r.id,
                    title=r.title,
                    abstract=r.abstract,
                    abstract_sentences=abstract_sentences,
                    year=r.year,
                    venue=r.venue,
                    authors=[a.name for a in r.authors[:4]],
                    source_query=query,
                    tldr=r.tldr,
                    open_access_pdf_url=r.open_access_pdf_url,
                    specter_v2=r.specter_v2,
                )
        return list(papers.values())[:30]

    async def _retrieve_queries(
        self, session: _Session, queries: list[str]
    ) -> list[ExpPaper]:
        clean = [query.strip() for query in queries if query.strip()]
        if not clean:
            return []
        if self._demo(session):
            return self._demo_retrieve(clean)
        return await self._live_retrieve(clean)

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
            cluster_sizes=[len(g) for g in groups],
            silhouette=silhouette,
        )

    def _demo_cluster(self, papers: list[ExpPaper]) -> list[list[ExpPaper]]:
        groups: list[list[ExpPaper]] = [[] for _ in DEMO_CLUSTERS]
        for paper in papers:
            text = f"{paper.title} {paper.abstract or ''}".lower()
            best, best_score = 0, 0
            for i, seed in enumerate(DEMO_CLUSTERS):
                score = sum(1 for t in seed["terms"] if t in text)
                if score > best_score:
                    best, best_score = i, score
            groups[best].append(paper)
        return [g for g in groups if g]

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
        sentences = paper.abstract_sentences
        if evidence.sentence_index is not None and 0 <= evidence.sentence_index < len(
            sentences
        ):
            return evidence.model_copy(
                update={"sentence": sentences[evidence.sentence_index]}
            )
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

    @_serialized_session_mutation
    async def run_search(self, session_id: str, queries: list[str]) -> SessionState:
        session = self._require(session_id)
        state = session.state
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
        paper_by_id = {
            paper.id: paper
            for paper in await self._retrieve_queries(session, angle_queries)
        }

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
            reach.queries_r1 = round1
            hits = {
                paper.id: paper
                for paper in await self._retrieve_queries(session, round1)
            }
            assessment = await agents.assess_question_papers(
                reach.question,
                reach.candidates,
                list(hits.values()),
                provider=self._provider_for(session),
                want_round2=False,
            )
            reach.vocabulary = assessment.vocabulary
            selected_evidence = {item.paper_id: item for item in assessment.selected}
            reach.retrieved = len(hits)
            reach.selected = list(selected_evidence.values())
            reach.reached = bool(reach.selected)
            for paper_id in selected_evidence:
                paper = hits.get(paper_id)
                if paper is not None:
                    paper_by_id.setdefault(paper_id, paper)
        state.question_reach = reaches
        papers = list(paper_by_id.values())

        if self._demo(session):
            groups = self._demo_cluster(papers) if papers else []
            method = "demo_seeds"
        else:
            groups = self._embedding_clusters(papers)
            method = "specter_kmeans"
            if len(groups) < 2:
                groups = (
                    self._kmeans_clusters(papers, k=6)
                    if len(papers) >= 4
                    else ([papers] if papers else [])
                )
                method = "tfidf_kmeans" if len(papers) >= 4 else "single_group"

        state.clustering = self._clustering_diagnostics(method, papers, groups)

        state.papers = papers
        state.searched = True
        state.searched_queries = list(dict.fromkeys(queries))

        clusters: list[ClusterCard] = []
        ordered_groups = [self._centroid_order(group) for group in groups]
        namings = (
            []
            if self._demo(session)
            else await agents.name_clusters(
                ordered_groups,
                provider=self._provider_for(session),
            )
        )
        for idx, group in enumerate(ordered_groups):
            naming = namings[idx] if idx < len(namings) else None
            demo_facets = (
                [DEMO_FACETS.get(paper.id, []) for paper in group]
                if self._demo(session)
                else None
            )
            facets = await agents.extract_cluster_facets(
                group,
                provider=self._provider_for(session),
                demo_facets=demo_facets,
            )
            # Provenance is enforced at the service boundary: an extracted
            # facet survives only when it maps to this cluster's abstracts.
            by_id = {paper.id: paper for paper in group}
            grounded: list[FacetEvidence] = []
            seen_facets: set[Facet] = set()
            for evidence in facets:
                if evidence.facet in seen_facets:
                    continue
                seen_facets.add(evidence.facet)
                grounded.append(self._validate_facet_source(evidence, by_id))
            grounded.extend(
                FacetEvidence(facet=facet, text="")
                for facet in FACETS
                if facet not in seen_facets
            )
            clusters.append(
                ClusterCard(
                    id=f"cluster-{idx + 1}",
                    name=naming.name
                    if naming
                    else (DEMO_CLUSTERS[idx % len(DEMO_CLUSTERS)]["name"]),
                    blurb=naming.blurb
                    if naming
                    else (DEMO_CLUSTERS[idx % len(DEMO_CLUSTERS)]["blurb"]),
                    facets=grounded,
                    paper_ids=[p.id for p in group],
                )
            )
        state.clusters = clusters
        return self._save_state(state)

    async def paper_detail(self, session_id: str, paper_id: str) -> ExpPaper:
        state = self._require(session_id).state
        for paper in state.papers:
            if paper.id == paper_id:
                return paper
        raise SessionError(f"paper '{paper_id}' not in this session", status=404)

    def _ensure_perspective_agent(
        self,
        session: _Session,
        perspective: Perspective,
    ) -> AgentState:
        state = session.state
        existing = next(
            (agent for agent in state.agents if agent.perspective_id == perspective.id),
            None,
        )
        if existing is None:
            existing = AgentState(
                iid=session.next_agent_iid(),
                perspective_id=perspective.id,
                label=perspective.name,
                facets={
                    facet: evidence.model_copy(deep=True)
                    for facet, evidence in perspective.facets.items()
                },
            )
            state.agents.append(existing)
        for deliberation in state.deliberations:
            if (
                deliberation.completed_at is None
                and existing.iid not in deliberation.agent_iids
            ):
                deliberation.agent_iids.append(existing.iid)
        return existing

    @_serialized_session_mutation
    async def generate_perspective(
        self,
        session_id: str,
        *,
        cluster_id: str,
        facets: list[FacetEvidence] | None = None,
        name: str | None = None,
    ) -> SessionState:
        session = self._require(session_id)
        state = session.state
        if any(
            deliberation.completed_at is not None
            for deliberation in state.deliberations
        ):
            raise SessionError(
                "This deliberation has ended. Start from a Research Problem "
                "before adding more Perspectives."
            )
        cluster = next((item for item in state.clusters if item.id == cluster_id), None)
        if cluster is None:
            raise SessionError(f"cluster '{cluster_id}' not found", status=404)

        def cluster_in_matrix() -> bool:
            return any(
                perspective.origin == cluster.id and not perspective.evolved
                for perspective in state.perspectives
            )

        if cluster_in_matrix():
            raise SessionError(
                "This cluster already has a perspective in the matrix.",
                status=409,
            )

        final = facets if facets is not None else cluster.facets
        cluster_papers = {
            paper.id: paper for paper in state.papers if paper.id in cluster.paper_ids
        }
        by_facet: dict[Facet, FacetEvidence] = {}
        for evidence in final:
            if evidence.facet in by_facet:
                continue
            validated = self._validate_facet_source(evidence, cluster_papers)
            if not validated.text.strip():
                continue
            by_facet[evidence.facet] = validated
        missing = [facet for facet in FACETS if facet not in by_facet]
        if missing:
            raise SessionError(
                "A Perspective needs Scope, Explanation, Approach, and "
                f"Significance; missing {missing}."
            )

        color = PERSONA_COLORS[len(state.perspectives) % len(PERSONA_COLORS)]
        perspective = Perspective(
            id=session.next_perspective_id(),
            name=name or cluster.name,
            color=color,
            facets=by_facet,
            sources=sorted(
                {
                    evidence.paper_id
                    for evidence in by_facet.values()
                    if evidence.paper_id
                }
            ),
            origin=cluster.id,
        )
        perspective.framing = await agents.derive_framing(
            perspective, provider=self._provider_for(session)
        )
        perspective.summary = perspective.framing.framing

        # Authoritative re-check with NO await between check and append:
        # two racing requests can both pass the pre-check above, but only
        # one survives this synchronous window.
        if cluster_in_matrix():
            raise SessionError(
                "This cluster already has a perspective in the matrix.",
                status=409,
            )
        state.perspectives.append(perspective)
        self._ensure_perspective_agent(session, perspective)
        return self._save_state(state)

    @_serialized_session_mutation
    async def remove_perspective(
        self, session_id: str, perspective_id: str
    ) -> SessionState:
        session = self._require(session_id)
        state = session.state
        orphaned = {a.iid for a in state.agents if a.perspective_id == perspective_id}
        if any(
            deliberation.rounds
            and any(iid in deliberation.agent_iids for iid in orphaned)
            for deliberation in state.deliberations
        ):
            raise SessionError(
                "A perspective cannot be removed after its panel starts."
            )
        state.perspectives = [p for p in state.perspectives if p.id != perspective_id]
        # Cascade before round 1: agents built on the deleted perspective go
        # too, and every not-yet-started panel loses their wiring.
        state.agents = [a for a in state.agents if a.perspective_id != perspective_id]
        for d in state.deliberations:
            if orphaned:
                d.agent_iids = [i for i in d.agent_iids if i not in orphaned]
        return self._save_state(state)

    # -- stage ② deliberation ----------------------------------------------

    def _perspective(self, state: SessionState, perspective_id: str) -> Perspective:
        perspective = next(
            (item for item in state.perspectives if item.id == perspective_id),
            None,
        )
        if perspective is None:
            raise SessionError(
                f"perspective '{perspective_id}' not found",
                status=404,
            )
        return perspective

    def _agent_profile(self, state: SessionState, agent: AgentState) -> Perspective:
        base = self._perspective(state, agent.perspective_id)
        sources = sorted(
            {
                *base.sources,
                *(
                    evidence.paper_id
                    for evidence in agent.facets.values()
                    if evidence.paper_id
                ),
            }
        )
        return base.model_copy(
            deep=True,
            update={
                "facets": {
                    facet: evidence.model_copy(deep=True)
                    for facet, evidence in agent.facets.items()
                },
                "sources": sources,
                "evolved": agent.facet_version > 1,
            },
        )

    @_serialized_session_mutation
    async def develop_agent_hypothesis(self, session_id: str, iid: int) -> SessionState:
        session = self._require(session_id)
        state = session.state
        if any(
            deliberation.completed_at is not None
            for deliberation in state.deliberations
        ):
            raise SessionError("This deliberation has ended.")
        agent = next((item for item in state.agents if item.iid == iid), None)
        if agent is None:
            raise SessionError(f"agent {iid} not found", status=404)
        agent.hypothesis = await agents.develop_hypothesis(
            self._agent_profile(state, agent),
            provider=self._provider_for(session),
        )
        return self._save_state(state)

    def _deliberation(
        self, state: SessionState, deliberation_id: str
    ) -> DeliberationState:
        deliberation = next(
            (item for item in state.deliberations if item.id == deliberation_id),
            None,
        )
        if deliberation is None:
            raise SessionError(
                f"deliberation '{deliberation_id}' not found",
                status=404,
            )
        return deliberation

    @staticmethod
    def _same_hypothesis(
        proposed: HypothesisDev,
        current: HypothesisDev,
    ) -> bool:
        def normalized(value: str) -> str:
            text = value.strip()
            return "" if text == "Not established yet." else text

        parts = ("problem", "previous_work", "reasoning", "hypothesis")
        return all(
            normalized(getattr(proposed, part)) == normalized(getattr(current, part))
            for part in parts
        )

    @staticmethod
    def _require_open_deliberation(deliberation: DeliberationState) -> None:
        if deliberation.completed_at is not None:
            raise SessionError("This deliberation has ended.")

    @_serialized_session_mutation
    async def create_deliberation(self, session_id: str) -> SessionState:
        session = self._require(session_id)
        state = session.state
        for perspective in state.perspectives:
            self._ensure_perspective_agent(session, perspective)
        if not state.deliberations:
            inherited = (
                state.applied_hypothesis.model_copy(deep=True)
                if state.applied_hypothesis is not None
                else None
            )
            state.deliberations.append(
                DeliberationState(
                    id=session.next_deliberation_id(),
                    agent_iids=[agent.iid for agent in state.agents],
                    hypothesis=inherited,
                    applied_hypothesis=(
                        inherited.model_copy(deep=True)
                        if inherited is not None
                        else None
                    ),
                    hypothesis_confirmed=inherited is not None,
                )
            )
        return self._save_state(state)

    def _agent_view(
        self, state: SessionState, iid: int
    ) -> tuple[AgentState, Perspective]:
        agent = next((item for item in state.agents if item.iid == iid), None)
        if agent is None:
            raise SessionError(f"agent {iid} not on the canvas", status=404)
        return agent, self._agent_profile(state, agent)

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
    def _facet_snapshot(
        state: SessionState,
        agent_iids: list[int],
    ) -> dict[int, dict[Facet, str]]:
        selected = {
            agent.iid: agent for agent in state.agents if agent.iid in agent_iids
        }
        return {
            iid: {
                facet: selected[iid].facets[facet].text
                for facet in FACETS
                if facet in selected[iid].facets
            }
            for iid in agent_iids
            if iid in selected
        }

    async def _embed_metric_texts(
        self,
        session: _Session,
        texts: list[str],
    ) -> tuple[np.ndarray | None, str]:
        """Embed facet text semantically or mark the study metric unavailable."""
        embed_batch = self._embedder
        model = self._embedding_model
        if embed_batch is None:
            provider = self._provider
            embed_batch = getattr(provider, "embed_batch", None)
            model = getattr(provider, "embedding_model", model)
        if not callable(embed_batch):
            return None, "unavailable:no-semantic-embedder"
        try:
            matrix = np.asarray(
                await embed_batch(texts),
                dtype=np.float32,
            )
        except Exception:  # noqa: BLE001 — deliberation survives metric failure
            return None, "unavailable:embedding-failed"
        if matrix.ndim != 2 or matrix.shape[0] != len(texts):
            return None, "unavailable:invalid-embedding-batch"
        return matrix, f"semantic:{model}"

    async def _round_metrics(
        self,
        session: _Session,
        before: dict[int, dict[Facet, str]],
        after: dict[int, dict[Facet, str]],
    ) -> RoundMetrics:
        records: list[tuple[str, Facet, int, str]] = []
        for phase, snapshot in (("before", before), ("after", after)):
            for facet in FACETS:
                for iid, values in snapshot.items():
                    text = values.get(facet, "").strip()
                    if text:
                        records.append((phase, facet, iid, text))
        if not records:
            return RoundMetrics(method="none")

        matrix, method = await self._embed_metric_texts(
            session,
            [record[3] for record in records],
        )
        if matrix is None:
            return RoundMetrics(method=method)
        lookup = {
            (phase, facet, iid): index
            for index, (phase, facet, iid, _) in enumerate(records)
        }

        from sklearn.metrics.pairwise import cosine_distances

        def distances_for(
            phase: str,
            snapshot: dict[int, dict[Facet, str]],
        ) -> list[FacetDistance]:
            results: list[FacetDistance] = []
            for facet in FACETS:
                indices = [
                    lookup[(phase, facet, iid)]
                    for iid in snapshot
                    if (phase, facet, iid) in lookup
                ]
                if len(indices) < 2:
                    results.append(
                        FacetDistance(
                            facet=facet,
                            distance=0.0,
                            participant_count=len(indices),
                        )
                    )
                    continue
                pairwise = cosine_distances(matrix[indices])
                upper = pairwise[np.triu_indices(len(indices), k=1)]
                distance = float(np.clip(upper.mean(), 0.0, 2.0))
                results.append(
                    FacetDistance(
                        facet=facet,
                        distance=distance,
                        participant_count=len(indices),
                    )
                )
            return results

        before_distances = distances_for("before", before)
        after_distances = distances_for("after", after)

        def overall(values: list[FacetDistance]) -> float | None:
            valid = [value.distance for value in values if value.participant_count >= 2]
            return float(np.mean(valid)) if valid else None

        overall_before = overall(before_distances)
        overall_after = overall(after_distances)
        if overall_before is None or overall_after is None:
            delta = None
            direction = "insufficient"
        else:
            delta = float(np.clip(overall_after - overall_before, -2.0, 2.0))
            if delta < -0.001:
                direction = "convergent"
            elif delta > 0.001:
                direction = "divergent"
            else:
                direction = "stable"
        return RoundMetrics(
            method=method,
            before=before_distances,
            after=after_distances,
            overall_before=overall_before,
            overall_after=overall_after,
            delta=delta,
            direction=direction,
        )

    @_serialized_session_mutation
    async def run_round(
        self,
        session_id: str,
        deliberation_id: str,
        *,
        lead_iid: int,
        facets: list[Facet],
    ) -> SessionState:
        """Run one user-directed round over one or two selected facets."""
        session = self._require(session_id)
        state = session.state
        deliberation = self._deliberation(state, deliberation_id)
        self._require_open_deliberation(deliberation)
        selected = list(dict.fromkeys(facets))
        if len(selected) != len(facets) or not 1 <= len(selected) <= 2:
            raise SessionError("Select one or two different areas for this round.")
        if any(facet not in FACETS for facet in selected):
            raise SessionError(
                "Choose from Scope, Explanation, Approach, and Significance."
            )
        if len(deliberation.agent_iids) < 2:
            raise SessionError("Wire in at least two agents first.")
        if lead_iid not in deliberation.agent_iids:
            raise SessionError("The lead must be wired into this deliberation.")
        if (
            deliberation.hypothesis is not None
            and not deliberation.hypothesis_confirmed
        ):
            raise SessionError(
                "Apply or edit the pending shared-ground update before "
                "starting another round."
            )

        if deliberation.rounds and not deliberation.rounds[-1].completed:
            deliberation.rounds.pop()

        participant_iids = list(deliberation.agent_iids)
        round_state = DeliberationRound(
            n=len(deliberation.rounds) + 1,
            lead_iid=lead_iid,
            participant_iids=participant_iids,
            facets=selected,
        )
        deliberation.rounds.append(round_state)
        before = self._facet_snapshot(state, participant_iids)

        lead_agent, lead_profile = self._agent_view(state, lead_iid)
        other_profiles = [
            self._agent_view(state, iid)[1]
            for iid in participant_iids
            if iid != lead_iid
        ]

        async def speak(turn: Turn) -> None:
            round_state.turns.append(turn)

        for facet in selected:
            statement = await agents.open_statement(
                lead_profile,
                facet,
                provider=self._provider_for(session),
                round_turns=[turn.text for turn in round_state.turns],
            )
            lead_turn = Turn(
                id=session.next_turn_id(),
                agent_iid=lead_iid,
                agent_label=lead_agent.label,
                role="lead",
                kind=TurnKind.open,
                facet=facet,
                text=statement.text,
                citations=self._canonical_citations(
                    state,
                    statement.citations,
                    set(lead_profile.sources),
                ),
            )
            await speak(lead_turn)

            answers: list[Turn] = []
            for iid in participant_iids:
                if iid == lead_iid:
                    continue
                agent, profile = self._agent_view(state, iid)
                response = await agents.answer_statement(
                    profile,
                    facet,
                    lead_agent.label,
                    statement.text,
                    provider=self._provider_for(session),
                )
                turn = Turn(
                    id=session.next_turn_id(),
                    agent_iid=iid,
                    agent_label=agent.label,
                    role="other",
                    kind=TurnKind.answer,
                    facet=facet,
                    text=response.text,
                    citations=self._canonical_citations(
                        state,
                        response.citations,
                        set(profile.sources),
                    ),
                )
                answers.append(turn)
                await speak(turn)

            if not any(turn.citations for turn in [lead_turn, *answers]):
                support_result = await agents.retrieve_support(
                    lead_turn.text,
                    lead_profile,
                    provider=self._provider_for(session),
                    s2=None if self._demo(session) else self._s2,
                    corpus=state.papers,
                )
                if support_result is not None:
                    support, support_paper = support_result
                    if not any(paper.id == support_paper.id for paper in state.papers):
                        state.papers.append(support_paper)
                    await speak(
                        Turn(
                            id=session.next_turn_id(),
                            agent_iid=lead_iid,
                            agent_label=lead_agent.label,
                            role="lead",
                            kind=TurnKind.support,
                            facet=facet,
                            text=support.text,
                            citations=self._canonical_citations(
                                state,
                                support.citations,
                                {paper.id for paper in state.papers},
                            ),
                        )
                    )

            facet_turns = [turn for turn in round_state.turns if turn.facet == facet]
            verdict = await agents.judge_facet(
                lead_profile,
                other_profiles,
                facet,
                [turn.text for turn in facet_turns],
                provider=self._provider_for(session),
                shared_ground=(
                    DEMO_SHARED_GROUND[facet]
                    if state.clustering is not None
                    and state.clustering.method == "demo_seeds"
                    else None
                ),
            )
            positions: dict[str, str] = {}
            evidence: dict[str, list[str]] = {}
            for turn in facet_turns:
                if turn.kind != TurnKind.support:
                    positions[turn.agent_label] = turn.text
                if turn.citations:
                    evidence[turn.agent_label] = list(
                        dict.fromkeys(
                            [
                                *evidence.get(turn.agent_label, []),
                                *turn.citations,
                            ]
                        )
                    )
            known = set(positions)
            verdict = verdict.model_copy(
                update={
                    "facet": facet,
                    "supporting": [
                        name for name in verdict.supporting if name in known
                    ],
                    "contested_by": [
                        name for name in verdict.contested_by if name in known
                    ],
                    "positions": positions,
                    "evidence": evidence,
                }
            )
            round_state.verdicts.append(verdict)

        resolution = await agents.summarize_round(
            selected,
            round_state.verdicts,
            [turn.text for turn in round_state.turns],
            provider=self._provider_for(session),
        )
        known_papers = {paper.id for paper in state.papers}
        known_names = {
            self._agent_view(state, iid)[0].label for iid in participant_iids
        }
        for points in (
            resolution.consensus_points,
            resolution.disagreement_points,
            resolution.unsettled_points,
        ):
            for point in points:
                point.citations = [
                    citation for citation in point.citations if citation in known_papers
                ]
                point.perspective_names = [
                    name for name in point.perspective_names if name in known_names
                ]
        round_state.resolution = resolution

        reflected: list[tuple[AgentState, Any, dict[Facet, FacetEvidence]]] = []
        for iid in participant_iids:
            agent, profile = self._agent_view(state, iid)
            reflection, updated = await agents.reflect_on_round(
                iid,
                profile,
                selected,
                resolution,
                provider=self._provider_for(session),
            )
            reflected.append((agent, reflection, updated))
        for agent, reflection, updated in reflected:
            agent.facets = updated
            if reflection.decision == "revised":
                agent.facet_version += 1
            round_state.reflections.append(reflection)

        after = self._facet_snapshot(state, participant_iids)
        round_state.metrics = await self._round_metrics(
            session,
            before,
            after,
        )

        _, revised = self._agent_view(state, lead_iid)
        revised = revised.model_copy(
            deep=True,
            update={
                "id": f"{revised.id}-round-{round_state.n}",
                "name": f"{revised.name} · round {round_state.n}",
                "evolved": True,
                "origin": deliberation.id,
            },
        )
        revised.framing = await agents.derive_framing(
            revised,
            provider=self._provider_for(session),
        )
        revised.summary = resolution.summary
        deliberation.revised_perspective = revised

        if resolution.consensus_points:
            deliberation.no_agreement = False
            proposed_hypothesis = await agents.develop_hypothesis_from_consensus(
                resolution,
                current=deliberation.applied_hypothesis,
                provider=self._provider_for(session),
            )
            current_hypothesis = deliberation.applied_hypothesis
            if current_hypothesis is not None and self._same_hypothesis(
                proposed_hypothesis,
                current_hypothesis,
            ):
                deliberation.hypothesis = current_hypothesis.model_copy(deep=True)
                deliberation.hypothesis_confirmed = True
            else:
                deliberation.hypothesis = proposed_hypothesis
                deliberation.hypothesis_confirmed = False
        else:
            deliberation.no_agreement = True

        questions = await agents.recommend_questions(
            resolution,
            revised,
            provider=self._provider_for(session),
        )
        unresolved = {
            " ".join(item.question.casefold().split())
            for item in deliberation.recommended_questions
            if item.status in {"open", "investigating"}
        }
        new_questions: list[RecommendedQuestion] = []
        for index, question in enumerate(questions, start=1):
            identity = " ".join(question.question.casefold().split())
            if identity in unresolved:
                continue
            unresolved.add(identity)
            new_questions.append(
                question.model_copy(
                    update={
                        "id": f"{deliberation.id}-r{round_state.n}-q{index}",
                        "source_round": round_state.n,
                    }
                )
            )
        deliberation.recommended_questions.extend(new_questions)
        deliberation.questions_generated = True
        round_state.completed = True

        return self._save_state(state)

    @_serialized_session_mutation
    async def complete_deliberation(
        self,
        session_id: str,
        deliberation_id: str,
    ) -> SessionState:
        session = self._require(session_id)
        state = session.state
        deliberation = self._deliberation(state, deliberation_id)
        if deliberation.completed_at is not None:
            return state
        if not deliberation.rounds or not deliberation.rounds[-1].completed:
            raise SessionError(
                "Complete a focused round before ending the deliberation."
            )
        if (
            not deliberation.hypothesis_confirmed
            or deliberation.applied_hypothesis is None
        ):
            raise SessionError(
                "Apply the pending hypothesis update before ending the deliberation."
            )
        if (
            state.applied_hypothesis_version_id is None
            or state.applied_hypothesis != deliberation.applied_hypothesis
        ):
            raise SessionError(
                "Save the current hypothesis before ending the deliberation."
            )
        deliberation.completed_at = utcnow()
        deliberation.final_hypothesis_version_id = state.applied_hypothesis_version_id
        return self._save_state(state)

    @_serialized_session_mutation
    async def rate_deliberation(
        self,
        session_id: str,
        deliberation_id: str,
        rating: DeliberationRating,
    ) -> SessionState:
        session = self._require(session_id)
        deliberation = self._deliberation(session.state, deliberation_id)
        if deliberation.completed_at is None:
            raise SessionError("End the deliberation before scoring it.")
        deliberation.rating = DeliberationRating(
            divergent=rating.divergent,
            convergent=rating.convergent,
            note=rating.note.strip(),
        )
        return self._save_state(session.state)

    @_serialized_session_mutation
    async def confirm_deliberation_hypothesis(
        self,
        session_id: str,
        deliberation_id: str,
        hypothesis: HypothesisDev,
        mode: HypothesisConfirmationMode = "apply_pending",
    ) -> SessionState:
        session = self._require(session_id)
        deliberation = self._deliberation(session.state, deliberation_id)
        self._require_open_deliberation(deliberation)
        if not deliberation.rounds or not deliberation.rounds[-1].completed:
            raise SessionError("Complete a focused round first.")
        if deliberation.hypothesis is None:
            raise SessionError(
                "This round did not establish enough common ground for a hypothesis."
            )
        parts = (
            hypothesis.problem.strip(),
            hypothesis.previous_work.strip(),
            hypothesis.reasoning.strip(),
            hypothesis.hypothesis.strip(),
        )
        if any(not part for part in parts):
            raise SessionError("Complete all four parts of the hypothesis.")
        applied = HypothesisDev(
            problem=parts[0],
            previous_work=parts[1],
            reasoning=parts[2],
            hypothesis=parts[3],
        )
        if mode == "apply_pending":
            if deliberation.hypothesis_confirmed:
                if applied == deliberation.applied_hypothesis:
                    return session.state
                raise SessionError(
                    "There is no pending hypothesis update to apply.",
                    status=409,
                )
            source_kind: Literal["applied", "edit"] = "applied"
        else:
            if (
                not deliberation.hypothesis_confirmed
                or deliberation.applied_hypothesis is None
            ):
                raise SessionError(
                    "Apply or discard the pending update before editing the "
                    "working hypothesis.",
                    status=409,
                )
            if applied == deliberation.applied_hypothesis:
                return session.state
            source_kind = "edit"

        previous = deliberation.applied_hypothesis
        deliberation.hypothesis = applied.model_copy(deep=True)
        deliberation.applied_hypothesis = applied.model_copy(deep=True)
        deliberation.hypothesis_confirmed = True
        if previous != applied:
            deliberation.working_hypothesis_source_kind = source_kind
            deliberation.working_hypothesis_source_round = deliberation.rounds[-1].n
        return self._save_state(session.state)

    @_serialized_session_mutation
    async def save_deliberation_hypothesis(
        self,
        session_id: str,
        deliberation_id: str,
    ) -> SessionState:
        session = self._require(session_id)
        deliberation = self._deliberation(session.state, deliberation_id)
        self._require_open_deliberation(deliberation)
        working = deliberation.applied_hypothesis
        if not deliberation.hypothesis_confirmed or working is None:
            raise SessionError("Apply the working hypothesis before saving it.")
        if (
            session.state.applied_hypothesis_version_id is not None
            and session.state.applied_hypothesis == working
        ):
            return session.state

        workspace = self._workspace_for(session.state)
        current_version_id = session.state.applied_hypothesis_version_id
        advances_promoted_branch = (
            current_version_id is not None
            and workspace.promoted_hypothesis_version_id == current_version_id
            and self._hypothesis_version(
                workspace,
                current_version_id,
            ).investigation_id
            == session.state.id
        )
        version = self._record_hypothesis(
            session.state,
            deliberation,
            working,
            source_kind=deliberation.working_hypothesis_source_kind or "applied",
            source_round=deliberation.working_hypothesis_source_round,
        )
        if advances_promoted_branch:
            workspace.promoted_hypothesis_version_id = version.id
        return self._save_state(session.state)

    @_serialized_session_mutation
    async def chat(
        self,
        session_id: str,
        deliberation_id: str,
        *,
        message: str,
        target_iid: int | None = None,
        proactivity: str = "med",
    ) -> SessionState:
        session = self._require(session_id)
        state = session.state
        deliberation = self._deliberation(state, deliberation_id)
        self._require_open_deliberation(deliberation)
        speakers = [
            iid
            for iid in deliberation.agent_iids
            if target_iid is None or iid == target_iid
        ]
        if not speakers:
            raise SessionError("No agents wired into this deliberation.")
        limit = {"low": 1, "med": 2}.get(proactivity, len(speakers))
        speakers = speakers[:limit]
        active_facets = (
            deliberation.rounds[-1].facets if deliberation.rounds else list(FACETS)
        )

        deliberation.chat.append(
            Turn(
                id=session.next_turn_id(),
                role="user",
                kind=TurnKind.user,
                text=message.strip(),
            )
        )

        history = [turn.text for turn in deliberation.chat]
        for iid in speakers:
            agent, perspective = self._agent_view(state, iid)
            reply = await agents.reply_to_user(
                perspective,
                message,
                history,
                active_facets=active_facets,
                provider=self._provider_for(session),
            )
            turn = Turn(
                id=session.next_turn_id(),
                agent_iid=iid,
                agent_label=agent.label,
                role="other",
                kind=TurnKind.answer,
                text=reply.text,
                citations=self._canonical_citations(
                    state,
                    reply.citations,
                    set(perspective.sources),
                ),
            )
            deliberation.chat.append(turn)

        return self._save_state(state)

    # -- export ---------------------------------------------------------------

    def export_workspace(self, workspace_id: str) -> dict[str, Any]:
        workspace = self._require_workspace(workspace_id)
        self._ensure_workspace_idle(workspace)
        view = self.workspace_view(workspace_id)
        return {
            "schema": "agora-hypothesis-workspace",
            "schema_version": 4,
            "exported_at": utcnow().isoformat(),
            "workspace": view.workspace.model_dump(mode="json"),
            "investigations": [
                self._require(investigation_id).state.model_dump(mode="json")
                for investigation_id in view.workspace.investigation_ids
            ],
        }
