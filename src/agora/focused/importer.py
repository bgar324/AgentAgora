"""Idempotent import of focused SQLite snapshots into another persistence store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agora.config.settings import load_settings
from agora.focused.models import SessionState, WorkspaceState
from agora.focused.persistence import FocusedPersistence, WorkspacePersistence
from agora.focused.supabase_persistence import SupabaseFocusedPersistence


def _by_workspace(
    workspaces: list[WorkspaceState],
    investigations: list[SessionState],
) -> dict[str, tuple[WorkspaceState, list[SessionState]]]:
    states = {investigation.id: investigation for investigation in investigations}
    return {
        workspace.id: (
            workspace,
            [
                states[investigation_id]
                for investigation_id in workspace.investigation_ids
            ],
        )
        for workspace in workspaces
    }


def import_snapshots(
    sqlite_path: Path,
    *,
    dry_run: bool,
    target_persistence: WorkspacePersistence | None = None,
) -> tuple[int, int]:
    if not sqlite_path.is_file():
        raise FileNotFoundError(sqlite_path)

    connection = sqlite3.connect(sqlite_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        source = _by_workspace(*FocusedPersistence(connection).load())
    finally:
        connection.close()

    if target_persistence is None:
        settings = load_settings()
        if not settings.supabase.url or not settings.supabase.secret_key:
            raise RuntimeError(
                "Set SUPABASE_URL and SUPABASE_SECRET_KEY before importing"
            )
        target_persistence = SupabaseFocusedPersistence(
            settings.supabase.url,
            settings.supabase.secret_key,
        )
    target = _by_workspace(*target_persistence.load())

    created = 0
    skipped = 0
    for workspace_id, snapshot in source.items():
        existing = target.get(workspace_id)
        if existing is not None:
            if snapshot != existing:
                raise RuntimeError(
                    f"Supabase workspace {workspace_id} exists with different state"
                )
            skipped += 1
            continue
        if not dry_run:
            target_persistence.create(*snapshot)
        created += 1
    return created, skipped
