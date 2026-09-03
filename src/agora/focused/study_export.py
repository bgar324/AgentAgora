"""Operator-only NDJSON export of focused study assignments and events."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

from agora.config.settings import load_settings
from agora.focused.persistence import FocusedPersistence, WorkspacePersistence
from agora.focused.supabase_persistence import SupabaseFocusedPersistence


def iter_study_export_records(
    persistence: WorkspacePersistence,
    *,
    page_size: int = 1000,
) -> Iterator[dict[str, object]]:
    for assignment in persistence.load_study_assignments():
        yield {
            "record_type": "assignment",
            **assignment.model_dump(mode="json"),
        }

    after_sequence = 0
    while True:
        events = persistence.load_study_events(
            after_sequence=after_sequence,
            limit=page_size,
        )
        for event in events:
            yield {
                "record_type": "event",
                **event.model_dump(mode="json"),
            }
        if len(events) < page_size:
            return
        sequence = events[-1].event_seq
        if sequence is None:
            raise RuntimeError("persisted study event is missing its sequence")
        after_sequence = sequence


def export_study_log(
    persistence: WorkspacePersistence,
    output: TextIO,
) -> int:
    count = 0
    for record in iter_study_export_records(persistence):
        output.write(json.dumps(record, separators=(",", ":"), sort_keys=True))
        output.write("\n")
        count += 1
    return count


def _paths_alias(source: Path, output: Path) -> bool:
    if source.resolve() == output.resolve():
        return True
    try:
        return os.path.samefile(source, output)
    except FileNotFoundError:
        return False


def export_study_log_to_path(
    persistence: WorkspacePersistence,
    output_path: Path,
    *,
    sqlite_source: Path | None = None,
) -> int:
    if sqlite_source is not None and _paths_alias(sqlite_source, output_path):
        raise ValueError("study export output cannot replace its SQLite source")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            os.fchmod(temporary.fileno(), 0o600)
            count = export_study_log(persistence, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, output_path)
        os.chmod(output_path, 0o600)
        temporary_path = None
        return count
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _sqlite_persistence(path: Path) -> tuple[FocusedPersistence, sqlite3.Connection]:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return FocusedPersistence(connection), connection


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export pseudonymous focused-study assignments and interaction events. "
            "Run only from a trusted operator environment."
        )
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        help="Read this SQLite database instead of the configured persistence backend",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write NDJSON to this owner-readable file instead of stdout",
    )
    args = parser.parse_args()

    connection: sqlite3.Connection | None = None
    sqlite_source: Path | None = None
    if args.sqlite is not None:
        sqlite_source = args.sqlite
        persistence, connection = _sqlite_persistence(sqlite_source)
    else:
        settings = load_settings()
        if settings.server.persistence_backend == "supabase":
            persistence = SupabaseFocusedPersistence(
                settings.supabase.url,
                settings.supabase.secret_key,
            )
        else:
            sqlite_source = settings.server.data_dir / "agora.db"
            persistence, connection = _sqlite_persistence(sqlite_source)

    try:
        if args.output is None:
            count = export_study_log(persistence, sys.stdout)
        else:
            count = export_study_log_to_path(
                persistence,
                args.output,
                sqlite_source=sqlite_source,
            )
    finally:
        if connection is not None:
            connection.close()

    print(f"Exported {count} study record(s).", file=sys.stderr)


if __name__ == "__main__":
    main()
