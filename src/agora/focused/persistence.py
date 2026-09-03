"""SQLite revisioned snapshots for baseline studies."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

from pydantic import ValidationError

from agora.focused.models import SessionState, WorkspaceState
from agora.focused.study_log import StudyAssignment, StudyEvent

logger = logging.getLogger(__name__)


class PersistenceConflict(RuntimeError):
    """A stale service instance attempted to overwrite a newer workspace."""


class WorkspacePersistence(Protocol):
    def load(self) -> tuple[list[WorkspaceState], list[SessionState]]: ...

    def create(
        self,
        workspace: WorkspaceState,
        investigations: list[SessionState],
        *,
        assignment: StudyAssignment | None = None,
        event: StudyEvent | None = None,
    ) -> None: ...

    def save(
        self,
        workspace: WorkspaceState,
        investigations: list[SessionState],
        *,
        expected_revision: int,
        event: StudyEvent | None = None,
    ) -> None: ...

    def delete(
        self,
        workspace_id: str,
        *,
        expected_revision: int,
        event: StudyEvent | None = None,
    ) -> None: ...

    def load_study_assignments(self) -> list[StudyAssignment]: ...

    def load_study_events(
        self,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> list[StudyEvent]: ...

    def append_study_event(self, event: StudyEvent) -> None: ...


class FocusedPersistence:
    """Persist focused workspace snapshots with durable revision checks."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._lock = Lock()
        self._connection.execute("pragma busy_timeout = 5000")
        with self._connection:
            self._connection.executescript(
                """
                create table if not exists focused_workspaces(
                    workspace_id text primary key,
                    revision integer not null default 0,
                    payload text not null
                );
                create table if not exists focused_investigations(
                    investigation_id text primary key,
                    workspace_id text not null,
                    payload text not null
                );
                create index if not exists focused_investigation_workspace
                    on focused_investigations(workspace_id);
                create table if not exists focused_quarantine(
                    kind text not null,
                    record_id text not null,
                    workspace_id text,
                    payload text not null,
                    reason text not null,
                    quarantined_at text not null,
                    primary key(kind, record_id)
                );
                create table if not exists focused_workspace_archives(
                    workspace_id text not null,
                    schema_version integer not null,
                    revision integer not null,
                    payload text not null,
                    archived_at text not null,
                    primary key(workspace_id, schema_version)
                );
                create table if not exists focused_study_assignments(
                    workspace_id text primary key,
                    schema_version integer not null,
                    participant_id text,
                    condition text not null,
                    assigned_at text not null,
                    check(schema_version = 1)
                );
                create table if not exists focused_interaction_events(
                    event_seq integer primary key autoincrement,
                    event_id text not null unique,
                    schema_version integer not null,
                    workspace_id text not null,
                    session_id text,
                    participant_id text,
                    condition text,
                    action text not null,
                    stage text not null,
                    outcome text not null,
                    occurred_at text not null,
                    recorded_at text not null,
                    duration_ms integer not null check(duration_ms >= 0),
                    revision_before integer,
                    revision_after integer,
                    object_type text,
                    object_id text,
                    error_code text,
                    details text not null,
                    check(schema_version = 1),
                    check(outcome in ('success', 'failure')),
                    check((object_type is null) = (object_id is null)),
                    check(
                        (outcome = 'success' and error_code is null)
                        or (outcome = 'failure' and error_code is not null)
                    )
                );
                create index if not exists focused_interaction_workspace
                    on focused_interaction_events(workspace_id, event_seq);
                create index if not exists focused_interaction_participant
                    on focused_interaction_events(participant_id, event_seq);
                create index if not exists focused_interaction_condition
                    on focused_interaction_events(condition, event_seq);
                create trigger if not exists reject_focused_assignment_update
                before update on focused_study_assignments
                begin
                    select raise(abort, 'focused study assignments are immutable');
                end;
                create trigger if not exists reject_focused_assignment_delete
                before delete on focused_study_assignments
                begin
                    select raise(abort, 'focused study assignments are immutable');
                end;
                create trigger if not exists reject_focused_interaction_update
                before update on focused_interaction_events
                begin
                    select raise(abort, 'focused interaction events are append-only');
                end;
                create trigger if not exists reject_focused_interaction_delete
                before delete on focused_interaction_events
                begin
                    select raise(abort, 'focused interaction events are append-only');
                end;
                """
            )
            columns = {
                row["name"]
                for row in self._connection.execute(
                    "pragma table_info(focused_workspaces)"
                )
            }
            if "revision" not in columns:
                self._connection.execute(
                    "alter table focused_workspaces "
                    "add column revision integer not null default 0"
                )

    def _begin_write(self) -> None:
        self._connection.execute("begin immediate")

    def _commit(self) -> None:
        self._connection.commit()

    def _rollback(self) -> None:
        self._connection.rollback()

    @staticmethod
    def _reason(error: Exception) -> str:
        message = str(error).splitlines()[0].strip()
        return message[:1000] or type(error).__name__

    def _quarantine(
        self,
        records: list[tuple[str, str, str | None, str, str]],
    ) -> None:
        if not records:
            return
        now = datetime.now(UTC).isoformat()
        self._begin_write()
        try:
            self._connection.executemany(
                """
                insert into focused_quarantine(
                    kind, record_id, workspace_id, payload, reason, quarantined_at
                ) values (?, ?, ?, ?, ?, ?)
                on conflict(kind, record_id) do update set
                    workspace_id = excluded.workspace_id,
                    payload = excluded.payload,
                    reason = excluded.reason,
                    quarantined_at = excluded.quarantined_at
                """,
                [(*record, now) for record in records],
            )
            for kind, record_id, _, _, _ in records:
                if kind == "workspace":
                    self._connection.execute(
                        "delete from focused_workspaces where workspace_id = ?",
                        (record_id,),
                    )
                else:
                    self._connection.execute(
                        "delete from focused_investigations where investigation_id = ?",
                        (record_id,),
                    )
        except Exception:
            self._rollback()
            raise
        self._commit()
        for kind, record_id, _, _, reason in records:
            logger.error(
                "Quarantined invalid focused %s %s: %s",
                kind,
                record_id,
                reason,
            )

    def load(self) -> tuple[list[WorkspaceState], list[SessionState]]:
        with self._lock:
            workspace_rows = self._connection.execute(
                "select workspace_id, revision, payload "
                "from focused_workspaces order by rowid"
            ).fetchall()
            investigation_rows = self._connection.execute(
                "select investigation_id, workspace_id, payload "
                "from focused_investigations order by rowid"
            ).fetchall()

            workspaces: dict[str, WorkspaceState] = {}
            investigations: dict[str, SessionState] = {}
            investigation_payloads: dict[str, tuple[str, str]] = {}
            quarantine: list[tuple[str, str, str | None, str, str]] = []

            for row in workspace_rows:
                record_id = row["workspace_id"]
                payload = row["payload"]
                try:
                    workspace = WorkspaceState.model_validate_json(payload)
                    if workspace.id != record_id:
                        raise ValueError("workspace row ID does not match payload ID")
                    if workspace.revision != row["revision"]:
                        raise ValueError(
                            "workspace row revision does not match payload"
                        )
                    workspaces[workspace.id] = workspace
                except (ValidationError, ValueError) as error:
                    quarantine.append(
                        (
                            "workspace",
                            record_id,
                            record_id,
                            payload,
                            self._reason(error),
                        )
                    )

            for row in investigation_rows:
                record_id = row["investigation_id"]
                row_workspace_id = row["workspace_id"]
                payload = row["payload"]
                investigation_payloads[record_id] = (row_workspace_id, payload)
                try:
                    investigation = SessionState.model_validate_json(payload)
                    if investigation.id != record_id:
                        raise ValueError(
                            "Investigation row ID does not match payload ID"
                        )
                    if investigation.workspace_id != row_workspace_id:
                        raise ValueError(
                            "Investigation row workspace does not match payload"
                        )
                    investigations[investigation.id] = investigation
                except (ValidationError, ValueError) as error:
                    quarantine.append(
                        (
                            "investigation",
                            record_id,
                            row_workspace_id,
                            payload,
                            self._reason(error),
                        )
                    )

            invalid_workspaces: dict[str, str] = {}
            for workspace in workspaces.values():
                missing = [
                    investigation_id
                    for investigation_id in workspace.investigation_ids
                    if investigation_id not in investigations
                ]
                wrong_owner = [
                    investigation_id
                    for investigation_id in workspace.investigation_ids
                    if investigation_id in investigations
                    and investigations[investigation_id].workspace_id != workspace.id
                ]
                if missing:
                    invalid_workspaces[workspace.id] = (
                        f"workspace references missing Investigations: {missing}"
                    )
                elif wrong_owner:
                    invalid_workspaces[workspace.id] = (
                        f"workspace references foreign Investigations: {wrong_owner}"
                    )
                else:
                    study = investigations[workspace.root_investigation_id]
                    if study.workspace_id != workspace.id:
                        invalid_workspaces[workspace.id] = (
                            "workspace study belongs to another workspace"
                        )

            for workspace_id, reason in invalid_workspaces.items():
                workspace = workspaces.pop(workspace_id)
                quarantine.append(
                    (
                        "workspace",
                        workspace_id,
                        workspace_id,
                        workspace.model_dump_json(),
                        reason,
                    )
                )

            referenced: dict[str, str] = {}
            for workspace in workspaces.values():
                for investigation_id in workspace.investigation_ids:
                    owner = referenced.get(investigation_id)
                    if owner is not None and owner != workspace.id:
                        raise ValueError(
                            f"Investigation {investigation_id} belongs to two workspaces"
                        )
                    referenced[investigation_id] = workspace.id

            for investigation_id, investigation in list(investigations.items()):
                expected_owner = referenced.get(investigation_id)
                if expected_owner == investigation.workspace_id:
                    continue
                investigations.pop(investigation_id)
                row_workspace_id, payload = investigation_payloads[investigation_id]
                quarantine.append(
                    (
                        "investigation",
                        investigation_id,
                        row_workspace_id,
                        payload,
                        "Investigation is not reachable from one valid workspace",
                    )
                )

            invalid_ids = {(kind, record_id) for kind, record_id, _, _, _ in quarantine}
            deduplicated = [
                record
                for index, record in enumerate(quarantine)
                if (record[0], record[1])
                not in {(prior[0], prior[1]) for prior in quarantine[:index]}
            ]
            if invalid_ids:
                self._quarantine(deduplicated)

        return list(workspaces.values()), list(investigations.values())

    def load_study_assignments(self) -> list[StudyAssignment]:
        with self._lock:
            rows = self._connection.execute(
                """
                select schema_version, workspace_id, participant_id,
                       condition, assigned_at
                from focused_study_assignments
                order by assigned_at, workspace_id
                """
            ).fetchall()
        return [StudyAssignment.model_validate(dict(row)) for row in rows]

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
            rows = self._connection.execute(
                """
                select event_seq, event_id, schema_version, workspace_id,
                       session_id, participant_id, condition, action, stage,
                       outcome, occurred_at, recorded_at, duration_ms,
                       revision_before, revision_after, object_type, object_id,
                       error_code, details
                from focused_interaction_events
                where event_seq > ?
                order by event_seq
                limit ?
                """,
                (after_sequence, limit),
            ).fetchall()
        return [
            StudyEvent.model_validate(
                {
                    **dict(row),
                    "details": json.loads(row["details"]),
                }
            )
            for row in rows
        ]

    def _write_study_assignment(self, assignment: StudyAssignment) -> None:
        self._connection.execute(
            """
            insert into focused_study_assignments(
                workspace_id, schema_version, participant_id,
                condition, assigned_at
            ) values (?, ?, ?, ?, ?)
            """,
            (
                assignment.workspace_id,
                assignment.schema_version,
                assignment.participant_id,
                assignment.condition,
                assignment.assigned_at.isoformat(),
            ),
        )

    def _write_study_event(self, event: StudyEvent) -> None:
        self._connection.execute(
            """
            insert into focused_interaction_events(
                event_id, schema_version, workspace_id, session_id,
                participant_id, condition, action, stage, outcome,
                occurred_at, recorded_at, duration_ms, revision_before,
                revision_after, object_type, object_id, error_code, details
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.schema_version,
                event.workspace_id,
                event.session_id,
                event.participant_id,
                event.condition,
                event.action.value,
                event.stage.value,
                event.outcome.value,
                event.occurred_at.isoformat(),
                datetime.now(UTC).isoformat(),
                event.duration_ms,
                event.revision_before,
                event.revision_after,
                event.object_type,
                event.object_id,
                event.error_code.value if event.error_code else None,
                json.dumps(event.details, separators=(",", ":"), sort_keys=True),
            ),
        )

    def append_study_event(self, event: StudyEvent) -> None:
        with self._lock:
            self._begin_write()
            try:
                self._write_study_event(event)
            except Exception:
                self._rollback()
                raise
            self._commit()

    @staticmethod
    def _validate_membership(
        workspace: WorkspaceState,
        investigations: list[SessionState],
    ) -> None:
        expected = set(workspace.investigation_ids)
        actual = {state.id for state in investigations}
        if expected != actual:
            raise ValueError("workspace save requires its complete Investigation set")
        if any(state.workspace_id != workspace.id for state in investigations):
            raise ValueError("cannot save an Investigation under another workspace")

    def create(
        self,
        workspace: WorkspaceState,
        investigations: list[SessionState],
        *,
        assignment: StudyAssignment | None = None,
        event: StudyEvent | None = None,
    ) -> None:
        self._validate_membership(workspace, investigations)
        if (assignment is None) != (event is None):
            raise ValueError("study workspace creation requires assignment and event")
        if assignment is not None and assignment.workspace_id != workspace.id:
            raise ValueError("study assignment belongs to another workspace")
        if event is not None and event.workspace_id != workspace.id:
            raise ValueError("study event belongs to another workspace")
        with self._lock:
            self._begin_write()
            try:
                self._connection.execute(
                    "insert into focused_workspaces(workspace_id, revision, payload) "
                    "values (?, ?, ?)",
                    (workspace.id, workspace.revision, workspace.model_dump_json()),
                )
                self._write_investigations(workspace, investigations)
                if assignment is not None:
                    self._write_study_assignment(assignment)
                if event is not None:
                    self._write_study_event(event)
            except Exception:
                self._rollback()
                raise
            self._commit()

    def _write_investigations(
        self,
        workspace: WorkspaceState,
        investigations: list[SessionState],
    ) -> None:
        for state in investigations:
            row = self._connection.execute(
                "select workspace_id from focused_investigations "
                "where investigation_id = ?",
                (state.id,),
            ).fetchone()
            if row is not None and row["workspace_id"] != workspace.id:
                raise ValueError(
                    "Investigation ID already belongs to another workspace"
                )
            self._connection.execute(
                """
                insert into focused_investigations(
                    investigation_id, workspace_id, payload
                ) values (?, ?, ?)
                on conflict(investigation_id) do update set payload = excluded.payload
                """,
                (state.id, workspace.id, state.model_dump_json()),
            )
        placeholders = ",".join("?" for _ in investigations)
        self._connection.execute(
            f"delete from focused_investigations "
            f"where workspace_id = ? and investigation_id not in ({placeholders})",
            (workspace.id, *(state.id for state in investigations)),
        )

    def save(
        self,
        workspace: WorkspaceState,
        investigations: list[SessionState],
        *,
        expected_revision: int,
        event: StudyEvent | None = None,
    ) -> None:
        self._validate_membership(workspace, investigations)
        if workspace.revision != expected_revision + 1:
            raise ValueError("workspace revision must advance exactly once")
        if event is not None and event.workspace_id != workspace.id:
            raise ValueError("study event belongs to another workspace")
        with self._lock:
            self._begin_write()
            try:
                updated = self._connection.execute(
                    """
                    update focused_workspaces
                    set revision = ?, payload = ?
                    where workspace_id = ? and revision = ?
                    """,
                    (
                        workspace.revision,
                        workspace.model_dump_json(),
                        workspace.id,
                        expected_revision,
                    ),
                )
                if updated.rowcount != 1:
                    raise PersistenceConflict(
                        f"workspace {workspace.id} changed or was deleted"
                    )
                self._write_investigations(workspace, investigations)
                if event is not None:
                    self._write_study_event(event)
            except Exception:
                self._rollback()
                raise
            self._commit()

    def delete(
        self,
        workspace_id: str,
        *,
        expected_revision: int,
        event: StudyEvent | None = None,
    ) -> None:
        if event is not None and event.workspace_id != workspace_id:
            raise ValueError("study event belongs to another workspace")
        with self._lock:
            self._begin_write()
            try:
                deleted = self._connection.execute(
                    "delete from focused_workspaces "
                    "where workspace_id = ? and revision = ?",
                    (workspace_id, expected_revision),
                )
                if deleted.rowcount != 1:
                    raise PersistenceConflict(
                        f"workspace {workspace_id} changed or was deleted"
                    )
                self._connection.execute(
                    "delete from focused_investigations where workspace_id = ?",
                    (workspace_id,),
                )
                if event is not None:
                    self._write_study_event(event)
            except Exception:
                self._rollback()
                raise
            self._commit()
