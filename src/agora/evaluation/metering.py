from __future__ import annotations

from typing import Any

from agora.evaluation.retrieval import ModelUsage
from agora.llm.providers.base import LLMProvider, LLMResponse, StructuredResponse
from agora.schemas.base import TokenUsage


class MeteredLLMProvider(LLMProvider):
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self.name = provider.name
        self._usage: dict[str, ModelUsage] = {}

    def _record(self, model: str, usage: TokenUsage) -> None:
        current = self._usage.setdefault(model, ModelUsage(model=model))
        current.calls += 1
        current.input_tokens += usage.input_tokens
        current.cached_input_tokens += usage.cached_tokens
        current.output_tokens += usage.output_tokens
        current.reasoning_tokens += usage.reasoning_tokens

    async def generate(self, **kwargs: Any) -> LLMResponse:
        response = await self._provider.generate(**kwargs)
        self._record(response.model, response.usage)
        return response

    async def generate_structured(self, **kwargs: Any) -> StructuredResponse:
        response = await self._provider.generate_structured(**kwargs)
        self._record(response.model, response.usage)
        return response

    def snapshot(self, *, reset: bool = False) -> list[ModelUsage]:
        result = [item.model_copy(deep=True) for item in self._usage.values()]
        if reset:
            self._usage.clear()
        return result


def dspy_model_usage(lms: list[tuple[Any, int]]) -> list[ModelUsage]:
    totals: dict[str, ModelUsage] = {}
    for lm, start in lms:
        for entry in getattr(lm, "history", [])[start:]:
            if isinstance(entry, dict):
                response = entry.get("response")
                model = str(entry.get("model") or getattr(lm, "model", "unknown"))
                usage = entry.get("usage") or {}
                cost = entry.get("cost")
                cache_hit = bool(
                    entry.get("cache_hit") or getattr(response, "cache_hit", False)
                )
            elif hasattr(entry, "response"):
                response = entry.response
                model = str(getattr(entry, "model", getattr(lm, "model", "unknown")))
                usage = getattr(response, "usage", {}) or {}
                cost = getattr(response, "cost", None)
                cache_hit = bool(getattr(response, "cache_hit", False))
            else:
                raise TypeError(
                    f"unsupported DSPy history entry: {type(entry).__name__}"
                )
            if not isinstance(usage, dict):
                usage = getattr(usage, "model_dump", dict)()
            current = totals.setdefault(model, ModelUsage(model=model))
            if cache_hit or not usage:
                current.cached_calls += 1
                continue
            current.calls += 1
            current.input_tokens += int(
                usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
            )
            prompt_details = usage.get("prompt_tokens_details") or {}
            if isinstance(prompt_details, dict):
                current.cached_input_tokens += int(
                    prompt_details.get("cached_tokens", 0) or 0
                )
            current.output_tokens += int(
                usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
            )
            current.reasoning_tokens += int(usage.get("reasoning_tokens", 0) or 0)
            if isinstance(cost, int | float):
                current.cost_usd = (current.cost_usd or 0.0) + float(cost)
    return list(totals.values())
