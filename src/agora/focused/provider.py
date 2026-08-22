from typing import TypeVar

from pydantic import BaseModel

from agora.config.settings import PhaseModel
from agora.llm.providers.base import LLMProvider, StructuredResponse

T = TypeVar("T", bound=BaseModel)


class FocusedProvider:
    """Narrow adapter used by the standalone focused-panel workflow."""

    def __init__(self, *, llm: LLMProvider, phase: PhaseModel) -> None:
        self._llm = llm
        self._phase = phase

    async def generate_structured(
        self,
        *,
        messages: list[dict[str, str]],
        schema: type[T],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> StructuredResponse[T]:
        return await self._llm.generate_structured(
            model=self._phase.model,
            messages=messages,  # type: ignore[arg-type]
            schema=schema,
            temperature=(
                self._phase.temperature if temperature is None else temperature
            ),
            max_output_tokens=max_output_tokens or self._phase.max_tokens,
            cache_namespace="focused-panel",
        )

    async def close(self) -> None:
        client = getattr(self._llm, "_client", None)
        close = getattr(client, "close", None)
        if close is not None:
            await close()
