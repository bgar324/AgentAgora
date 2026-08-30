"""Baseline paper search and hidden cluster-grounded Perspective contracts."""

from __future__ import annotations

import asyncio
import sqlite3

import numpy as np
import pytest

from agora.api.focused import paper_detail
from agora.focused import agents
from agora.focused.models import (
    FACETS,
    ClusterCard,
    ExpPaper,
    FacetCandidate,
    FacetEvidence,
    FacetExtraction,
    NotepadDoc,
    NotepadTurn,
    QuerySuggestions,
    SuggestedQuery,
)
from agora.focused.persistence import FocusedPersistence
from agora.focused.service import FocusedPanelService, SessionError

PROBLEM = "Should antibiotics be prescribed broadly?"
POSITION = {
    "framing": "Prescribing breadth is an evolutionary-pressure problem.",
    "prior": "Cohorts link broad days to resistance without pricing benefit.",
    "method": "Compare severity-matched cohorts on resistome carriage.",
    "expected": "Narrower first-line holds outcomes outside sepsis.",
}


def _paper(index: int, *, vector: list[float] | None = None) -> ExpPaper:
    sentence = f"Paper {index} reports bounded antibiotic evidence."
    return ExpPaper(
        id=f"p{index}",
        title=f"Antibiotic paper {index}",
        abstract=sentence,
        abstract_sentences=[sentence],
        year=2020 + index,
        authors=[f"Author {index}"],
        specter_v2=vector or [float(index), 1.0],
    )


def _cluster(papers: list[ExpPaper]) -> ClusterCard:
    return ClusterCard(
        id="cluster-1",
        name="Bounded antibiotic policy",
        blurb="Evidence about policy boundaries.",
        facets=[
            FacetEvidence(
                facet=facet,
                text=papers[index % len(papers)].abstract_sentences[0],
                paper_id=papers[index % len(papers)].id,
                sentence_index=0,
                sentence=papers[index % len(papers)].abstract_sentences[0],
            )
            for index, facet in enumerate(FACETS)
        ],
        paper_ids=[paper.id for paper in papers],
        representative_paper_ids=[paper.id for paper in papers[:5]],
    )


def _seeded_service(
    paper_count: int = 3,
    *,
    persistence: FocusedPersistence | None = None,
) -> tuple[FocusedPanelService, str, str]:
    service = FocusedPanelService(persistence=persistence)
    view = service.create_workspace(
        problem=PROBLEM,
        position=dict(POSITION),
        demo=True,
    )
    state = service.get(view.active.id)
    state.papers = [_paper(index) for index in range(1, paper_count + 1)]
    state.clusters = [_cluster(state.papers)]
    state.searched = True
    return service, state.id, view.workspace.id


def test_position_prompt_names_every_part_the_researcher_wrote() -> None:
    block = agents._position_block(NotepadDoc(**POSITION))
    for label in ("Framing", "Previous work", "Methodology", "Expected results"):
        assert f"### {label}" in block
    assert POSITION["method"] in block


def test_unwritten_and_partial_positions_do_not_invent_parts() -> None:
    assert agents._position_block(NotepadDoc()) == ""
    assert agents._position_block(None) == ""
    block = agents._position_block(NotepadDoc(framing="Only this one."))
    assert "### Framing" in block
    assert "Methodology" not in block


def test_query_suggestion_and_question_derivation_see_all_four_parts(
    monkeypatch,
) -> None:
    captured: list[str] = []

    async def capture(provider, system, user, schema, **kwargs):
        captured.append(user)

    monkeypatch.setattr(agents, "_structured", capture)

    async def go() -> None:
        await agents.suggest_queries(
            PROBLEM,
            [],
            position=NotepadDoc(**POSITION),
        )
        await agents.derive_research_questions(
            PROBLEM,
            position=NotepadDoc(**POSITION),
        )

    asyncio.run(go())
    assert len(captured) == 2
    for prompt in captured:
        assert PROBLEM in prompt
        assert all(value in prompt for value in POSITION.values())


def test_partial_or_duplicate_model_queries_are_completed_to_five(
    monkeypatch,
) -> None:
    async def partial(*_args, **_kwargs):
        return QuerySuggestions(
            queries=[
                SuggestedQuery(query="resistance ecology"),
                SuggestedQuery(query="resistance ecology"),
            ]
        )

    monkeypatch.setattr(agents, "_structured", partial)
    queries = asyncio.run(
        agents.suggest_queries(
            PROBLEM,
            [],
            position=NotepadDoc(**POSITION),
        )
    )
    assert len(queries) == 5
    assert len({suggestion.query.casefold() for suggestion in queries}) == 5


