from __future__ import annotations

import asyncio
import sqlite3
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from agora.config.settings import load_settings
from agora.core.errors import ConfigurationError
from agora.focused.importer import import_snapshots
from agora.focused.persistence import FocusedPersistence
from agora.focused.service import FocusedPanelService, SessionError
from agora.focused.study_log import (
    StudyAction,
    StudyAssignment,
    StudyOutcome,
)
from agora.focused.supabase_persistence import (
    ASSIGNMENT_TABLE,
    CREATE_STUDY_RPC,
    DELETE_STUDY_RPC,
    EVENT_TABLE,
    QUARANTINE_TABLE,
    SAVE_STUDY_RPC,
    SNAPSHOT_TABLE,
    SupabaseFocusedPersistence,
)


class FakeQuery:
    def __init__(self, client: FakeSupabaseClient, table: str) -> None:
        self.client = client
        self.table = table
        self.operation = "select"
        self.value: dict[str, Any] | None = None
        self.filters: list[tuple[str, Any]] = []
        self.greater_than: list[tuple[str, Any]] = []
        self.order_field: str | None = None
        self.limit_count: int | None = None

    def select(self, *_: Any, **__: Any) -> FakeQuery:
        self.operation = "select"
        return self

    def insert(self, value: dict[str, Any]) -> FakeQuery:
        self.operation = "insert"
        self.value = value
        return self

    def update(self, value: dict[str, Any], **_: Any) -> FakeQuery:
        self.operation = "update"
        self.value = value
        return self

    def delete(self, **_: Any) -> FakeQuery:
        self.operation = "delete"
        return self

    def upsert(self, value: dict[str, Any], **_: Any) -> FakeQuery:
        self.operation = "upsert"
        self.value = value
        return self

    def eq(self, field: str, value: Any) -> FakeQuery:
        self.filters.append((field, value))
        return self

    def gt(self, field: str, value: Any) -> FakeQuery:
        self.greater_than.append((field, value))
        return self

    def order(self, field: str, **_: Any) -> FakeQuery:
        self.order_field = field
        return self

    def limit(self, count: int) -> FakeQuery:
        self.limit_count = count
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        return all(row.get(field) == value for field, value in self.filters) and all(
            row.get(field, 0) > value for field, value in self.greater_than
        )

    def execute(self) -> SimpleNamespace:
        rows = self.client.rows.setdefault(self.table, {})
        matched = [row for row in rows.values() if self._matches(row)]
        if self.order_field is not None:
            matched.sort(key=lambda row: row[self.order_field])
        if self.limit_count is not None:
            matched = matched[: self.limit_count]
        if self.operation == "select":
            if self.client.max_select_rows is not None:
                matched = matched[: self.client.max_select_rows]
            return SimpleNamespace(data=deepcopy(matched))
        assert self.value is not None or self.operation == "delete"
        if self.operation == "insert":
            inserted = self.client.insert(self.table, self.value)
            return SimpleNamespace(data=[deepcopy(inserted)])
        if self.operation == "upsert":
            key = self.client.key(self.table, self.value)
            rows[key] = deepcopy(self.value)
            return SimpleNamespace(data=[deepcopy(rows[key])])
        if self.operation == "update":
            updated = []
            for row in matched:
                row.update(deepcopy(self.value))
                updated.append(deepcopy(row))
            return SimpleNamespace(data=updated)
        deleted = []
        for row in matched:
            key = str(row["workspace_id"])
            deleted.append(deepcopy(rows.pop(key)))
        return SimpleNamespace(data=deleted)


class FakeRpc:
    def __init__(
        self,
        client: FakeSupabaseClient,
        name: str,
        params: dict[str, Any],
    ) -> None:
        self.client = client
        self.name = name
        self.params = params

    def execute(self) -> SimpleNamespace:
        rows_before = deepcopy(self.client.rows)
        sequence_before = self.client.next_event_sequence
        try:
            workspace_id = str(self.params["p_workspace_id"])
            if self.name == CREATE_STUDY_RPC:
                self.client.insert(
                    SNAPSHOT_TABLE,
                    {
                        "workspace_id": workspace_id,
                        "revision": self.params["p_revision"],
                        "payload": self.params["p_payload"],
                    },
                )
                self.client.insert(ASSIGNMENT_TABLE, self.params["p_assignment"])
                self.client.insert(EVENT_TABLE, self.params["p_event"])
                return SimpleNamespace(data=None)

            snapshot = self.client.rows[SNAPSHOT_TABLE].get(workspace_id)
            expected_revision = self.params["p_expected_revision"]
            if snapshot is None or snapshot["revision"] != expected_revision:
                return SimpleNamespace(data=False)
            if self.name == SAVE_STUDY_RPC:
                snapshot.update(
                    {
                        "revision": self.params["p_revision"],
                        "payload": deepcopy(self.params["p_payload"]),
                    }
                )
            elif self.name == DELETE_STUDY_RPC:
                self.client.rows[SNAPSHOT_TABLE].pop(workspace_id)
            else:
                raise AssertionError(f"unknown fake RPC {self.name}")
            self.client.insert(EVENT_TABLE, self.params["p_event"])
            return SimpleNamespace(data=True)
        except Exception:
            self.client.rows = rows_before
            self.client.next_event_sequence = sequence_before
            raise


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, dict[str, Any]]] = {
            SNAPSHOT_TABLE: {},
            QUARANTINE_TABLE: {},
            ASSIGNMENT_TABLE: {},
            EVENT_TABLE: {},
        }
        self.next_event_sequence = 1
        self.max_select_rows: int | None = None

    @staticmethod
    def key(table: str, value: dict[str, Any]) -> str:
        if table == EVENT_TABLE:
            return str(value["event_id"])
        return str(value["workspace_id"])

    def insert(self, table: str, value: dict[str, Any]) -> dict[str, Any]:
        rows = self.rows.setdefault(table, {})
        row = deepcopy(value)
        if table == EVENT_TABLE:
            row["event_id"] = str(UUID(str(row["event_id"])))
        key = self.key(table, row)
        if key in rows:
            raise RuntimeError(f"duplicate row in {table}")
        if table == EVENT_TABLE:
            row["event_seq"] = self.next_event_sequence
            self.next_event_sequence += 1
        rows[key] = row
        return row

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    def rpc(self, name: str, params: dict[str, Any]) -> FakeRpc:
        return FakeRpc(self, name, params)


