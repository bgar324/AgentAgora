from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agora.config.settings import (
    FocusedModelSettings,
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
        corpus=PhaseModel("luna", None, 6_000, "low"),
        query=PhaseModel("terra-query", None, 2_000, "low"),
        reasoning=PhaseModel("terra-reasoning", None, 2_000, "medium"),
        evaluation=PhaseModel("sol", None, 4_000, "high"),
    )


@pytest.mark.parametrize(
    ("task", "model", "effort"),
    [
        (FocusedTask.assess_question_papers, "luna", "low"),
        (FocusedTask.suggest_queries, "terra-query", "low"),
        (FocusedTask.open_statement, "terra-reasoning", "medium"),
        (FocusedTask.summarize_round, "sol", "high"),
    ],
)
def test_provider_routes_tasks_to_requested_models(task, model, effort) -> None:
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
        assert request["model"] == model
        assert request["reasoning_effort"] == effort
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


def test_focused_model_defaults_use_official_openai_ids() -> None:
    models = FocusedModelSettings()
    assert models.corpus.model == "gpt-5.6-luna"
    assert models.query.model == "gpt-5.6-terra"
    assert models.reasoning.model == "gpt-5.6-terra"
    assert models.evaluation.model == "gpt-5.6-sol"


def test_supabase_startup_requires_openai_key(monkeypatch) -> None:
    monkeypatch.setenv("AGORA_PERSISTENCE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "service-key")
    monkeypatch.setenv("AGORA_PROXY_TOKEN", "proxy-token")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        load_settings()
