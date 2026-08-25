from typing import TypeVar

from pydantic import BaseModel

from agora.config.settings import FocusedModelSettings, PhaseModel
from agora.focused.routing import TASK_ROLES, FocusedModelRole, FocusedTask
from agora.llm.providers.base import LLMProvider, StructuredResponse

T = TypeVar("T", bound=BaseModel)


class FocusedProvider:
    """Narrow adapter used by the standalone focused-panel workflow."""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        models: FocusedModelSettings,
        disable_prompt_cache: bool = False,
    ) -> None:
        self._llm = llm
        self._models = models
        self._cache_scope = ""
        self._disable_prompt_cache = disable_prompt_cache

    def _phase(self, role: FocusedModelRole) -> PhaseModel:
        match role:
            case FocusedModelRole.corpus:
                return self._models.corpus
            case FocusedModelRole.query:
                return self._models.query
            case FocusedModelRole.reasoning:
                return self._models.reasoning
            case FocusedModelRole.evaluation:
                return self._models.evaluation

    def set_cache_scope(self, scope: str) -> None:
        self._cache_scope = scope.strip()

    async def generate_structured(
        self,
        *,
        task: FocusedTask,
        messages: list[dict[str, str]],
        schema: type[T],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> StructuredResponse[T]:
        phase = self._phase(TASK_ROLES[task])
        return await self._llm.generate_structured(
            model=phase.model,
            messages=messages,  # type: ignore[arg-type]
            schema=schema,
            temperature=(
                None
                if phase.reasoning_effort is not None
                else phase.temperature
                if temperature is None
                else temperature
            ),
            max_output_tokens=max_output_tokens or phase.max_tokens,
            reasoning_effort=phase.reasoning_effort,
            cache_namespace=(
                ""
                if self._disable_prompt_cache
                else (
                    f"focused-panel:{self._cache_scope}:{TASK_ROLES[task].value}"
                    if self._cache_scope
                    else f"focused-panel:{TASK_ROLES[task].value}"
                )
            ),
        )

    async def close(self) -> None:
        client = getattr(self._llm, "_client", None)
        close = getattr(client, "close", None)
        if close is not None:
            await close()
