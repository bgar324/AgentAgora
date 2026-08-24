#!/usr/bin/env python3

from __future__ import annotations

import ast
from pathlib import Path

AGENTS_PATH = Path("src/agora/focused/agents.py")


def main() -> None:
    tree = ast.parse(AGENTS_PATH.read_text(encoding="utf-8"), filename=str(AGENTS_PATH))
    missing: list[int] = []
    invalid: list[int] = []
    calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "_structured":
            continue
        calls += 1
        task = next((item.value for item in node.keywords if item.arg == "task"), None)
        if task is None:
            missing.append(node.lineno)
            continue
        if not (
            isinstance(task, ast.Attribute)
            and isinstance(task.value, ast.Name)
            and task.value.id == "FocusedTask"
        ):
            invalid.append(node.lineno)
    if missing:
        raise SystemExit(f"_structured calls missing task= at lines {missing}")
    if invalid:
        raise SystemExit(f"_structured calls use invalid task routes at lines {invalid}")
    if calls == 0:
        raise SystemExit("no _structured calls found")
    print(f"verified {calls} focused model call routes")


if __name__ == "__main__":
    main()
