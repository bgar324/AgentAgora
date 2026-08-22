from typing import Any

from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from agora.config.settings import OpenRouterSettings
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


def _request(
    *,
    model: str,
    messages: list[Message],
    temperature: float | None,
    max_output_tokens: int | None,
    reasoning_effort: str | None,
    schema: type[T] | None,
    settings: OpenRouterSettings,
) -> dict[str, Any]:
    provider: dict[str, Any] = {"allow_fallbacks": True}

    if settings.provider_sort:
        provider["sort"] = settings.provider_sort

    if schema is not None:
        provider["require_parameters"] = True

    extra_body: dict[str, Any] = {"provider": provider}

    if settings.models:
        extra_body["models"] = settings.models

    if reasoning_effort is not None:
        extra_body["reasoning"] = {"effort": reasoning_effort}

    request: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "extra_body": extra_body,
    }

    if temperature is not None:
        request["temperature"] = temperature

    if max_output_tokens is not None:
        request["max_tokens"] = max_output_tokens

    if schema is not None:
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "strict": True,
                "schema": to_strict_json_schema(schema),
            },
        }

    return request


def _usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()

    prompt_details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)

    return TokenUsage(
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        reasoning_tokens=int(getattr(completion_details, "reasoning_tokens", 0) or 0),
        cached_tokens=int(getattr(prompt_details, "cached_tokens", 0) or 0),
        cache_write_tokens=int(getattr(prompt_details, "cache_write_tokens", 0) or 0),
    )


def _truncated(response: Any) -> bool:
    choices = getattr(response, "choices", None) or []

    if not choices:
        return False

    return getattr(choices[0], "finish_reason", None) == "length"


def _content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ProviderError("OpenRouter returned no choices")

    content = getattr(choices[0].message, "content", None)
    if not content:
        raise ProviderError("OpenRouter returned empty content")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = [
            str(item.get("text", "")) for item in content if isinstance(item, dict)
        ]
        text = "".join(parts)
        if text:
            return text

    return str(content)


class OpenRouterProvider(LLMProvider):
    name = ProviderName.OPENROUTER

    def __init__(self, settings: OpenRouterSettings) -> None:
        if not settings.api_key:
            raise ProviderError("OPENROUTER_API_KEY is required")

        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ProviderError(
                "the openai package is required for OpenRouterProvider"
            ) from exc

        headers: dict[str, str] = {}
        if settings.app_url:
            headers["HTTP-Referer"] = settings.app_url
        if settings.app_title:
            headers["X-OpenRouter-Title"] = settings.app_title

        self.settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            max_retries=settings.max_retries,
            timeout=settings.timeout,
            default_headers=headers or None,
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
        del cache_namespace
        request = _request(
            model=model,
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            schema=None,
            settings=self.settings,
        )

        try:
            response = await self._client.chat.completions.create(**request)
        except Exception as exc:
            raise ProviderError(f"OpenRouter request failed: {exc}") from exc

        usage = _usage(response)

        if _truncated(response):
            raise truncation_error(self.name, usage, max_output_tokens)

        return LLMResponse(
            content=_content(response),
            usage=usage,
            model=str(getattr(response, "model", None) or model),
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
        del cache_namespace
        request = _request(
            model=model,
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            schema=schema,
            settings=self.settings,
        )

        try:
            response = await self._client.chat.completions.create(**request)
        except Exception as exc:
            raise ProviderError(f"OpenRouter structured request failed: {exc}") from exc

        usage = _usage(response)

        if _truncated(response):
            raise truncation_error(self.name, usage, max_output_tokens)

        try:
            parsed = schema.model_validate_json(_content(response))
        except ValidationError as exc:
            raise ProviderError(
                f"OpenRouter returned invalid {schema.__name__}: {exc}"
            ) from exc

        return StructuredResponse(
            parsed=parsed,
            usage=usage,
            model=str(getattr(response, "model", None) or model),
            provider=self.name,
        )
