#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel
from run_retrieval_evals import dspy_lm

from agora.config.settings import load_settings
from agora.evaluation.metering import MeteredLLMProvider, dspy_model_usage
from agora.focused.provider import FocusedProvider
from agora.focused.routing import FocusedTask
from agora.llm.providers.openai import OpenAIProvider


class Acknowledgment(BaseModel):
    ok: bool


async def main() -> None:
    settings = load_settings()
    if not settings.openai.api_key:
        raise SystemExit("OPENAI_API_KEY is required")
    long_input = " ".join(
        f"cache-isolation-token-{index}" for index in range(1_500)
    )
    messages = [
        {"role": "system", "content": "Return {\"ok\": true}."},
        {"role": "user", "content": long_input},
    ]

    openai = OpenAIProvider(settings.openai)
    focused_meter = MeteredLLMProvider(openai)
    focused = FocusedProvider(
        llm=focused_meter,
        models=settings.focused_models,
        disable_prompt_cache=True,
    )
    for _ in range(2):
        await focused.generate_structured(
            task=FocusedTask.suggest_queries,
            messages=messages,
            schema=Acknowledgment,
            max_output_tokens=500,
        )
    focused_usage = focused_meter.snapshot(reset=True)

    judge_meter = MeteredLLMProvider(openai)
    for _ in range(2):
        await judge_meter.generate_structured(
            model=settings.focused_models.evaluation.model,
            messages=messages,
            schema=Acknowledgment,
            max_output_tokens=1_000,
            reasoning_effort="high",
            cache_namespace="",
        )
    judge_usage = judge_meter.snapshot(reset=True)

    kat_lm = dspy_lm(
        settings.focused_models.query.model,
        api_key=settings.openai.api_key,
        max_tokens=500,
    )
    history_start = len(kat_lm.history)
    for _ in range(2):
        await kat_lm.acall(messages=messages)
    kat_usage = dspy_model_usage([(kat_lm, history_start)])

    paths = {
        "focused": focused_usage,
        "judge": judge_usage,
        "kat": kat_usage,
    }
    for path, usage in paths.items():
        if not usage or sum(item.input_tokens for item in usage) == 0:
            raise SystemExit(f"{path} recorded no live input tokens")
        if any(item.cached_calls for item in usage):
            raise SystemExit(f"{path} replayed a cached response")
        if any(item.cached_input_tokens for item in usage):
            raise SystemExit(f"{path} used cached prompt input tokens")

    print(
        json.dumps(
            {
                path: [item.model_dump(mode="json") for item in usage]
                for path, usage in paths.items()
            },
            indent=2,
        )
    )
    await openai._client.close()


if __name__ == "__main__":
    asyncio.run(main())
