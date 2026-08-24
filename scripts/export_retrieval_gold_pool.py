#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from agora.evaluation.retrieval import PipelineRun, RetrievalCase, load_cases, load_runs


def _order_key(case_id: str, paper_id: str) -> bytes:
    return hashlib.sha256(f"fair-v2:{case_id}:{paper_id}".encode()).digest()


def build_pool(
    cases: list[RetrievalCase],
    runs: list[PipelineRun],
    *,
    depth_per_run: int,
) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    if depth_per_run < 1:
        raise ValueError("depth_per_run must be positive")
    case_by_id = {case.id: case for case in cases}
    pooled: dict[tuple[str, str], Any] = {}
    for run in runs:
        if run.case_id not in case_by_id:
            raise ValueError(f"run references unknown case: {run.case_id}")
        paper_by_id = {paper.id: paper for paper in run.papers}
        delivered = sorted(
            {
                paper_id
                for cluster in run.clusters
                for paper_id in cluster.paper_ids
            },
            key=lambda paper_id: _order_key(run.case_id, paper_id),
        )
        tail = sorted(
            run.unassigned_paper_ids,
            key=lambda paper_id: _order_key(run.case_id, paper_id),
        )
        selected = list(dict.fromkeys([*delivered, *tail]))[:depth_per_run]
        if len(selected) != depth_per_run:
            raise ValueError(
                f"{run.pipeline} {run.case_id} repeat {run.repeat} has "
                f"{len(selected)} papers; gold depth requires {depth_per_run}"
            )
        for paper_id in selected:
            if paper_id in paper_by_id:
                pooled.setdefault((run.case_id, paper_id), paper_by_id[paper_id])
    rows: list[dict[str, str]] = []
    mapping: dict[str, dict[str, str]] = {}
    for case_id, paper_id in sorted(
        pooled,
        key=lambda item: _order_key(*item),
    ):
        case = case_by_id[case_id]
        paper = pooled[(case_id, paper_id)]
        alias = f"G{hashlib.sha256(f'{case_id}:{paper_id}'.encode()).hexdigest()[:14]}"
        mapping[alias] = {"case_id": case_id, "paper_id": paper_id}
        rows.append(
            {
                "case_id": case_id,
                "problem": case.problem,
                "research_questions": " | ".join(case.research_questions),
                "alias": alias,
                "title": paper.title,
                "abstract": paper.abstract,
                "relevance_0_to_4": "",
                "notes": "",
            }
        )
    return rows, mapping


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export a pipeline-blind TREC-style pool for human relevance labels. "
            "Use 0=off-topic, 1=background, 2=related, 3=addresses, 4=answers."
        )
    )
    parser.add_argument("--cases", default="evals/retrieval_cases.json")
    parser.add_argument("--results", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--depth-per-run", type=int, default=60)
    args = parser.parse_args()

    rows, mapping = build_pool(
        load_cases(args.cases),
        load_runs(args.results),
        depth_per_run=args.depth_per_run,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    map_path = output.with_suffix(".map.json")
    map_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} blinded rows to {output}")
    print(f"wrote private alias map to {map_path}")


if __name__ == "__main__":
    main()