def test_partial_or_unsupported_model_facets_use_grounded_fallbacks(
    monkeypatch,
) -> None:
    paper = ExpPaper(
        id="paper",
        title="Resistance study",
        abstract=(
            "Adults received broad antibiotics. "
            "Longer exposure selected resistance genes. "
            "A cohort compared antibiotic-days. "
            "Resistance increased across hospitals."
        ),
        abstract_sentences=[
            "Adults received broad antibiotics.",
            "Longer exposure selected resistance genes.",
            "A cohort compared antibiotic-days.",
            "Resistance increased across hospitals.",
        ],
    )

    async def partial(*_args, **_kwargs):
        return FacetExtraction(
            facets=[
                FacetCandidate(
                    facet="scope",
                    text="An unsupported claim about marine mammals.",
                    paper_id=paper.id,
                    sentence_index=0,
                )
            ]
        )

    monkeypatch.setattr(agents, "_structured", partial)
    facets = asyncio.run(agents.extract_cluster_facets([paper], provider=object()))
    assert [evidence.facet for evidence in facets] == FACETS
    assert all(evidence.sentence in paper.abstract_sentences for evidence in facets)
    assert all("marine mammals" not in evidence.text for evidence in facets)


def test_demo_and_live_flags_share_query_behavior() -> None:
    async def suggestions(demo: bool) -> list[str]:
        service = FocusedPanelService()
        state = service.create_workspace(
            problem=PROBLEM,
            position=dict(POSITION),
            demo=demo,
        ).active
        state = await service.suggest_queries(state.id)
        return [suggestion.query for suggestion in state.suggested_queries]

    assert asyncio.run(suggestions(True)) == asyncio.run(suggestions(False))


def test_anchor_paper_builds_the_complete_hidden_cluster_profile() -> None:
    async def go() -> None:
        service, session_id, workspace_id = _seeded_service()
        await service.generate_perspective(
            session_id,
            paper_id="p2",
            name="Resistance steward",
            description="Tests treatment benefit against ecological cost.",
        )
        perspective = service.get(session_id).perspectives[0]
        assert perspective.name == "Resistance steward"
        assert perspective.summary == "Tests treatment benefit against ecological cost."
        assert perspective.anchor_paper_id == "p2"
        assert perspective.related_paper_count == 2
        assert perspective.cluster_id == "cluster-1"
        assert set(perspective.sources) == {"p1", "p2", "p3"}
        assert set(perspective.facets) == set(FACETS)
        assert perspective.framing is not None
        assert all(
            evidence.paper_id in {"p1", "p2", "p3"}
            for evidence in perspective.facets.values()
        )

        public = service.workspace_view(workspace_id).model_dump(mode="json")
        assert set(public["active"]) == {
            "id",
            "workspace_id",
            "created_at",
            "problem",
            "position",
            "suggested_queries",
            "searched_queries",
            "papers",
            "perspectives",
            "notepad",
            "searched",
        }
        public_perspective = public["active"]["perspectives"][0]
        assert set(public_perspective) == {
            "id",
            "name",
            "color",
            "summary",
            "anchor_paper_id",
            "related_paper_count",
        }
        assert "clusters" not in public["active"]
        assert "specter_v2" not in public["active"]["papers"][0]

    asyncio.run(go())


def test_job_and_description_orient_identity_without_replacing_evidence() -> None:
    async def go() -> None:
        service, session_id, _ = _seeded_service()
        await service.generate_perspective(
            session_id,
            paper_id="p1",
            name="Clinical  trialist",
            description=(
                "Prioritizes severity-matched outcomes.\n"
                "Keeps  the ecological boundary explicit."
            ),
        )
        perspective = service.get(session_id).perspectives[0]
        assert perspective.name == "Clinical  trialist"
        assert perspective.summary == (
            "Prioritizes severity-matched outcomes.\n"
            "Keeps  the ecological boundary explicit."
        )
        assert all(item.paper_id for item in perspective.facets.values())
        assert all(
            "Prioritizes severity-matched outcomes" not in item.text
            for item in perspective.facets.values()
        )

    asyncio.run(go())


