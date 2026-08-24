#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agora.evaluation.retrieval import load_cases, load_runs, score_runs


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Score professor and Kat retrieval runs against one fixed case set."
    )
    value.add_argument("--cases", required=True, help="JSON file of RetrievalCase rows")
    value.add_argument(
        "--results",
        required=True,
        nargs="+",
        help="One or more JSON files containing PipelineRun rows",
    )
    value.add_argument("--output", required=True, help="Comparison JSON destination")
    return value


def main() -> None:
    args = parser().parse_args()
    cases = load_cases(args.cases)
    runs = load_runs(args.results)
    expected_cases = {case.id for case in cases}
    run_case_ids = {run.case_id for run in runs}
    unknown = sorted(run_case_ids - expected_cases)
    if unknown:
        raise SystemExit(f"results reference unknown cases: {', '.join(unknown)}")
    comparison = score_runs(
        [case for case in cases if case.id in run_case_ids],
        runs,
    )
    comparison.write_json(args.output)
    print(
        json.dumps(
            [summary.model_dump(mode="json") for summary in comparison.summaries],
            indent=2,
        )
    )
    print(f"wrote {Path(args.output)}")


if __name__ == "__main__":
    main()
