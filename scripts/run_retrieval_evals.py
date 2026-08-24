#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from agora.client.s2 import SemanticScholarClient
from agora.config.settings import load_settings
from agora.evaluation.judge import RUBRIC_VERSION, BlindedSolJudge
from agora.evaluation.metering import MeteredLLMProvider
from agora.evaluation.retrieval import (
    evaluate_pipelines,
    load_cases,
    load_runs,
    score_runs,
)
from agora.focused.provider import FocusedProvider
from agora.focused.retrieval import FocusedSemanticScholar
from agora.llm.providers.openai import OpenAIProvider


def dspy_lm(model: str, *, api_key: str, max_tokens: int) -> Any:
    import dspy

    return dspy.LM(
        f"openai/{model}",
        api_key=api_key,
        cache=False,
        prompt_cache_options={"mode": "explicit"},
        max_tokens=max_tokens,
    )

def assert_cold_runs(runs: list[Any]) -> None:
    pipeline_scopes = [run.telemetry.cache_scope for run in runs]
    if not all(pipeline_scopes) or len(set(pipeline_scopes)) != len(pipeline_scopes):
        raise SystemExit("pipeline prompt-cache scopes were reused")
    judgment_scopes: dict[tuple[str, int], set[str]] = {}
    for run in runs:
        if run.judgment is not None:
            judgment_scopes.setdefault((run.case_id, run.repeat), set()).add(
                run.judgment.cache_scope
            )
    if (
        any(
            len(scopes) != 1 or not next(iter(scopes))
            for scopes in judgment_scopes.values()
        )
        or len({next(iter(scopes)) for scopes in judgment_scopes.values()})
        != len(judgment_scopes)
    ):
        raise SystemExit("judge prompt-cache scopes were reused")
    for run in runs:
        if run.telemetry.cache_mode != "off":
            raise SystemExit(f"{run.pipeline} did not run with caches off")
        if any(usage.cached_calls for usage in run.telemetry.model_usage):
            raise SystemExit(f"{run.pipeline} replayed a cached model response")
        if any(
            usage.cached_input_tokens for usage in run.telemetry.model_usage
        ):
            raise SystemExit(f"{run.pipeline} used cached prompt input tokens")
        if not run.telemetry.model_usage or sum(
            usage.input_tokens for usage in run.telemetry.model_usage
        ) == 0:
            raise SystemExit(f"{run.pipeline} recorded no live model input tokens")
        if run.judgment is None or not run.judgment.model_usage:
            raise SystemExit("the blinded judge recorded no model usage")
        if any(usage.cached_calls for usage in run.judgment.model_usage):
            raise SystemExit("the blinded judge replayed a cached model response")
        if any(
            usage.cached_input_tokens for usage in run.judgment.model_usage
        ):
            raise SystemExit("the blinded judge used cached prompt input tokens")
        if sum(usage.input_tokens for usage in run.judgment.model_usage) == 0:
            raise SystemExit("the blinded judge recorded no live input tokens")


async def run(args) -> None:
    if args.perspectives != 3:
        raise SystemExit("decision-grade evaluation requires exactly 3 Perspectives")
    settings = load_settings()
    if not settings.openai.api_key:
        raise SystemExit("OPENAI_API_KEY is required for live retrieval evaluation")
    if not settings.semantic_scholar.api_key:
        raise SystemExit(
            "SEMANTIC_SCHOLAR_API_KEY is required for live retrieval evaluation"
        )
    settings.semantic_scholar.min_request_interval = max(
        settings.semantic_scholar.min_request_interval,
        args.s2_request_interval,
    )
    settings.semantic_scholar.max_retries = max(
        settings.semantic_scholar.max_retries,
        8,
    )
    settings.semantic_scholar.retry_threshold_s = max(
        settings.semantic_scholar.retry_threshold_s,
        300.0,
    )
    settings.semantic_scholar.cache_dir = None
    from agora.evaluation.kat import KatRetrievalPipeline
    from agora.evaluation.professor import ProfessorRetrievalPipeline


    openai = OpenAIProvider(settings.openai)
    judge_openai = MeteredLLMProvider(openai)
    metered_openai = MeteredLLMProvider(openai)
    focused = FocusedProvider(
        llm=metered_openai,
        models=settings.focused_models,
        disable_prompt_cache=True,
    )
    s2 = SemanticScholarClient(settings.semantic_scholar)
    professor = ProfessorRetrievalPipeline(
        provider=focused,
        retrieval=FocusedSemanticScholar(s2),
        meter=metered_openai,
        perspectives=args.perspectives,
    )
    kat = KatRetrievalPipeline(
        client=s2,
        query_lm=dspy_lm(
            settings.focused_models.query.model,
            api_key=settings.openai.api_key,
            max_tokens=settings.focused_models.query.max_tokens,
        ),
        reasoning_lm=dspy_lm(
            settings.focused_models.reasoning.model,
            api_key=settings.openai.api_key,
            max_tokens=settings.focused_models.reasoning.max_tokens,
        ),
        perspectives=args.perspectives,
    )
    judge = BlindedSolJudge(
        judge_openai,
        model=settings.focused_models.evaluation.model,
        disable_prompt_cache=True,
    )
    all_cases = load_cases(args.cases)
    cases = all_cases
    if args.case:
        cases = [case for case in all_cases if case.id in set(args.case)]
        if not cases:
            raise SystemExit("No requested evaluation case was found")
    output_path = Path(args.output)
    raw_output_path = output_path.with_suffix(".raw.json")
    prior_output_path = raw_output_path
    if args.append and not raw_output_path.exists():
        raise SystemExit("--append requires the embedding-complete .raw.json sidecar")
    if (
        args.repeat_start > 1
        and (raw_output_path.exists() or output_path.exists())
        and not args.append
    ):
        raise SystemExit("Use --append or a new output path for later repeats")
    try:
        comparison = await evaluate_pipelines(
            cases,
            [professor, kat],
            judge=judge,
            repeats=args.repeats,
            repeat_start=args.repeat_start,
            cache_mode="off",
        )
        assert_cold_runs(comparison.runs)
        if args.append:
            existing = load_runs([prior_output_path])
            if any(
                run.telemetry.cache_mode != "off"
                or run.judgment is None
                or run.judgment.rubric_version != RUBRIC_VERSION
                for run in existing
            ):
                raise SystemExit(
                    "Cannot append runs from a different cache or judging protocol"
                )
            combined = [*existing, *comparison.runs]
            keys = [(run.pipeline, run.case_id, run.repeat) for run in combined]
            if len(set(keys)) != len(keys):
                raise SystemExit("Output already contains one of the requested runs")
            assert_cold_runs(combined)
            included = {run.case_id for run in combined}
            comparison = score_runs(
                [case for case in all_cases if case.id in included],
                combined,
            )
        comparison.write_json(raw_output_path, include_embeddings=True)
        comparison.write_json(output_path)
    finally:
        await focused.close()
        await s2.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run blinded professor-versus-Kat retrieval evaluations serially."
    )
    parser.add_argument("--cases", default="evals/retrieval_cases.json")
    parser.add_argument("--case", action="append")
    parser.add_argument("--output", default="evals/results/retrieval_comparison.json")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--repeat-start", type=int, default=1)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--perspectives", type=int, default=3)
    parser.add_argument("--s2-request-interval", type=float, default=3.0)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
