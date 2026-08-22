import asyncio
import logging
import random
from collections.abc import Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import monotonic
from typing import Any, Protocol, Self

import httpx

from agora.client.cache import CACHE_MISS, FileCache
from agora.core.errors import ClientError
from agora.schemas.research import AcademicField, Paper, SearchHit

logger = logging.getLogger("agora.client")

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class LiteratureClient(Protocol):
    async def search_snippets(
        self,
        query: str,
        *,
        limit: int,
        fields_of_study: Sequence[AcademicField] = (),
        year: str | None = None,
        min_citations: int = 0,
    ) -> list[SearchHit]:
        ...

    async def get_papers(
        self,
        source_ids: Sequence[str],
        *,
        batch_size: int,
    ) -> list[Paper]:
        ...


class BaseAPIClient:
    def __init__(
        self,
        *,
        base_url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
        min_request_interval: float = 0.0,
        max_retries: int = 3,
        retry_threshold_s: float = 60.0,
        cache: FileCache | None = None,
        cache_ttl: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.min_request_interval = max(0.0, min_request_interval)
        self.max_retries = max(0, max_retries)
        self.retry_threshold_s = max(0.0, retry_threshold_s)
        self.cache = cache
        self.cache_ttl = cache_ttl
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _wait_for_slot(self) -> None:
        async with self._request_lock:
            elapsed = monotonic() - self._last_request_at
            remaining = self.min_request_interval - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request_at = monotonic()

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        header = response.headers.get("retry-after")
        if not header:
            return None
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(header)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())

    @staticmethod
    def _response_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])[:500]
            if isinstance(error, str) and error:
                return error[:500]
            if payload.get("message"):
                return str(payload["message"])[:500]
        return str(payload)[:500]

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
        json_body: Any = None,
        use_cache: bool = True,
        cache_ttl: float | None = None,
    ) -> Any:
        key = FileCache.key(method, path, params=params, json_body=json_body)

        if use_cache and self.cache is not None:
            cached = await asyncio.to_thread(
                self.cache.get,
                key,
                ttl=self.cache_ttl if cache_ttl is None else cache_ttl,
            )
            if cached is not CACHE_MISS:
                return cached

        started = monotonic()
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            await self._wait_for_slot()
            retry_after: float | None = None
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                )
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if response.is_success:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise ClientError(
                            f"{method.upper()} {path} returned invalid JSON"
                        ) from exc
                    if use_cache and self.cache is not None:
                        await asyncio.to_thread(self.cache.set, key, payload)
                    return payload

                last_error = ClientError(
                    f"{method.upper()} {path} returned {response.status_code}: "
                    f"{self._response_detail(response)}"
                )
                if response.status_code not in RETRYABLE_STATUS:
                    raise last_error
                retry_after = self._retry_after(response)

            if attempt >= self.max_retries:
                break

            delay = retry_after if retry_after is not None else min(30.0, 2.0**attempt)
            delay += random.uniform(0.0, min(1.0, delay * 0.2))
            if monotonic() - started + delay > self.retry_threshold_s:
                break

            logger.warning(
                "Retrying %s %s in %.1fs (attempt %d/%d)",
                method.upper(),
                path,
                delay,
                attempt + 1,
                self.max_retries,
            )
            await asyncio.sleep(delay)

        if last_error is None:
            raise ClientError(f"{method.upper()} {path} failed")
        if isinstance(last_error, ClientError):
            raise last_error
        raise ClientError(f"{method.upper()} {path} failed: {last_error}") from last_error
