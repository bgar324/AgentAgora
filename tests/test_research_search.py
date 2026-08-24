from __future__ import annotations

import asyncio

import pytest

from agora.core.errors import Conflict
from agora.research.search import (
    LiteratureSearch,
    RetrievalProgress,
    retrieval_progress_message,
)
from agora.schemas.research import (
    ResearchDirection,
    ResearchIdea,
    ResearchQuestion,
    RetrievalSeed,
    SearchPlan,
    SearchQuery,
)
from agora.workflow.run import Runner


class EmptyClient:
    async def search_snippets(self, *_args, **_kwargs):
        return []


def test_literature_search_reports_each_query_checkpoint() -> None:
    async def go() -> None:
        updates: list[RetrievalProgress] = []

        async def progress(update: RetrievalProgress) -> None:
            updates.append(update)

        search = LiteratureSearch(EmptyClient(), progress=progress)
        await search.retrieve(
            [
                SearchQuery(id="R1", stage="seed", query="first", intent="one"),
                SearchQuery(id="P1", stage="direction", query="second", intent="two"),
            ],
            [],
        )
        assert [update.stage for update in updates] == [
            "query_started",
            "query_completed",
            "query_started",
            "query_completed",
        ]
        assert (
            retrieval_progress_message(updates[1])
            == "Searched first...retrieved 0 papers"
        )
        assert updates[1].query == "first"
        assert updates[1].retrieved == 0
        assert updates[1].source_ids == ()
        assert updates[-1].completed_queries == 2
        assert updates[-1].total_queries == 2

    asyncio.run(go())


def test_runner_updates_reviewed_research_directions(tmp_path) -> None:
    investigation_id = "investigation"
    plan = SearchPlan(
        idea=ResearchIdea(idea="How should human-AI decisions be explained?"),
        research_question=ResearchQuestion(
            title="Decision transparency",
            main_question="Which explanations improve calibrated trust?",
        ),
        retrieval_seeds=[
            RetrievalSeed(query="human AI transparency", intent="Initial scope")
        ],
        research_directions=[
            ResearchDirection(
                topic="Trust calibration",
                query="calibrated trust explanations",
                intent="Original direction",
            )
        ],
    )
    (tmp_path / "search_plan.json").write_text(plan.model_dump_json())
    runner = object.__new__(Runner)
    transitions: list[dict] = []
    events: list[dict] = []
    runner.require_version = lambda *_args, **_kwargs: None
    runner._dir = lambda _investigation_id: tmp_path
    runner._transition = lambda _investigation_id, **fields: transitions.append(fields)
    runner.emit = lambda _investigation_id, _kind, payload: events.append(payload)
    reviewed = [
        ResearchDirection(
            topic="User control",
            query="human AI user control",
            intent="Include control mechanisms",
        ),
        ResearchDirection(
            topic="Decision quality",
            query="AI explanation decision quality",
            intent="Include performance outcomes",
        ),
    ]

    runner.update_brief(
        investigation_id,
        version=1,
        title=None,
        research_question=None,
        research_directions=reviewed,
    )

    updated = SearchPlan.model_validate_json(
        (tmp_path / "search_plan.json").read_text()
    )
    assert updated.research_directions == reviewed
    assert transitions == [{}]
    assert events[0]["research_directions"] == [
        item.model_dump(mode="json") for item in reviewed
    ]
    with pytest.raises(Conflict, match="Expected 2 distinct Research Directions"):
        runner.update_brief(
            investigation_id,
            version=1,
            title=None,
            research_question=None,
            research_directions=[reviewed[0], reviewed[0]],
        )
