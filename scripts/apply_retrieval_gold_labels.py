#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply completed 0-4 human relevance labels to retrieval cases."
    )
    parser.add_argument("--cases", default="evals/retrieval_cases.json")
    parser.add_argument("--labels", required=True)
    parser.add_argument("--map", dest="map_path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--relevant-at", type=int, default=3)
    args = parser.parse_args()
    if not 0 <= args.relevant_at <= 4:
        raise SystemExit("--relevant-at must be between 0 and 4")

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    mapping = json.loads(Path(args.map_path).read_text(encoding="utf-8"))
    labels: dict[str, int] = {}
    with Path(args.labels).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            alias = (row.get("alias") or "").strip()
            raw = (row.get("relevance_0_to_4") or "").strip()
            if not raw:
                continue
            if alias not in mapping:
                raise SystemExit(f"unknown blinded alias: {alias}")
            if alias in labels:
                raise SystemExit(f"duplicate blinded alias: {alias}")
            try:
                value = int(raw)
            except ValueError as exc:
                raise SystemExit(f"invalid relevance for {alias}: {raw}") from exc
            if not 0 <= value <= 4:
                raise SystemExit(f"relevance for {alias} must be between 0 and 4")
            labels[alias] = value

    relevant_by_case: dict[str, list[str]] = {}
    labeled_by_case: dict[str, int] = {}
    pool_by_case: dict[str, int] = {}
    for alias, reference in mapping.items():
        case_id = reference["case_id"]
        pool_by_case[case_id] = pool_by_case.get(case_id, 0) + 1
        if alias not in labels:
            continue
        labeled_by_case[case_id] = labeled_by_case.get(case_id, 0) + 1
        if labels[alias] >= args.relevant_at:
            relevant_by_case.setdefault(case_id, []).append(reference["paper_id"])

    incomplete = [
        case_id
        for case_id, pool_size in pool_by_case.items()
        if labeled_by_case.get(case_id, 0) != pool_size
    ]
    if incomplete:
        details = ", ".join(
            f"{case_id}={labeled_by_case.get(case_id, 0)}/{pool_by_case[case_id]}"
            for case_id in sorted(incomplete)
        )
        raise SystemExit(f"human label pool is incomplete: {details}")

    known_cases = {case["id"] for case in cases}
    if unknown := sorted(set(relevant_by_case) - known_cases):
        raise SystemExit(f"labels reference unknown cases: {', '.join(unknown)}")
    mapped_ids_by_case: dict[str, set[str]] = {}
    for reference in mapping.values():
        mapped_ids_by_case.setdefault(reference["case_id"], set()).add(
            reference["paper_id"]
        )
    for case in cases:
        if case["id"] not in mapped_ids_by_case:
            continue
        retained = set(case.get("relevant_paper_ids", [])) - mapped_ids_by_case[
            case["id"]
        ]
        retained.update(relevant_by_case.get(case["id"], []))
        case["relevant_paper_ids"] = sorted(retained)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    print(f"wrote human-grounded cases to {output}")


if __name__ == "__main__":
    main()
