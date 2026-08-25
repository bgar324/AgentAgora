from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agora.config.settings import (
    FocusedModelSettings,
    ModelSettings,
    PhaseModel,
    load_settings,
)
from agora.core.errors import ConfigurationError
from agora.focused.models import QuerySuggestions
from agora.focused.provider import FocusedProvider
from agora.focused.routing import TASK_ROLES, FocusedTask


class RecordingLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed=QuerySuggestions(queries=[]))


def routes() -> FocusedModelSettings:
    return FocusedModelSettings(
        corpus=PhaseModel("gpt-5.6-luna", None, 6_000, "low"),
        query=PhaseModel("gpt-5.6-luna", None, 2_000, "low"),
        reasoning=PhaseModel("gpt-5.6-luna", None, 2_000, "medium"),
        evaluation=PhaseModel("gpt-5.6-luna", None, 4_000, "high"),
    )


@pytest.mark.parametrize(
    ("task", "effort", "max_tokens"),
    [
        (FocusedTask.assess_question_papers, "low", 6_000),
        (FocusedTask.suggest_queries, "low", 2_000),
        (FocusedTask.open_statement, "medium", 2_000),
        (FocusedTask.summarize_round, "high", 4_000),
    ],
)
def test_provider_routes_tasks_to_requested_models(
    task, effort, max_tokens
) -> None:
    async def go() -> None:
        llm = RecordingLLM()
        provider = FocusedProvider(llm=llm, models=routes())
        await provider.generate_structured(
            task=task,
            messages=[{"role": "user", "content": "test"}],
            schema=QuerySuggestions,
            temperature=0.7,
        )
        request = llm.calls[0]
        assert request["model"] == "gpt-5.6-luna"
        assert request["reasoning_effort"] == effort
        assert request["max_output_tokens"] == max_tokens
        assert request["temperature"] is None
        assert request["cache_namespace"] == f"focused-panel:{TASK_ROLES[task].value}"
        provider.set_cache_scope("cold-run")
        await provider.generate_structured(
            task=task,
            messages=[{"role": "user", "content": "test"}],
            schema=QuerySuggestions,
        )
        assert llm.calls[1]["cache_namespace"] == (
            f"focused-panel:cold-run:{TASK_ROLES[task].value}"
        )


    asyncio.run(go())


def test_all_model_defaults_use_gpt_5_6_luna() -> None:
    focused = FocusedModelSettings()
    assert {
        focused.corpus.model,
        focused.query.model,
        focused.reasoning.model,
        focused.evaluation.model,
    } == {"gpt-5.6-luna"}

    legacy = ModelSettings()
    assert {
        legacy.brief.model,
        legacy.panel.model,
        legacy.deliberation.model,
    } == {"openai/gpt-5.6-luna"}


def test_supabase_startup_requires_openai_key(monkeypatch) -> None:
    monkeypatch.setenv("AGORA_PERSISTENCE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "service-key")
    monkeypatch.setenv("AGORA_PROXY_TOKEN", "proxy-token")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        load_settings()