def persistence(client: FakeSupabaseClient) -> SupabaseFocusedPersistence:
    return SupabaseFocusedPersistence(client=client)


def test_supabase_snapshot_round_trip_and_revision_conflict() -> None:
    client = FakeSupabaseClient()
    first = FocusedPanelService(persistence=persistence(client))
    root = first.create_workspace(
        problem="A durable research problem",
        demo=True,
    ).active
    stale = FocusedPanelService(persistence=persistence(client))

    asyncio.run(first.suggest_queries(root.id))

    with pytest.raises(SessionError, match="changed in another process"):
        asyncio.run(stale.suggest_queries(root.id))

    restored = FocusedPanelService(persistence=persistence(client))
    assert restored.get(root.id).suggested_queries
    first.delete_workspace(root.workspace_id)
    with pytest.raises(SessionError, match="not found"):
        FocusedPanelService(persistence=persistence(client)).workspace_view(
            root.workspace_id
        )

    assignments = persistence(client).load_study_assignments()
    assert len(assignments) == 1
    assert assignments[0].workspace_id == root.workspace_id
    assert assignments[0].condition == "baseline"
    events = persistence(client).load_study_events()
    assert [event.action for event in events] == [
        StudyAction.WORKSPACE_CREATE,
        StudyAction.QUERIES_SUGGEST,
        StudyAction.QUERIES_SUGGEST,
        StudyAction.WORKSPACE_DELETE,
    ]
    assert [event.outcome for event in events] == [
        StudyOutcome.SUCCESS,
        StudyOutcome.SUCCESS,
        StudyOutcome.FAILURE,
        StudyOutcome.SUCCESS,
    ]



def test_supabase_assignment_loading_paginates_past_row_limit() -> None:
    client = FakeSupabaseClient()
    client.max_select_rows = 1000
    for index in range(1001):
        assignment = StudyAssignment(
            workspace_id=f"workspace-{index:04d}",
            participant_id=f"P-{index:04d}",
            condition="baseline",
        )
        client.insert(
            ASSIGNMENT_TABLE,
            assignment.model_dump(mode="json"),
        )

    assignments = persistence(client).load_study_assignments()

    assert len(assignments) == 1001
    assert assignments[0].workspace_id == "workspace-0000"
    assert assignments[-1].workspace_id == "workspace-1000"

def test_supabase_snapshot_quarantines_malformed_rows() -> None:
    client = FakeSupabaseClient()
    service = FocusedPanelService(persistence=persistence(client))
    healthy = service.create_workspace(
        problem="A healthy workspace",
        demo=True,
    ).active
    client.rows[SNAPSHOT_TABLE]["broken"] = {
        "workspace_id": "broken",
        "revision": 0,
        "payload": {"workspace": {"id": "broken"}, "investigations": []},
    }
    legacy = deepcopy(client.rows[SNAPSHOT_TABLE][healthy.workspace_id])
    legacy["workspace_id"] = "legacy"
    legacy["payload"]["workspace"]["id"] = "legacy"
    legacy["payload"]["workspace"]["schema_version"] = 6
    for study in legacy["payload"]["investigations"]:
        study["workspace_id"] = "legacy"
    client.rows[SNAPSHOT_TABLE]["legacy"] = legacy

    restored = FocusedPanelService(persistence=persistence(client))

    assert restored.workspace_view(healthy.workspace_id).active.id == healthy.id
    assert "broken" not in client.rows[SNAPSHOT_TABLE]
    assert client.rows[QUARANTINE_TABLE]["broken"]["reason"]
    assert "legacy" not in client.rows[SNAPSHOT_TABLE]
    assert client.rows[QUARANTINE_TABLE]["legacy"]["reason"]


def test_sqlite_import_is_idempotent(tmp_path) -> None:
    sqlite_path = tmp_path / "focused.db"
    connection = sqlite3.connect(sqlite_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    source = FocusedPanelService(persistence=FocusedPersistence(connection))
    source.create_workspace(
        problem="An imported workspace",
        demo=True,
    )
    connection.close()

    target = persistence(FakeSupabaseClient())
    assert import_snapshots(
        sqlite_path,
        dry_run=False,
        target_persistence=target,
    ) == (1, 0)
    assert import_snapshots(
        sqlite_path,
        dry_run=False,
        target_persistence=target,
    ) == (0, 1)


def test_supabase_backend_requires_both_credentials(monkeypatch) -> None:
    monkeypatch.setenv("AGORA_PERSISTENCE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "")

    with pytest.raises(ConfigurationError, match="requires SUPABASE_URL"):
        load_settings()


def test_supabase_backend_requires_proxy_token(monkeypatch) -> None:
    monkeypatch.setenv("AGORA_PERSISTENCE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret")
    monkeypatch.setenv("AGORA_PROXY_TOKEN", "")

    with pytest.raises(ConfigurationError, match="requires AGORA_PROXY_TOKEN"):
        load_settings()
