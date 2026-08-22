from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Literal, TypedDict, TypeVar

from pydantic import BaseModel

from agora.core.errors import ProviderError
from agora.schemas.base import TokenUsage


class ProviderName(StrEnum):
    OPENAI = "openai"
    OPENROUTER = "openrouter"


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResponse:
    content: str
    usage: TokenUsage
    model: str
    provider: ProviderName


@dataclass
class StructuredResponse(Generic[T]):
    parsed: T
    usage: TokenUsage
    model: str
    provider: ProviderName


def truncation_error(
    provider: ProviderName,
    usage: TokenUsage,
    limit: int | None,
) -> ProviderError:
    return ProviderError(
        f"{provider.value} stopped at the output token limit "
        f"({usage.output_tokens} output, {usage.reasoning_tokens} reasoning, "
        f"limit {limit}); raise max_output_tokens or lower reasoning_effort"
    )


class LLMProvider(ABC):
    name: ProviderName

    @abstractmethod
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
        ...

    @abstractmethod
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
        ...
