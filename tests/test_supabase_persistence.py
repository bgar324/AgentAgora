from __future__ import annotations

import asyncio
import sqlite3
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from agora.config.settings import load_settings
from agora.core.errors import ConfigurationError
from agora.focused.importer import import_snapshots
from agora.focused.persistence import FocusedPersistence
from agora.focused.service import FocusedPanelService, SessionError
from agora.focused.supabase_persistence import (
    QUARANTINE_TABLE,
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

    def _matches(self, row: dict[str, Any]) -> bool:
        return all(row.get(field) == value for field, value in self.filters)

    def execute(self) -> SimpleNamespace:
        rows = self.client.rows.setdefault(self.table, {})
        matched = [row for row in rows.values() if self._matches(row)]
        if self.operation == "select":
            return SimpleNamespace(data=deepcopy(matched))
        assert self.value is not None or self.operation == "delete"
        if self.operation == "insert":
            key = str(self.value["workspace_id"])
            if key in rows:
                raise RuntimeError("duplicate workspace")
            rows[key] = deepcopy(self.value)
            return SimpleNamespace(data=[deepcopy(rows[key])])
        if self.operation == "upsert":
            key = str(self.value["workspace_id"])
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


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, dict[str, Any]]] = {
            SNAPSHOT_TABLE: {},
            QUARANTINE_TABLE: {},
        }

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


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
