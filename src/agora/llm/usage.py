from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

from agora.llm.providers.base import (
    LLMProvider,
    LLMResponse,
    Message,
    StructuredResponse,
    T,
)
from agora.schemas.base import TokenUsage

active_usage: ContextVar[TokenUsage | None] = ContextVar(
    "active_usage",
    default=None,
)


@contextmanager
def track_usage() -> Generator[TokenUsage, None, None]:
    total = TokenUsage()
    token = active_usage.set(total)
    try:
        yield total
    finally:
        active_usage.reset(token)


def record_usage(usage: TokenUsage) -> None:
    total = active_usage.get()
    if total is not None:
        total.add(usage)


class UsageProvider(LLMProvider):
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.name = provider.name

    async def generate(
        self,
        *,
        model: str,
        messages: list[Message],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
        cache_namespace: str | None = None,
    ) -> LLMResponse:
        response = await self.provider.generate(
            model=model,
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            cache_namespace=cache_namespace,
        )
        record_usage(response.usage)
        return response

    async def generate_structured(
        self,
        *,
        model: str,
        messages: list[Message],
        schema: type[T],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
        cache_namespace: str | None = None,
    ) -> StructuredResponse[T]:
        response = await self.provider.generate_structured(
            model=model,
            messages=messages,
            schema=schema,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            cache_namespace=cache_namespace,
        )
        record_usage(response.usage)
        return response
