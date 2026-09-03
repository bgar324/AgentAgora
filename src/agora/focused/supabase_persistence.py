"""Supabase-backed aggregate snapshots for baseline studies."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from postgrest import ReturnMethod
from pydantic import ValidationError

from agora.focused.models import SessionState, WorkspaceState
from agora.focused.persistence import FocusedPersistence, PersistenceConflict
from agora.focused.study_log import StudyAssignment, StudyEvent

logger = logging.getLogger(__name__)

SNAPSHOT_TABLE = "focused_workspace_snapshots"
QUARANTINE_TABLE = "focused_workspace_quarantine"
ASSIGNMENT_TABLE = "focused_study_assignments"
EVENT_TABLE = "focused_interaction_events"
CREATE_STUDY_RPC = "create_focused_study_workspace"
SAVE_STUDY_RPC = "save_focused_study_workspace"
DELETE_STUDY_RPC = "delete_focused_study_workspace"
ASSIGNMENT_PAGE_SIZE = 1000


class SupabaseFocusedPersistence:
    """Persist each complete workspace aggregate in one revisioned JSONB row."""

    def __init__(
        self,
        url: str | None = None,
        secret_key: str | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        if client is None:
            if not url or not secret_key:
                raise ValueError("Supabase persistence requires its URL and secret key")
            from supabase import ClientOptions, create_client

            client = create_client(
                url,
                secret_key,
                options=ClientOptions(
                    auto_refresh_token=False,
                    persist_session=False,
                ),
            )
        self._client = client
        self._lock = Lock()

    @staticmethod
    def _payload(
        workspace: WorkspaceState,
        investigations: list[SessionState],
    ) -> dict[str, Any]:
        FocusedPersistence._validate_membership(workspace, investigations)
        return {
            "workspace": workspace.model_dump(mode="json"),
            "investigations": [
                investigation.model_dump(mode="json")
                for investigation in investigations
            ],
        }

    @staticmethod
    def _assignment_payload(assignment: StudyAssignment) -> dict[str, Any]:
        return assignment.model_dump(mode="json")

    @staticmethod
    def _event_payload(event: StudyEvent) -> dict[str, Any]:
        return event.model_dump(
            mode="json",
            exclude={"event_seq", "recorded_at"},
        )

    @staticmethod
    def _parse_row(row: Mapping[str, Any]) -> tuple[WorkspaceState, list[SessionState]]:
        workspace_id = str(row.get("workspace_id") or "")
        revision = row.get("revision")
        payload = row.get("payload")
        if not workspace_id or not isinstance(revision, int):
            raise ValueError("snapshot row has an invalid identity or revision")
        if not isinstance(payload, Mapping):
            raise TypeError("snapshot payload must be an object")
        raw_investigations = payload.get("investigations")
        if not isinstance(raw_investigations, list):
            raise TypeError("snapshot Investigations must be a list")

        workspace = WorkspaceState.model_validate(payload.get("workspace"))
        investigations = [
            SessionState.model_validate(investigation)
            for investigation in raw_investigations
        ]
        if workspace.id != workspace_id:
            raise ValueError("workspace row ID does not match payload ID")
        if workspace.revision != revision:
            raise ValueError("workspace row revision does not match payload")
        FocusedPersistence._validate_membership(workspace, investigations)
        return workspace, investigations

    def _quarantine(self, row: Mapping[str, Any], error: Exception) -> None:
        workspace_id = str(row.get("workspace_id") or "")
        if not workspace_id:
            raise ValueError("cannot quarantine a snapshot without a workspace ID")
        revision = row.get("revision")
        payload = row.get("payload")
        safe_payload = (
            payload if isinstance(payload, Mapping) else {"invalid_payload": payload}
        )
        reason = FocusedPersistence._reason(error)
        self._client.table(QUARANTINE_TABLE).upsert(
            {
                "workspace_id": workspace_id,
                "revision": revision if isinstance(revision, int) else None,
                "payload": safe_payload,
                "reason": reason,
                "quarantined_at": datetime.now(UTC).isoformat(),
            },
            on_conflict="workspace_id",
        ).execute()
        deletion = (
            self._client.table(SNAPSHOT_TABLE).delete().eq("workspace_id", workspace_id)
        )
        if isinstance(revision, int):
            deletion = deletion.eq("revision", revision)
        deletion.execute()
        logger.error(
            "Quarantined invalid focused workspace %s: %s", workspace_id, reason
        )

    def load(self) -> tuple[list[WorkspaceState], list[SessionState]]:
        with self._lock:
            rows = (
                self._client.table(SNAPSHOT_TABLE)
                .select("workspace_id,revision,payload")
                .execute()
                .data
                or []
            )
            workspaces: list[WorkspaceState] = []
            investigations: list[SessionState] = []
            for row in rows:
                try:
                    workspace, states = self._parse_row(row)
                except (ValidationError, ValueError, TypeError) as error:
                    self._quarantine(row, error)
                    continue
                workspaces.append(workspace)
                investigations.extend(states)
            return workspaces, investigations

    def load_study_assignments(self) -> list[StudyAssignment]:
        rows: list[Mapping[str, Any]] = []
        after_workspace_id = ""
        with self._lock:
            while True:
                query = (
                    self._client.table(ASSIGNMENT_TABLE)
                    .select(
                        "schema_version,workspace_id,participant_id,"
                        "condition,assigned_at"
                    )
                    .order("workspace_id")
                    .limit(ASSIGNMENT_PAGE_SIZE)
                )
                if after_workspace_id:
                    query = query.gt("workspace_id", after_workspace_id)
                page = query.execute().data or []
                if not page:
                    break
                rows.extend(page)
                next_workspace_id = page[-1].get("workspace_id")
                if (
                    not isinstance(next_workspace_id, str)
                    or next_workspace_id <= after_workspace_id
                ):
                    raise ValueError(
                        "assignment page is not ordered by workspace ID"
                    )
                after_workspace_id = next_workspace_id
        return [StudyAssignment.model_validate(row) for row in rows]

    def load_study_events(
        self,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> list[StudyEvent]:
        if after_sequence < 0:
            raise ValueError("study event sequence cannot be negative")
        if not 1 <= limit <= 10_000:
            raise ValueError("study event page size must be between 1 and 10000")
        with self._lock:
            rows = (
                self._client.table(EVENT_TABLE)
                .select("*")
                .gt("event_seq", after_sequence)
                .order("event_seq")
                .limit(limit)
                .execute()
                .data
                or []
            )
        return [StudyEvent.model_validate(row) for row in rows]

    def append_study_event(self, event: StudyEvent) -> None:
        with self._lock:
            self._client.table(EVENT_TABLE).insert(self._event_payload(event)).execute()

    def create(
        self,
        workspace: WorkspaceState,
        investigations: list[SessionState],
        *,
        assignment: StudyAssignment | None = None,
        event: StudyEvent | None = None,
    ) -> None:
        payload = self._payload(workspace, investigations)
        if (assignment is None) != (event is None):
            raise ValueError("study workspace creation requires assignment and event")
        with self._lock:
            if assignment is None:
                self._client.table(SNAPSHOT_TABLE).insert(
                    {
                        "workspace_id": workspace.id,
                        "revision": workspace.revision,
                        "payload": payload,
                    }
                ).execute()
                return
            self._client.rpc(
                CREATE_STUDY_RPC,
                {
                    "p_workspace_id": workspace.id,
                    "p_revision": workspace.revision,
                    "p_payload": payload,
                    "p_assignment": self._assignment_payload(assignment),
                    "p_event": self._event_payload(event),
                },
            ).execute()

    def save(
        self,
        workspace: WorkspaceState,
        investigations: list[SessionState],
        *,
        expected_revision: int,
        event: StudyEvent | None = None,
    ) -> None:
        if workspace.revision != expected_revision + 1:
            raise ValueError("workspace revision must advance exactly once")
        payload = self._payload(workspace, investigations)
        with self._lock:
            if event is None:
                response = (
                    self._client.table(SNAPSHOT_TABLE)
                    .update(
                        {"revision": workspace.revision, "payload": payload},
                        returning=ReturnMethod.representation,
                    )
                    .eq("workspace_id", workspace.id)
                    .eq("revision", expected_revision)
                    .execute()
                )
                saved = len(response.data or []) == 1
            else:
                response = self._client.rpc(
                    SAVE_STUDY_RPC,
                    {
                        "p_workspace_id": workspace.id,
                        "p_expected_revision": expected_revision,
                        "p_revision": workspace.revision,
                        "p_payload": payload,
                        "p_event": self._event_payload(event),
                    },
                ).execute()
                saved = response.data is True
        if not saved:
            raise PersistenceConflict(
                f"workspace {workspace.id} changed or was deleted"
            )

    def delete(
        self,
        workspace_id: str,
        *,
        expected_revision: int,
        event: StudyEvent | None = None,
    ) -> None:
        with self._lock:
            if event is None:
                response = (
                    self._client.table(SNAPSHOT_TABLE)
                    .delete(returning=ReturnMethod.representation)
                    .eq("workspace_id", workspace_id)
                    .eq("revision", expected_revision)
                    .execute()
                )
                deleted = len(response.data or []) == 1
            else:
                response = self._client.rpc(
                    DELETE_STUDY_RPC,
                    {
                        "p_workspace_id": workspace_id,
                        "p_expected_revision": expected_revision,
                        "p_event": self._event_payload(event),
                    },
                ).execute()
                deleted = response.data is True
        if not deleted:
            raise PersistenceConflict(
                f"workspace {workspace_id} changed or was deleted"
            )