def test_description_orients_feedback_comparison_and_direct_reply(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, _ = _seeded_service()
        orientation = "Prioritizes severity-matched outcomes."
        await service.generate_perspective(
            session_id,
            paper_id="p1",
            name="Clinical trialist",
            description=orientation,
        )
        perspective = service.get(session_id).perspectives[0]
        prompts: list[str] = []

        async def capture(provider, system, user, schema, **kwargs):
            prompts.append(user)

        monkeypatch.setattr(agents, "_structured", capture)
        feedback = NotepadTurn(
            id="turn-1",
            version_id="v1",
            kind="feedback",
            role="perspective",
            author_id=perspective.id,
            author_label=perspective.name,
            text="Feedback.",
            review_n=1,
            part="framing",
        )
        await agents.review_draft_element(
            perspective,
            "framing",
            POSITION["framing"],
        )
        await agents.compare_draft_feedback(
            perspective,
            "framing",
            POSITION["framing"],
            [feedback],
        )
        await agents.reply_to_user(
            perspective,
            "What should I defend?",
            [],
        )
        assert len(prompts) == 3
        assert all(orientation in prompt for prompt in prompts)
        assert all("Clinical trialist" in prompt for prompt in prompts)

    asyncio.run(go())


def test_blank_description_falls_back_to_derived_framing() -> None:
    async def go() -> None:
        service, session_id, _ = _seeded_service()
        await service.generate_perspective(
            session_id,
            paper_id="p1",
            description="   ",
        )
        perspective = service.get(session_id).perspectives[0]
        assert perspective.framing is not None
        assert perspective.summary == perspective.framing.framing

    asyncio.run(go())


def test_blank_job_is_rejected_before_profile_synthesis(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, _ = _seeded_service()

        async def should_not_run(*args, **kwargs):
            raise AssertionError("blank Job reached the model")

        monkeypatch.setattr(agents, "derive_framing", should_not_run)
        with pytest.raises(SessionError, match="Job requires text"):
            await service.generate_perspective(
                session_id,
                paper_id="p1",
                name="   ",
            )

    asyncio.run(go())


def test_perspective_ids_are_not_reused_after_removal_and_cold_reload() -> None:
    async def go() -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        persistence = FocusedPersistence(connection)
        service, session_id, _ = _seeded_service(persistence=persistence)
        await service.generate_perspective(session_id, paper_id="p1")
        await service.generate_perspective(session_id, paper_id="p2")
        assert [item.id for item in service.get(session_id).perspectives] == [
            "persp-1",
            "persp-2",
        ]
        await service.remove_perspective(session_id, "persp-2")

        reloaded = FocusedPanelService(persistence=persistence)
        await reloaded.generate_perspective(session_id, paper_id="p3")
        state = reloaded.get(session_id)
        assert [item.id for item in state.perspectives] == ["persp-1", "persp-3"]
        assert state.perspective_sequence == 3

    asyncio.run(go())


def test_duplicate_anchor_is_rejected_before_model_work(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, _ = _seeded_service()
        await service.generate_perspective(session_id, paper_id="p1")

        async def should_not_run(*args, **kwargs):
            raise AssertionError("duplicate reached the model")

        monkeypatch.setattr(agents, "derive_framing", should_not_run)
        with pytest.raises(SessionError, match="already has a Perspective"):
            await service.generate_perspective(session_id, paper_id="p1")

    asyncio.run(go())


def test_six_perspective_limit_is_checked_before_model_work(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, _ = _seeded_service(paper_count=7)
        for index in range(1, 7):
            await service.generate_perspective(session_id, paper_id=f"p{index}")

        async def should_not_run(*args, **kwargs):
            raise AssertionError("seventh Perspective reached the model")

        monkeypatch.setattr(agents, "derive_framing", should_not_run)
        with pytest.raises(SessionError, match="at most six"):
            await service.generate_perspective(session_id, paper_id="p7")

    asyncio.run(go())


def test_a_later_perspective_joins_the_current_discussion_element() -> None:
    async def go() -> None:
        service, session_id, _ = _seeded_service()
        await service.generate_perspective(session_id, paper_id="p1")
        await service.start_notepad(session_id)
        notepad = service.get(session_id).notepad
        assert notepad is not None
        version_id = notepad.active_version_id
        assert version_id is not None
        await service.discuss_notepad(session_id, version_id=version_id, turns=1)
        await service.generate_perspective(session_id, paper_id="p2")
        notepad = service.get(session_id).notepad
        assert notepad is not None
        assert notepad.in_chat == ["persp-1", "persp-2"]
        active = notepad.active_version()
        assert active is not None
        assert active.agenda.participant_ids == ["persp-1", "persp-2"]
        await service.discuss_notepad(session_id, version_id=version_id, turns=1)
        assert notepad.turns[-1].author_id == "persp-2"
        assert notepad.turns[-1].kind == "feedback"

    asyncio.run(go())


def test_every_density_noise_paper_attaches_to_one_nearest_cluster() -> None:
    first = [_paper(1, vector=[1.0, 0.0]), _paper(2, vector=[0.9, 0.1])]
    second = [_paper(3, vector=[0.0, 1.0]), _paper(4, vector=[0.1, 0.9])]
    noise = _paper(5, vector=[0.95, 0.05])
    groups = FocusedPanelService._attach_unassigned_papers(
        [first, second],
        [noise],
    )
    assert noise in groups[0]
    assert noise not in groups[1]
    assert sum(paper.id == noise.id for group in groups for paper in group) == 1
    assert np.allclose(noise.specter_v2, [0.95, 0.05])


def test_paper_detail_exposes_plain_metadata_without_fragment_hits() -> None:
    async def go() -> None:
        service, session_id, _ = _seeded_service()
        await service.generate_perspective(session_id, paper_id="p1")
        detail = await paper_detail(session_id, "p1", service)
        assert set(detail) == {"paper"}
        assert detail["paper"].id == "p1"
        assert "specter_v2" not in detail["paper"].model_dump()

    asyncio.run(go())


def test_finish_blocks_building_another_perspective() -> None:
    async def go() -> None:
        service, session_id, _ = _seeded_service()
        await service.generate_perspective(session_id, paper_id="p1")
        await service.start_notepad(session_id)
        await service.finish_notepad_study(session_id)
        with pytest.raises(SessionError, match="read-only"):
            await service.generate_perspective(session_id, paper_id="p2")

    asyncio.run(go())
