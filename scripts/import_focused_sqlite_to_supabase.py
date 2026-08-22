"""Import focused workspace snapshots from SQLite into configured Supabase."""

from __future__ import annotations

import argparse
from pathlib import Path

from agora.focused.importer import import_snapshots


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=Path("artifacts/agora.db"),
        help="SQLite database to import",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and compare snapshots without writing",
    )
    args = parser.parse_args()
    created, skipped = import_snapshots(args.sqlite, dry_run=args.dry_run)
    action = "would create" if args.dry_run else "created"
    print(f"{action} {created} workspace(s); skipped {skipped} unchanged workspace(s)")


if __name__ == "__main__":
    main()
