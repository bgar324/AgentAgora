from __future__ import annotations

import asyncio
import sqlite3
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from postgrest.exceptions import APIError

from agora.config.settings import load_settings
from agora.core.errors import ConfigurationError
from agora.focused.importer import import_snapshots
from agora.focused.models import DeliberationRound, HypothesisDev
from agora.focused.persistence import FocusedPersistence
from agora.focused.service import FocusedPanelService, SessionError
from agora.focused.supabase_persistence import (
    ARCHIVE_TABLE,
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
            ARCHIVE_TABLE: {},
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
        research_questions=["original"],
        demo=True,
    ).active
    stale = FocusedPanelService(persistence=persistence(client))

    first.update_brief(
        root.id,
        problem="A durable research problem",
        research_questions=["newer"],
    )

    with pytest.raises(SessionError, match="changed in another process"):
        stale.update_brief(
            root.id,
            problem="A durable research problem",
            research_questions=["stale"],
        )

    restored = FocusedPanelService(persistence=persistence(client))
    assert restored.get(root.id).research_questions == ["newer"]
    first.delete_workspace(root.workspace_id)
    with pytest.raises(SessionError, match="not found"):
        FocusedPanelService(persistence=persistence(client)).workspace_view(
            root.workspace_id
        )


def test_supabase_load_archives_and_migrates_v5_hypotheses(
    legacy_v5_deliberation,
) -> None:
    async def go() -> None:
        client = FakeSupabaseClient()
        service = FocusedPanelService(persistence=persistence(client))
        root = service.create_workspace(
            problem="A legacy workspace",
            research_questions=[],
            demo=True,
        ).active
        state = await service.create_deliberation(root.id)
        deliberation = state.deliberations[0]
        candidate = HypothesisDev(hypothesis="A durable legacy candidate")
        deliberation.rounds.append(
            DeliberationRound(
                n=1,
                lead_iid=1,
                facets=["scope"],
                completed=True,
            )
        )
        deliberation.hypothesis = candidate
        deliberation.hypothesis_confirmed = False
        await service.confirm_deliberation_hypothesis(
            root.id,
            deliberation.id,
            candidate,
        )
        await service.save_deliberation_hypothesis(root.id, deliberation.id)

        snapshot = client.rows[SNAPSHOT_TABLE][root.workspace_id]
        legacy_payload = deepcopy(snapshot["payload"])
        legacy_payload["workspace"]["schema_version"] = 5
        version = legacy_payload["workspace"]["hypothesis_versions"][0]
        version["steps"] = {
            "problem": "legacy problem",
            "previous_work": "legacy previous work",
            "reasoning": "legacy reasoning",
            "hypothesis": candidate.hypothesis,
        }
        version["step_sources"] = {
            "problem": "H1",
            "previous_work": "H1",
            "reasoning": "H1",
            "hypothesis": "H1",
        }
        legacy_payload["investigations"][0]["deliberations"] = [
            legacy_v5_deliberation("persp-legacy")
        ]
        snapshot["payload"] = deepcopy(legacy_payload)

        restored = FocusedPanelService(persistence=persistence(client))
        view = restored.workspace_view(root.workspace_id)
        assert view.workspace.schema_version == 6
        assert view.workspace.hypothesis_versions[0].steps == candidate
        assert view.workspace.hypothesis_versions[0].step_sources == {
            "hypothesis": "H1"
        }
        migrated = view.active.deliberations[0]
        migrated_round = migrated.rounds[0]
        assert migrated_round.verdict is not None
        assert migrated_round.verdict.facets == ["scope", "significance"]
        assert [turn.kind.value for turn in migrated_round.turns] == [
            "open",
            "reply",
        ]
        assert migrated_round.turns[1].relation == "reply"
        assert migrated_round.resolution is not None
        assert migrated_round.resolution.consensus_points[0].facets == ["scope"]
        assert migrated.completion_history[0].rounds[0].verdict is not None
        archived = client.rows[ARCHIVE_TABLE][root.workspace_id]
        assert archived["schema_version"] == 5
        assert archived["payload"] == legacy_payload

        FocusedPanelService(persistence=persistence(client))
        assert len(client.rows[ARCHIVE_TABLE]) == 1

    asyncio.run(go())


def test_missing_archive_table_skips_row_without_mutation(
    legacy_v5_deliberation,
) -> None:
    async def go() -> None:
        client = FakeSupabaseClient()
        service = FocusedPanelService(persistence=persistence(client))
        root = service.create_workspace(
            problem="A legacy workspace",
            research_questions=[],
            demo=True,
        ).active
        snapshot = client.rows[SNAPSHOT_TABLE][root.workspace_id]
        legacy_payload = deepcopy(snapshot["payload"])
        legacy_payload["workspace"]["schema_version"] = 5
        legacy_payload["investigations"][0]["deliberations"] = [
            legacy_v5_deliberation("persp-legacy")
        ]
        snapshot["payload"] = deepcopy(legacy_payload)

        class MissingArchiveClient:
            """The archives DDL has not been applied to the project."""

            def table(self, name: str) -> Any:
                if name == ARCHIVE_TABLE:
                    raise_query = FakeQuery(client, name)
                    raise_query.execute = lambda: (_ for _ in ()).throw(
                        APIError(
                            {
                                "code": "PGRST205",
                                "message": (
                                    "Could not find the table "
                                    "'public.focused_workspace_archives'"
                                ),
                            }
                        )
                    )
                    return raise_query
                return client.table(name)

        degraded = SupabaseFocusedPersistence(client=MissingArchiveClient())
        workspaces, investigations = degraded.load()
        # The legacy workspace is hidden this boot, never crashed on,
        # never quarantined, and its stored snapshot is untouched.
        assert workspaces == []
        assert investigations == []
        assert client.rows[QUARANTINE_TABLE] == {}
        assert client.rows[SNAPSHOT_TABLE][root.workspace_id]["payload"] == (
            legacy_payload
        )

        # Once the DDL exists, the same stored row migrates normally.
        restored = FocusedPanelService(persistence=persistence(client))
        view = restored.workspace_view(root.workspace_id)
        assert view.workspace.schema_version == 6
        assert len(client.rows[ARCHIVE_TABLE]) == 1

    asyncio.run(go())


def test_supabase_snapshot_quarantines_malformed_rows() -> None:
    client = FakeSupabaseClient()
    service = FocusedPanelService(persistence=persistence(client))
    healthy = service.create_workspace(
        problem="A healthy workspace",
        research_questions=[],
        demo=True,
    ).active
    client.rows[SNAPSHOT_TABLE]["broken"] = {
        "workspace_id": "broken",
        "revision": 0,
        "payload": {"workspace": {"id": "broken"}, "investigations": []},
    }

    restored = FocusedPanelService(persistence=persistence(client))

    assert restored.workspace_view(healthy.workspace_id).active.id == healthy.id
    assert "broken" not in client.rows[SNAPSHOT_TABLE]
    assert client.rows[QUARANTINE_TABLE]["broken"]["reason"]


def test_sqlite_import_is_idempotent(tmp_path) -> None:
    sqlite_path = tmp_path / "focused.db"
    connection = sqlite3.connect(sqlite_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    source = FocusedPanelService(persistence=FocusedPersistence(connection))
    source.create_workspace(
        problem="An imported workspace",
        research_questions=[],
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
