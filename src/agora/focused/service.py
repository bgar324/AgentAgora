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
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from agora.focused import agents
from agora.focused.clustering import density_partition
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
    DeliberationCompletion,
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
    RetrievalTier,
    RoundMetrics,
    RoundResolution,
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
PAPERS_PER_QUERY = 20
MAX_RETRIEVED_PAPERS = 200
TARGET_CLUSTER_PAPERS = 30
MAX_CLUSTERS = 6
CLUSTER_REPRESENTATIVE_PAPERS = 5

MIN_CLUSTERING_CORPUS = 90
MIN_THREE_CLUSTER_PAPERS = 15
DEMO_RETRIEVAL_DELAY_SECONDS = 1.05
MAX_SEARCH_PROGRESS_EVENTS = 192
SearchProgressKind = Literal[
    "query_started",
    "query_completed",
    "query_failed",
    "retrieval_completed",
    "clustering_started",
    "clustering_completed",
    "round_stage",
    "round_turn",
]


@dataclass(frozen=True)
class QuestionRetrieval:
    answering: dict[str, ExpPaper]
    candidates: dict[str, ExpPaper]
    succeeded: bool
    expansion_queries: list[str]


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
        for deliberation in state.deliberations:
            FocusedPanelService._materialize_completion_history(deliberation)
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
                    *(
                        turn
                        for completion in deliberation.completion_history
                        for turn in [
                            *completion.chat,
                            *(
                                turn
                                for round_state in completion.rounds
                                for turn in round_state.turns
                            ),
                        ]
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
        retain_search_embeddings: bool = False,
    ) -> None:
        self._sessions: dict[str, _Session] = {}
        self._workspaces: dict[str, WorkspaceState] = {}
        self._workspace_locks: dict[str, asyncio.Lock] = {}
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
        ) + sum(
            round_state.completed
            for deliberation in state.deliberations
            for completion in deliberation.completion_history
            for round_state in completion.rounds
        )
        open_questions = sum(
            question.status == "open"
            for deliberation in state.deliberations
            for question in deliberation.recommended_questions
        ) + sum(
            question.status == "open"
            for deliberation in state.deliberations
            for completion in deliberation.completion_history
            for question in completion.recommended_questions
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
            for completion in deliberation.completion_history:
                for question in completion.recommended_questions:
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
            if parent_ids is None and state.applied_hypothesis_version_id
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
            self._forget_search_progress(state.id)
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

    @_serialized_parent_mutation
    async def integrate_child_investigation(
        self,
        workspace_id: str,
        parent_investigation_id: str,
        child_investigation_id: str,
        invited_perspective_ids: list[str] | None = None,
    ) -> WorkspaceView:
        workspace = self._require_workspace(workspace_id)
        parent = self._require(parent_investigation_id)
        child = self._require(child_investigation_id)
        child_state = child.state
        if child_state.parent_investigation_id != parent.state.id:
            raise SessionError(
                "The research branch does not belong to this Investigation.",
                status=409,
            )
        if child_state.integrated_into_parent_at is not None:
            raise SessionError(
                "This research branch was already continued.",
                status=409,
            )
        if not child_state.perspectives:
            raise SessionError("Add at least one Perspective before continuing.")
        if not parent.state.deliberations:
            raise SessionError("The parent Investigation has no deliberation.")
        deliberation = parent.state.deliberations[0]
        if (
            deliberation.completed_at is None
            or deliberation.final_hypothesis_version_id is None
        ):
            raise SessionError(
                "Return to the parent panel and end its current deliberation "
                "before adding this research branch."
            )
        agent_by_iid = {agent.iid: agent for agent in parent.state.agents}
        invited = (
            list(invited_perspective_ids)
            if invited_perspective_ids is not None
            else [
                agent_by_iid[iid].perspective_id
                for iid in deliberation.agent_iids
                if iid in agent_by_iid
            ]
        )
        if child_state.origin_question_id is None:
            raise SessionError("The research branch has no source question.")
        _, source_question = self._recommended_question(
            parent.state,
            child_state.origin_question_id,
        )
        if source_question.child_investigation_id != child_state.id:
            raise SessionError(
                "The source question points to another Investigation.",
                status=409,
            )

        paper_ids = {paper.id for paper in parent.state.papers}
        paper_by_content = {
            (paper.title.casefold(), paper.abstract or ""): paper.id
            for paper in parent.state.papers
        }
        paper_map: dict[str, str] = {}
        for paper in child_state.papers:
            fingerprint = (paper.title.casefold(), paper.abstract or "")
            existing_id = paper_by_content.get(fingerprint)
            if existing_id is not None:
                paper_map[paper.id] = existing_id
                continue
            imported_id = paper.id
            if imported_id in paper_ids:
                imported_id = f"{child_state.id[:8]}-{paper.id}"
            paper_ids.add(imported_id)
            paper_by_content[fingerprint] = imported_id
            paper_map[paper.id] = imported_id
            parent.state.papers.append(
                paper.model_copy(deep=True, update={"id": imported_id})
            )

        cluster_ids = {cluster.id for cluster in parent.state.clusters}
        cluster_map: dict[str, str] = {}
        for cluster in child_state.clusters:
            imported_id = f"{child_state.id[:8]}-{cluster.id}"
            suffix = 2
            while imported_id in cluster_ids:
                imported_id = f"{child_state.id[:8]}-{cluster.id}-{suffix}"
                suffix += 1
            cluster_ids.add(imported_id)
            cluster_map[cluster.id] = imported_id
            parent.state.clusters.append(
                cluster.model_copy(
                    deep=True,
                    update={
                        "id": imported_id,
                        "paper_ids": [
                            paper_map.get(paper_id, paper_id)
                            for paper_id in cluster.paper_ids
                        ],
                        "representative_paper_ids": [
                            paper_map.get(paper_id, paper_id)
                            for paper_id in cluster.representative_paper_ids
                        ],
                        "facets": [
                            evidence.model_copy(
                                deep=True,
                                update={
                                    "paper_id": paper_map.get(
                                        evidence.paper_id,
                                        evidence.paper_id,
                                    )
                                },
                            )
                            for evidence in cluster.facets
                        ],
                    },
                )
            )

        imported_perspective_ids: list[str] = []
        for perspective in child_state.perspectives:
            imported = perspective.model_copy(
                deep=True,
                update={
                    "id": parent.next_perspective_id(),
                    "color": PERSONA_COLORS[
                        len(parent.state.perspectives) % len(PERSONA_COLORS)
                    ],
                    "origin": cluster_map.get(
                        perspective.origin,
                        f"{child_state.id[:8]}-{perspective.origin}",
                    ),
                    "source_question_id": child_state.origin_question_id,
                    "panel_cycle": 0,
                    "sources": [
                        paper_map.get(paper_id, paper_id)
                        for paper_id in perspective.sources
                    ],
                    "facets": {
                        facet: evidence.model_copy(
                            deep=True,
                            update={
                                "paper_id": paper_map.get(
                                    evidence.paper_id,
                                    evidence.paper_id,
                                )
                            },
                        )
                        for facet, evidence in perspective.facets.items()
                    },
                },
            )
            parent.state.perspectives.append(imported)
            imported_perspective_ids.append(imported.id)

        source_question.status = "addressed"
        self._restart_deliberation(
            parent,
            [*imported_perspective_ids, *invited],
        )
        for perspective in parent.state.perspectives:
            if perspective.id in imported_perspective_ids:
                perspective.panel_cycle = len(deliberation.completion_history)

        parent.state.searched_queries = list(
            dict.fromkeys(
                [*parent.state.searched_queries, *child_state.searched_queries]
            )
        )
        child_state.integrated_into_parent_at = utcnow()
        workspace.active_investigation_id = parent.state.id
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
            self._forget_search_progress(investigation_id)
        self._workspaces.pop(workspace.id, None)
        self._workspace_locks.pop(workspace.id, None)
        self._durable_snapshots.pop(workspace.id, None)

    @staticmethod
    def _retryable_empty_search(state: SessionState) -> bool:
        return (
            state.searched
            and not state.papers
            and not state.clusters
            and not state.perspectives
            and not state.deliberations
        )

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
        if state.searched and not self._retryable_empty_search(state):
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
        state.searched = False
        state.suggested_queries = []
        state.searched_queries = []
        state.question_reach = []
        return self._save_state(state)

    def _ensure_searchable(self, state: SessionState) -> None:
        if state.searched and not self._retryable_empty_search(state):
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
                await asyncio.sleep(DEMO_RETRIEVAL_DELAY_SECONDS)
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

    @_serialized_session_mutation
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
        if (
            len(papers) < MIN_CLUSTERING_CORPUS
            and not self._demo(session)
            and not rate_limited
        ):
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
        if self._demo(session):
            await asyncio.sleep(DEMO_RETRIEVAL_DELAY_SECONDS)

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
        if self._demo(session):
            await asyncio.sleep(DEMO_RETRIEVAL_DELAY_SECONDS)

        partition_representatives: list[list[ExpPaper]] | None = None
        unassigned_papers: list[ExpPaper] = []
        if self._demo(session):
            groups = self._demo_cluster(papers) if papers else []
            if len(groups) < requested_clusters:
                groups = self._balanced_fallback_clusters(
                    papers,
                    requested_clusters,
                )
                method = "balanced_fallback"
            else:
                method = "demo_seeds"
        else:
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

        state.clustering = self._clustering_diagnostics(
            method,
            papers,
            groups,
            requested_clusters=requested_clusters,
        )

        state.papers = papers
        state.unassigned_paper_ids = [paper.id for paper in unassigned_papers]
        state.searched = True
        state.searched_queries = list(dict.fromkeys([*queries, *automatic_queries]))

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
            representatives = (
                partition_representatives[idx]
                if partition_representatives is not None
                and idx < len(partition_representatives)
                else group[:CLUSTER_REPRESENTATIVE_PAPERS]
            )
            facets = await agents.extract_cluster_facets(
                representatives,
                provider=self._provider_for(session),
                demo_facets=demo_facets,
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
                    name=naming.name
                    if naming
                    else (DEMO_CLUSTERS[idx % len(DEMO_CLUSTERS)]["name"]),
                    blurb=naming.blurb
                    if naming
                    else (DEMO_CLUSTERS[idx % len(DEMO_CLUSTERS)]["blurb"]),
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
        state = self._require(session_id).state
        for paper in state.papers:
            if paper.id == paper_id:
                return paper
        raise SessionError(f"paper '{paper_id}' not in this session", status=404)

    def _new_panel_agent(
        self,
        session: _Session,
        perspective: Perspective,
    ) -> AgentState:
        agent = AgentState(
            iid=session.next_agent_iid(),
            perspective_id=perspective.id,
            label=perspective.name,
            facets={
                facet: evidence.model_copy(deep=True)
                for facet, evidence in perspective.facets.items()
            },
        )
        session.state.agents.append(agent)
        return agent

    @staticmethod
    def _recorded_question_ids(deliberation: DeliberationState) -> set[str]:
        return {
            question_id
            for completion in deliberation.completion_history
            for question_id in completion.question_ids
        }

    @staticmethod
    def _materialize_completion_history(
        deliberation: DeliberationState,
    ) -> tuple[int, int]:
        has_legacy_cumulative_history = any(
            completion.round_count > 0 and not completion.rounds
            for completion in deliberation.completion_history
        )
        if not has_legacy_cumulative_history:
            return 0, 0
        rounds = list(deliberation.rounds)
        chat = list(deliberation.chat)
        previous_round_count = 0
        previous_chat_count = 0
        by_question_id = {
            question.id: question for question in deliberation.recommended_questions
        }
        for completion in deliberation.completion_history:
            cumulative_round_count = completion.round_count
            if not completion.rounds:
                completion.rounds = [
                    item.model_copy(deep=True)
                    for item in rounds[previous_round_count:cumulative_round_count]
                ]
                completion.round_count = len(completion.rounds)
            if not completion.question_ids:
                completion.question_ids = [
                    question.id
                    for question in deliberation.recommended_questions
                    if question.source_round is not None
                    and previous_round_count
                    < question.source_round
                    <= cumulative_round_count
                ]
            if not completion.recommended_questions:
                completion.recommended_questions = [
                    by_question_id[question_id].model_copy(deep=True)
                    for question_id in completion.question_ids
                    if question_id in by_question_id
                ]
            if completion.chat_count and not completion.chat:
                completion.chat = [
                    item.model_copy(deep=True)
                    for item in chat[
                        previous_chat_count : previous_chat_count
                        + completion.chat_count
                    ]
                ]
            previous_round_count = cumulative_round_count
            previous_chat_count += completion.chat_count
        archived_question_ids = {
            question_id
            for completion in deliberation.completion_history
            for question_id in completion.question_ids
        }
        deliberation.rounds = rounds[previous_round_count:]
        deliberation.recommended_questions = [
            question
            for question in deliberation.recommended_questions
            if question.id not in archived_question_ids
        ]
        deliberation.chat = chat[previous_chat_count:]
        return 0, 0

    def _archive_current_deliberation(
        self,
        deliberation: DeliberationState,
        applied_hypothesis_version_id: str | None,
    ) -> None:
        previous_round_count, previous_chat_count = (
            self._materialize_completion_history(deliberation)
        )
        recorded_questions = self._recorded_question_ids(deliberation)
        current_rounds = deliberation.rounds[previous_round_count:]
        current_chat = deliberation.chat[previous_chat_count:]
        current_questions = [
            question
            for question in deliberation.recommended_questions
            if question.id not in recorded_questions
        ]
        has_activity = (
            bool(current_rounds)
            or bool(current_chat)
            or bool(current_questions)
            or deliberation.hypothesis is not None
            or deliberation.completed_at is not None
        )
        if not has_activity:
            return
        reason: Literal["completed", "restarted"] = (
            "completed" if deliberation.completed_at is not None else "restarted"
        )
        deliberation.completion_history.append(
            DeliberationCompletion(
                archived_at=utcnow(),
                reason=reason,
                completed_at=deliberation.completed_at,
                final_hypothesis_version_id=deliberation.final_hypothesis_version_id,
                round_count=len(current_rounds),
                chat_count=len(current_chat),
                agent_iids=list(deliberation.agent_iids),
                question_ids=[question.id for question in current_questions],
                lead_perspective_id=deliberation.lead_perspective_id,
                baseline_hypothesis=(
                    deliberation.baseline_hypothesis.model_copy(deep=True)
                    if deliberation.baseline_hypothesis is not None
                    else None
                ),
                selected_question_ids=list(deliberation.selected_question_ids),
                rating=(
                    deliberation.rating.model_copy(deep=True)
                    if deliberation.rating is not None
                    else None
                ),
                rounds=[item.model_copy(deep=True) for item in current_rounds],
                recommended_questions=[
                    item.model_copy(deep=True) for item in current_questions
                ],
                chat=[item.model_copy(deep=True) for item in current_chat],
                revised_perspective=(
                    deliberation.revised_perspective.model_copy(deep=True)
                    if deliberation.revised_perspective is not None
                    else None
                ),
                hypothesis=(
                    deliberation.hypothesis.model_copy(deep=True)
                    if deliberation.hypothesis is not None
                    else None
                ),
                applied_hypothesis_version_id=applied_hypothesis_version_id,
                applied_hypothesis=(
                    deliberation.applied_hypothesis.model_copy(deep=True)
                    if deliberation.applied_hypothesis is not None
                    else None
                ),
                hypothesis_confirmed=deliberation.hypothesis_confirmed,
                no_agreement=deliberation.no_agreement,
            )
        )

    def _restart_deliberation(
        self,
        session: _Session,
        perspective_ids: list[str],
    ) -> DeliberationState:
        state = session.state
        if not state.deliberations:
            raise SessionError("This Investigation has no deliberation.")
        roster = list(dict.fromkeys(perspective_ids))
        if len(roster) < 2:
            raise SessionError("A panel needs at least two Perspectives.")
        perspectives = {
            perspective.id: perspective for perspective in state.perspectives
        }
        unknown = [
            perspective_id
            for perspective_id in roster
            if perspective_id not in perspectives
        ]
        if unknown:
            raise SessionError(f"unknown Perspectives: {unknown}", status=404)
        deliberation = state.deliberations[0]
        self._archive_current_deliberation(
            deliberation,
            state.applied_hypothesis_version_id,
        )
        deliberation.rounds = []
        deliberation.recommended_questions = []
        deliberation.chat = []
        deliberation.lead_perspective_id = None
        deliberation.baseline_hypothesis = None
        deliberation.selected_question_ids = []
        deliberation.agent_iids = [
            self._new_panel_agent(session, perspectives[perspective_id]).iid
            for perspective_id in roster
        ]
        deliberation.revised_perspective = None
        deliberation.hypothesis = None
        deliberation.applied_hypothesis = None
        deliberation.hypothesis_confirmed = False
        deliberation.working_hypothesis_source_kind = None
        deliberation.working_hypothesis_source_round = None
        deliberation.no_agreement = False
        deliberation.questions_generated = False
        deliberation.completed_at = None
        deliberation.final_hypothesis_version_id = None
        deliberation.rating = None
        return deliberation

    def _ensure_perspective_agent(
        self,
        session: _Session,
        perspective: Perspective,
    ) -> AgentState:
        state = session.state
        existing = next(
            (
                agent
                for agent in reversed(state.agents)
                if agent.perspective_id == perspective.id
            ),
            None,
        )
        if existing is None:
            existing = self._new_panel_agent(session, perspective)
        agent_by_iid = {agent.iid: agent for agent in state.agents}
        for deliberation in state.deliberations:
            has_perspective = any(
                iid in agent_by_iid
                and agent_by_iid[iid].perspective_id == perspective.id
                for iid in deliberation.agent_iids
            )
            if deliberation.completed_at is None and not has_perspective:
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
        invited_perspective_ids: list[str] | None = None,
    ) -> SessionState:
        session = self._require(session_id)
        state = session.state
        if state.integrated_into_parent_at is not None:
            raise SessionError(
                "This research branch was already continued.",
                status=409,
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
            panel_cycle=0,
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
        if state.deliberations:
            current = state.deliberations[0]
            agent_by_iid = {agent.iid: agent for agent in state.agents}
            invited = (
                list(invited_perspective_ids)
                if invited_perspective_ids is not None
                else [
                    agent_by_iid[iid].perspective_id
                    for iid in current.agent_iids
                    if iid in agent_by_iid
                ]
            )
            self._restart_deliberation(
                session,
                [perspective.id, *invited],
            )
            perspective.panel_cycle = len(current.completion_history)
        else:
            self._ensure_perspective_agent(session, perspective)
        return self._save_state(state)

    @_serialized_session_mutation
    async def remove_perspective(
        self, session_id: str, perspective_id: str
    ) -> SessionState:
        session = self._require(session_id)
        state = session.state
        if state.integrated_into_parent_at is not None:
            raise SessionError(
                "This research branch was already continued.",
                status=409,
            )
        orphaned = {a.iid for a in state.agents if a.perspective_id == perspective_id}
        archived_iids = {
            iid
            for deliberation in state.deliberations
            for completion in deliberation.completion_history
            for iid in [
                *completion.agent_iids,
                *(
                    participant_iid
                    for round_state in completion.rounds
                    for participant_iid in round_state.participant_iids
                ),
            ]
        }
        if orphaned & archived_iids or any(
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
        if state.deliberations:
            return state
        for perspective in state.perspectives:
            self._ensure_perspective_agent(session, perspective)
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
                    inherited.model_copy(deep=True) if inherited is not None else None
                ),
                hypothesis_confirmed=inherited is not None,
            )
        )
        return self._save_state(state)

    @_serialized_session_mutation
    async def initialize_deliberation(
        self,
        session_id: str,
        deliberation_id: str,
        lead_perspective_id: str,
    ) -> SessionState:
        session = self._require(session_id)
        state = session.state
        deliberation = self._deliberation(state, deliberation_id)
        self._require_open_deliberation(deliberation)
        if deliberation.rounds:
            legacy_rounds = (
                deliberation.lead_perspective_id is None
                and deliberation.baseline_hypothesis is None
            )
            if not legacy_rounds:
                raise SessionError("The lead cannot change after round 1.")
            agent_by_iid = {agent.iid: agent for agent in state.agents}
            roster = [
                agent_by_iid[iid].perspective_id
                for iid in deliberation.agent_iids
                if iid in agent_by_iid
            ]
            deliberation = self._restart_deliberation(session, roster)
        lead = next(
            (
                agent
                for agent in state.agents
                if agent.iid in deliberation.agent_iids
                and agent.perspective_id == lead_perspective_id
            ),
            None,
        )
        if lead is None:
            raise SessionError("Choose a Perspective wired into this panel.")
        if (
            deliberation.lead_perspective_id == lead_perspective_id
            and deliberation.baseline_hypothesis is not None
        ):
            return state
        baseline = await agents.develop_hypothesis(
            self._agent_profile(state, lead),
            provider=self._provider_for(session),
        )
        lead.hypothesis = baseline.model_copy(deep=True)
        deliberation.lead_perspective_id = lead_perspective_id
        deliberation.baseline_hypothesis = baseline.model_copy(deep=True)
        deliberation.hypothesis = baseline.model_copy(deep=True)
        deliberation.applied_hypothesis = baseline.model_copy(deep=True)
        deliberation.hypothesis_confirmed = True
        deliberation.working_hypothesis_source_kind = None
        deliberation.working_hypothesis_source_round = None
        return self._save_state(state)

    @staticmethod
    def _deliberation_lead(
        state: SessionState,
        deliberation: DeliberationState,
    ) -> AgentState | None:
        return next(
            (
                agent
                for agent in state.agents
                if agent.iid in deliberation.agent_iids
                and agent.perspective_id == deliberation.lead_perspective_id
            ),
            None,
        )

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
        progress_generation: int | None = None,
    ) -> SessionState:
        """Run one user-directed round over exactly one hypothesis facet."""
        session = self._require(session_id)
        state = session.state
        if progress_generation is None:
            self.start_search_progress(state.id)
        elif self._search_progress_generation.get(state.id) != progress_generation:
            raise SessionError("Round progress generation is stale.", status=409)
        self._search_progress_active_generation[state.id] = (
            self._search_progress_generation[state.id]
        )
        deliberation = self._deliberation(state, deliberation_id)
        self._require_open_deliberation(deliberation)
        selected = list(dict.fromkeys(facets))
        if len(selected) != 1 or len(facets) != 1:
            raise SessionError("Select exactly one area for this round.")
        if any(facet not in FACETS for facet in selected):
            raise SessionError(
                "Choose from Scope, Explanation, Approach, and Significance."
            )
        if len(deliberation.agent_iids) < 2:
            raise SessionError("Wire in at least two agents first.")
        if lead_iid not in deliberation.agent_iids:
            raise SessionError("The lead must be wired into this deliberation.")
        if (
            deliberation.lead_perspective_id is None
            or deliberation.baseline_hypothesis is None
        ):
            raise SessionError("Choose a lead and generate its baseline first.")
        configured_lead = self._deliberation_lead(state, deliberation)
        if configured_lead is None or configured_lead.iid != lead_iid:
            raise SessionError("Use the configured lead for every round.")
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
        round_state.hypothesis_before = (
            deliberation.applied_hypothesis.model_copy(deep=True)
            if deliberation.applied_hypothesis is not None
            else None
        )
        deliberation.rounds.append(round_state)
        before = self._facet_snapshot(state, participant_iids)

        lead_agent, lead_profile = self._agent_view(state, lead_iid)
        other_profiles = [
            self._agent_view(state, iid)[1]
            for iid in participant_iids
            if iid != lead_iid
        ]

        def report(
            step: int,
            stage: str,
            message: str,
            *,
            kind: SearchProgressKind = "round_stage",
            turn: Turn | None = None,
        ) -> None:
            self._publish_search_progress(
                state.id,
                kind,
                message,
                stage=stage,
                step=step,
                total_steps=7,
                agent_label=turn.agent_label if turn is not None else None,
                text=turn.text if turn is not None else None,
            )

        report(1, "lead", "Lead is drafting the opening statement.")

        async def speak(turn: Turn) -> None:
            round_state.turns.append(turn)
            report(
                1,
                "exchange",
                f"{turn.agent_label or 'Panel'} responded.",
                kind="round_turn",
                turn=turn,
            )

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
            report(2, "panel", "Panel Perspectives are responding.")

            answers: list[Turn] = []
            answer_tasks = []
            try:
                async with asyncio.TaskGroup() as task_group:
                    for iid in participant_iids:
                        if iid == lead_iid:
                            continue
                        agent, profile = self._agent_view(state, iid)
                        answer_tasks.append(
                            (
                                iid,
                                agent,
                                profile,
                                task_group.create_task(
                                    agents.answer_statement(
                                        profile,
                                        facet,
                                        lead_agent.label,
                                        statement.text,
                                        provider=self._provider_for(session),
                                    )
                                ),
                            )
                        )
            except* Exception as errors:  # noqa: BLE001
                raise errors.exceptions[0]
            for iid, agent, profile, task in answer_tasks:
                response = task.result()
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
            report(3, "judging", "Moderator is judging agreement.")
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

        report(4, "summary", "Moderator is synthesizing the round.")
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

        report(5, "lead_revision", "Updating the lead Perspective.")
        consensus_resolution = RoundResolution(
            summary=resolution.summary,
            consensus_points=[
                point.model_copy(deep=True) for point in resolution.consensus_points
            ],
        )
        reflection, updated = await agents.reflect_on_round(
            lead_iid,
            lead_profile,
            selected,
            consensus_resolution,
            provider=self._provider_for(session),
        )
        lead_agent.facets = updated
        if reflection.decision == "revised":
            lead_agent.facet_version += 1
        round_state.reflections.append(reflection)

        after = self._facet_snapshot(state, participant_iids)
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
        revised.summary = resolution.summary

        report(6, "hypothesis", "Generating the hypothesis proposal.")
        hypothesis_task = None
        try:
            async with asyncio.TaskGroup() as task_group:
                metrics_task = task_group.create_task(
                    self._round_metrics(session, before, after)
                )
                framing_task = task_group.create_task(
                    agents.derive_framing(
                        revised,
                        provider=self._provider_for(session),
                    )
                )
                questions_task = task_group.create_task(
                    agents.recommend_questions(
                        resolution,
                        revised,
                        provider=self._provider_for(session),
                    )
                )
                if resolution.consensus_points:
                    hypothesis_task = task_group.create_task(
                        agents.develop_hypothesis_from_consensus(
                            consensus_resolution,
                            current=deliberation.applied_hypothesis,
                            provider=self._provider_for(session),
                        )
                    )
        except* Exception as errors:  # noqa: BLE001
            raise errors.exceptions[0]

        round_state.metrics = metrics_task.result()
        revised.framing = framing_task.result()
        deliberation.revised_perspective = revised

        if hypothesis_task is not None:
            deliberation.no_agreement = False
            proposed_hypothesis = hypothesis_task.result()
            if deliberation.applied_hypothesis is not None:
                proposed_hypothesis = proposed_hypothesis.model_copy(
                    update={
                        part: getattr(deliberation.applied_hypothesis, part)
                        for part in (
                            "problem",
                            "previous_work",
                            "reasoning",
                            "hypothesis",
                        )
                        if not getattr(proposed_hypothesis, part).strip()
                        or getattr(proposed_hypothesis, part).strip()
                        == "Not established yet."
                    }
                )
            round_state.hypothesis_proposal = proposed_hypothesis.model_copy(deep=True)
            if deliberation.applied_hypothesis is not None and self._same_hypothesis(
                proposed_hypothesis,
                deliberation.applied_hypothesis,
            ):
                deliberation.hypothesis = deliberation.applied_hypothesis.model_copy(
                    deep=True
                )
                deliberation.hypothesis_confirmed = True
            else:
                deliberation.hypothesis = proposed_hypothesis
                deliberation.hypothesis_confirmed = False
        else:
            deliberation.no_agreement = True

        questions = questions_task.result()
        prior_questions = [
            *(
                question
                for completion in deliberation.completion_history
                for question in completion.recommended_questions
            ),
            *deliberation.recommended_questions,
        ]
        unresolved = {
            " ".join(item.question.casefold().split())
            for item in prior_questions
            if item.status in {"open", "investigating"}
        }
        new_questions: list[RecommendedQuestion] = []
        cycle_suffix = (
            f"-c{len(deliberation.completion_history) + 1}"
            if deliberation.completion_history
            else ""
        )
        for index, question in enumerate(questions, start=1):
            identity = " ".join(question.question.casefold().split())
            if identity in unresolved:
                continue
            unresolved.add(identity)
            new_questions.append(
                question.model_copy(
                    update={
                        "id": (
                            f"{deliberation.id}{cycle_suffix}-r{round_state.n}-q{index}"
                        ),
                        "source_round": round_state.n,
                    }
                )
            )
        deliberation.recommended_questions.extend(new_questions)
        deliberation.questions_generated = True
        round_state.completed = True
        report(7, "saving", "Saving the completed round.")

        return self._save_state(state)

    @_serialized_session_mutation
    async def complete_deliberation(
        self,
        session_id: str,
        deliberation_id: str,
        selected_question_ids: list[str] | None = None,
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
        covered_facets = {
            facet
            for round_state in deliberation.rounds
            if round_state.completed
            for facet in round_state.facets
        }
        missing_facets = [facet for facet in FACETS if facet not in covered_facets]
        if missing_facets:
            raise SessionError(
                "Discuss all four areas before ending the deliberation; "
                f"missing {missing_facets}."
            )
        completed_round_count = sum(
            round_state.completed for round_state in deliberation.rounds
        )
        if completed_round_count < 4:
            raise SessionError(
                "Complete at least four focused rounds before ending the "
                "deliberation."
            )
        selected = (
            deliberation.selected_question_ids
            if selected_question_ids is None
            else selected_question_ids
        )
        selection = list(dict.fromkeys(selected))
        known_questions = {
            question.id: question
            for question in deliberation.recommended_questions
            if question.status == "open"
        }
        unknown_questions = [
            question_id
            for question_id in selection
            if question_id not in known_questions
        ]
        if unknown_questions:
            raise SessionError(
                f"unknown open questions: {unknown_questions}",
                status=404,
            )
        deliberation.selected_question_ids = selection
        for question in deliberation.recommended_questions:
            question.selected_for_followup = question.id in selection
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
        latest_round = deliberation.rounds[-1]
        if mode == "reject_pending":
            if deliberation.hypothesis_confirmed:
                raise SessionError(
                    "There is no pending hypothesis update to reject.",
                    status=409,
                )
            if deliberation.applied_hypothesis is None:
                raise SessionError("There is no previous hypothesis to keep.")
            deliberation.hypothesis = deliberation.applied_hypothesis.model_copy(
                deep=True
            )
            deliberation.hypothesis_confirmed = True
            lead_agent = self._deliberation_lead(session.state, deliberation)
            if lead_agent is not None:
                lead_agent.hypothesis = (
                    deliberation.applied_hypothesis.model_copy(deep=True)
                )
            latest_round.hypothesis_decision = "rejected"
            return self._save_state(session.state)
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
            latest_round.hypothesis_decision = (
                "accepted"
                if latest_round.hypothesis_proposal is not None
                and self._same_hypothesis(
                    latest_round.hypothesis_proposal,
                    applied,
                )
                else "edited"
            )
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
        lead_agent = self._deliberation_lead(session.state, deliberation)
        if lead_agent is not None:
            lead_agent.hypothesis = applied.model_copy(deep=True)
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
        workspace = self._workspace_for(session.state)
        current_version_id = session.state.applied_hypothesis_version_id
        latest_archive = (
            deliberation.completion_history[-1]
            if deliberation.completion_history
            else None
        )
        fresh_cycle = (
            latest_archive is not None
            and current_version_id == latest_archive.applied_hypothesis_version_id
        )
        if (
            not fresh_cycle
            and current_version_id is not None
            and session.state.applied_hypothesis == working
        ):
            return session.state

        advances_promoted_branch = (
            not fresh_cycle
            and current_version_id is not None
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
            parent_ids=[] if fresh_cycle else None,
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
            "schema_version": 5,
            "exported_at": utcnow().isoformat(),
            "workspace": view.workspace.model_dump(mode="json"),
            "investigations": [
                self._require(investigation_id).state.model_dump(mode="json")
                for investigation_id in view.workspace.investigation_ids
            ],
        }
