from hashlib import sha256
from typing import Any

from agora.config.settings import OpenAISettings
from agora.core.errors import ProviderError
from agora.llm.providers.base import (
    LLMProvider,
    LLMResponse,
    Message,
    ProviderName,
    StructuredResponse,
    T,
    truncation_error,
)
from agora.schemas.base import TokenUsage


def _prompt_cache_key(
    messages: list[Message],
    cache_namespace: str | None,
) -> str | None:
    material = cache_namespace
    if material is None:
        material = next(
            (
                message["content"]
                for message in messages
                if message["role"] == "system"
            ),
            "",
        )
    if not material:
        return None
    return sha256(material.encode()).hexdigest()[:40]


def _request(
    *,
    model: str,
    messages: list[Message],
    temperature: float | None,
    max_output_tokens: int | None,
    reasoning_effort: str | None,
    cache_namespace: str | None,
) -> dict[str, Any]:
    request: dict[str, Any] = {"model": model, "input": list(messages)}

    if temperature is not None:
        request["temperature"] = temperature
    if max_output_tokens is not None:
        request["max_output_tokens"] = max_output_tokens
    if reasoning_effort is not None:
        request["reasoning"] = {"effort": reasoning_effort}

    key = _prompt_cache_key(messages, cache_namespace)
    if key is not None:
        request["prompt_cache_key"] = key

    return request


def _usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)

    return TokenUsage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        reasoning_tokens=getattr(output_details, "reasoning_tokens", 0) or 0,
        cached_tokens=getattr(input_details, "cached_tokens", 0) or 0,
        cache_write_tokens=getattr(input_details, "cache_write_tokens", 0) or 0,
    )


def _truncated(response: Any) -> bool:
    if getattr(response, "status", None) != "incomplete":
        return False
    details = getattr(response, "incomplete_details", None)
    return getattr(details, "reason", None) == "max_output_tokens"


def _text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if not text:
        raise ProviderError("OpenAI returned an empty response")
    return text


class OpenAIProvider(LLMProvider):
    name = ProviderName.OPENAI

    def __init__(self, settings: OpenAISettings) -> None:
        if not settings.api_key:
            raise ProviderError("OPENAI_API_KEY is required")

        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ProviderError(
                "the openai package is required for OpenAIProvider"
            ) from exc

        self._client = AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            max_retries=settings.max_retries,
            timeout=settings.timeout,
        )

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
        request = _request(
            model=model,
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            cache_namespace=cache_namespace,
        )

        try:
            response = await self._client.responses.create(**request)
        except Exception as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc

        usage = _usage(response)

        if _truncated(response):
            raise truncation_error(self.name, usage, max_output_tokens)

        return LLMResponse(
            content=_text(response),
            usage=usage,
            model=model,
            provider=self.name,
        )

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
        request = _request(
            model=model,
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            cache_namespace=cache_namespace,
        )

        try:
            response = await self._client.responses.parse(
                text_format=schema,
                **request,
            )
        except Exception as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc

        usage = _usage(response)

        if _truncated(response):
            raise truncation_error(self.name, usage, max_output_tokens)

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise ProviderError(f"OpenAI returned no parsed {schema.__name__}")
        if not isinstance(parsed, schema):
            parsed = schema.model_validate(parsed)

        return StructuredResponse(
            parsed=parsed,
            usage=usage,
            model=model,
            provider=self.name,
        )
