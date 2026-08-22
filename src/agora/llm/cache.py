import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from agora.client.cache import CACHE_MISS, FileCache
from agora.llm.providers.base import (
    LLMProvider,
    LLMResponse,
    Message,
    StructuredResponse,
    T,
)
from agora.schemas.base import TokenUsage


class CachedProvider(LLMProvider):
    def __init__(self, provider: LLMProvider, *, cache: FileCache) -> None:
        self.provider = provider
        self.cache = cache
        self.name = provider.name
        self.inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}

    def build_cache_key(
        self,
        *,
        model: str,
        messages: list[Message],
        temperature: float | None,
        max_output_tokens: int | None,
        reasoning_effort: str | None,
        schema: type[BaseModel] | None,
        cache_namespace: str | None,
    ) -> str:
        return FileCache.key(
            "POST",
            "/llm",
            json_body={
                "provider": self.provider.name.value,
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "reasoning_effort": reasoning_effort,
                "schema": None if schema is None else schema.model_json_schema(),
                "cache_namespace": cache_namespace,
            },
        )

    async def _load(self, key: str) -> dict[str, Any] | None:
        record = await asyncio.to_thread(self.cache.get, key)
        if record is CACHE_MISS or not isinstance(record, dict):
            return None
        return record

    async def _get_or_create(
        self,
        key: str,
        create: Callable[[], Awaitable[dict[str, Any]]],
    ) -> tuple[dict[str, Any], bool]:
        request = self.inflight.get(key)
        if request is not None:
            return await request, True

        request = asyncio.create_task(create())
        self.inflight[key] = request

        def remove(_: asyncio.Task[dict[str, Any]]) -> None:
            self.inflight.pop(key, None)

        request.add_done_callback(remove)
        return await request, False

    @staticmethod
    def _usage(record: dict[str, Any], reused: bool) -> TokenUsage:
        if reused:
            return TokenUsage()
        return TokenUsage.model_validate(record.get("usage") or {})

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
        key = self.build_cache_key(
            model=model,
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            schema=None,
            cache_namespace=cache_namespace,
        )

        record = await self._load(key)
        if record is not None:
            return LLMResponse(
                content=str(record.get("content") or ""),
                usage=TokenUsage(),
                model=str(record.get("model") or model),
                provider=self.name,
            )

        async def create() -> dict[str, Any]:
            response = await self.provider.generate(
                model=model,
                messages=messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                reasoning_effort=reasoning_effort,
                cache_namespace=cache_namespace,
            )
            created = {
                "content": response.content,
                "usage": response.usage.model_dump(mode="json"),
                "model": response.model,
            }
            await asyncio.to_thread(self.cache.set, key, created)
            return created

        record, reused = await self._get_or_create(key, create)

        return LLMResponse(
            content=str(record["content"]),
            usage=self._usage(record, reused),
            model=str(record["model"]),
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
        key = self.build_cache_key(
            model=model,
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            schema=schema,
            cache_namespace=cache_namespace,
        )

        record = await self._load(key)
        if record is not None:
            return StructuredResponse(
                parsed=schema.model_validate(record.get("parsed")),
                usage=TokenUsage(),
                model=str(record.get("model") or model),
                provider=self.name,
            )

        async def create() -> dict[str, Any]:
            response = await self.provider.generate_structured(
                model=model,
                messages=messages,
                schema=schema,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                reasoning_effort=reasoning_effort,
                cache_namespace=cache_namespace,
            )
            created = {
                "parsed": response.parsed.model_dump(mode="json"),
                "usage": response.usage.model_dump(mode="json"),
                "model": response.model,
            }
            await asyncio.to_thread(self.cache.set, key, created)
            return created

        record, reused = await self._get_or_create(key, create)

        return StructuredResponse(
            parsed=schema.model_validate(record["parsed"]),
            usage=self._usage(record, reused),
            model=str(record["model"]),
            provider=self.name,
        )
