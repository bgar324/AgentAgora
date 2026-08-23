from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agora.focused import agents
from agora.focused.agents import FocusedAgentError
from agora.focused.demo_data import (
    DEMO_FACETS,
    DEMO_PAPERS,
    DEMO_RESEARCH_QUESTIONS,
)
from agora.focused.models import (
    FACETS,
    DeliberationPoint,
    DeliberationRating,
    ExpPaper,
    FacetEvidence,
    FacetVerdict,
    Perspective,
    RoundResolution,
)
from agora.focused.service import FocusedPanelService, SessionError

PROBLEM = (
    "Should antibiotics be prescribed broadly when faster cure may trade off "
    "against resistance and microbiome harm?"
)
QUESTIONS = [
    "Does broad-spectrum use raise resistance enough to matter at population level?",
    "Does it harm the patient's flora beyond the treated infection?",
]


class FlakingProvider:
    async def generate_structured(self, **_):
        raise RuntimeError("provider unavailable")


class SemanticEmbedder:
    embedding_model = "fixture-semantic"

    async def embed_batch(self, texts: list[str]):
        import numpy as np

        return np.asarray(
            [[0.0, 1.0] if text == "opposite" else [1.0, 0.0] for text in texts],
            dtype=np.float32,
        )


def _facet_map(prefix: str, paper_id: str = "paper") -> dict[str, FacetEvidence]:
    return {
        facet: FacetEvidence(
            facet=facet,
            text=f"{prefix} {facet} account",
            paper_id=paper_id,
            sentence_index=0,
            sentence=f"{prefix} {facet} account.",
        )
        for facet in FACETS
    }


def _perspective(
    name: str,
    prefix: str,
    paper_id: str = "paper",
) -> Perspective:
    return Perspective(
        id=name.lower().replace(" ", "-"),
        name=name,
        color="#336699",
        facets=_facet_map(prefix, paper_id),
        sources=[paper_id],
    )


async def _demo_panel() -> tuple[FocusedPanelService, str, str, list[int]]:
    service = FocusedPanelService()
    state = service.create_workspace(
        problem=PROBLEM,
        research_questions=QUESTIONS,
        demo=True,
    ).active
    state = await service.suggest_queries(state.id)
    state = await service.run_search(
        state.id,
        [query.query for query in state.suggested_queries[:3]],
    )
    for cluster in state.clusters[:2]:
        state = await service.generate_perspective(
            state.id,
            cluster_id=cluster.id,
        )
    state = await service.create_deliberation(state.id)
    deliberation = state.deliberations[0]
    agent_iids = [agent.iid for agent in state.agents]
    assert deliberation.agent_iids == agent_iids
    return service, state.id, deliberation.id, agent_iids


def test_perspectives_join_open_deliberation_without_reset_and_end_once() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        state = service.create_workspace(
            problem=PROBLEM,
            research_questions=QUESTIONS,
            demo=True,
        ).active
        state = await service.suggest_queries(state.id)
        state = await service.run_search(
            state.id,
            [query.query for query in state.suggested_queries[:3]],
        )
        assert state.searched_queries == [
            query.query for query in state.suggested_queries[:3]
        ]

        for cluster in state.clusters[:2]:
            state = await service.generate_perspective(
                state.id,
                cluster_id=cluster.id,
            )
        assert len(state.agents) == 2

        state = await service.create_deliberation(state.id)
        deliberation = state.deliberations[0]
        assert deliberation.agent_iids == [agent.iid for agent in state.agents]

        state = await service.run_round(
            state.id,
            deliberation.id,
            lead_iid=deliberation.agent_iids[0],
            facets=["scope"],
        )
        first = state.deliberations[0]
        assert first.rounds[0].participant_iids == first.agent_iids
        assert first.hypothesis is not None
        state = await service.confirm_deliberation_hypothesis(
            state.id,
            first.id,
            first.hypothesis,
        )
        state = await service.save_deliberation_hypothesis(state.id, first.id)
        saved_version_id = state.applied_hypothesis_version_id
        saved_hypothesis = state.applied_hypothesis
        question_ids = [
            question.id for question in state.deliberations[0].recommended_questions
        ]

        state = await service.generate_perspective(
            state.id,
            cluster_id=state.clusters[2].id,
        )
        updated = state.deliberations[0]
        assert len(state.agents) == 3
        assert len(updated.rounds) == 1
        assert state.applied_hypothesis_version_id == saved_version_id
        assert state.applied_hypothesis == saved_hypothesis
        assert [
            question.id for question in updated.recommended_questions
        ] == question_ids
        assert updated.agent_iids == [agent.iid for agent in state.agents]

        state = await service.run_round(
            state.id,
            updated.id,
            lead_iid=updated.agent_iids[-1],
            facets=["explanation"],
        )
        updated = state.deliberations[0]
        assert updated.rounds[0].participant_iids == updated.agent_iids[:2]
        assert updated.rounds[1].participant_iids == updated.agent_iids
        assert updated.hypothesis is not None
        state = await service.confirm_deliberation_hypothesis(
            state.id,
            updated.id,
            updated.hypothesis,
        )
        state = await service.save_deliberation_hypothesis(state.id, updated.id)
        final_version_id = state.applied_hypothesis_version_id

        with pytest.raises(SessionError, match="End the deliberation"):
            await service.rate_deliberation(
                state.id,
                updated.id,
                DeliberationRating(divergent=6, convergent=5),
            )

        state = await service.complete_deliberation(state.id, updated.id)
        completed = state.deliberations[0]
        assert completed.completed_at is not None
        assert completed.final_hypothesis_version_id == final_version_id

        with pytest.raises(SessionError, match="ended"):
            await service.run_round(
                state.id,
                completed.id,
                lead_iid=completed.agent_iids[0],
                facets=["approach"],
            )

        state = await service.rate_deliberation(
            state.id,
            completed.id,
            DeliberationRating(divergent=6, convergent=5),
        )
        assert state.deliberations[0].rating is not None
        assert state.deliberations[0].rating.divergent == 6
        assert all(
            "rating" not in round_state.model_dump()
            for round_state in state.deliberations[0].rounds
        )

    asyncio.run(go())


def test_demo_search_reaches_every_default_research_question() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        state = service.create_workspace(
            problem=PROBLEM,
            research_questions=DEMO_RESEARCH_QUESTIONS,
            demo=True,
        ).active
        state = await service.suggest_queries(state.id)
        selected = state.suggested_queries[:3]
        assert [(query.kind, query.question_index) for query in selected] == [
            ("question", 0),
            ("question", 1),
            ("question", 2),
        ]

        state = await service.run_search(
            state.id,
            [query.query for query in selected],
        )

        assert len(state.question_reach) == 3
        for reach in state.question_reach:
            assert reach.queries_r1
            assert reach.retrieved > 0
            assert reach.selected
            assert reach.reached

    asyncio.run(go())


def test_completed_investigation_cannot_replace_its_literature() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        state = service.create_workspace(
            problem=PROBLEM,
            research_questions=DEMO_RESEARCH_QUESTIONS,
            demo=True,
        ).active
        state = await service.suggest_queries(state.id)
        selected = [query.query for query in state.suggested_queries[:3]]
        state = await service.run_search(state.id, selected)

        with pytest.raises(SessionError, match="child Investigation"):
            await service.suggest_queries(state.id)
        with pytest.raises(SessionError, match="child Investigation"):
            await service.run_search(state.id, selected)

    asyncio.run(go())


def test_extracts_exactly_four_abstract_grounded_facets() -> None:
    async def go() -> None:
        facets = await agents.extract_cluster_facets(
            DEMO_PAPERS[:4],
            provider=None,
            demo_facets=[DEMO_FACETS[paper.id] for paper in DEMO_PAPERS[:4]],
        )
        assert [facet.facet for facet in facets] == FACETS
        by_id = {paper.id: paper for paper in DEMO_PAPERS[:4]}
        for evidence in facets:
            assert evidence.paper_id in by_id
            assert evidence.sentence_index is not None
            assert (
                evidence.sentence
                == by_id[evidence.paper_id].abstract_sentences[evidence.sentence_index]
            )
            assert evidence.sentence in (by_id[evidence.paper_id].abstract or "")

    asyncio.run(go())


def test_maps_facet_only_to_abstract_sentences() -> None:
    paper = DEMO_PAPERS[0]
    sentence = paper.abstract_sentences[1]
    exact = FacetEvidence(
        facet="explanation",
        text=sentence[12:65],
        paper_id=paper.id,
    )
    mapped = agents.map_facet_to_sentence(paper, exact)
    assert mapped.sentence_index == 1
    assert mapped.sentence == sentence

    fuzzy = FacetEvidence(
        facet="explanation",
        text="selects higher prevalence resistance genes",
        paper_id=paper.id,
    )
    assert agents.map_facet_to_sentence(paper, fuzzy).sentence_index == 1


def test_framing_and_position_are_coupled_descriptors_not_rounds() -> None:
    async def go() -> None:
        perspective = _perspective("Resistance ecology", "resistance")
        synthesis = await agents.derive_framing(perspective, provider=None)
        combined = f"{synthesis.framing} {synthesis.position}".lower()
        for facet in FACETS:
            assert facet in combined

    asyncio.run(go())


def test_facet_judgement_does_not_treat_difference_as_disagreement() -> None:
    async def go() -> None:
        lead = _perspective("Lead", "population")
        same = _perspective("Same", "population")
        different = _perspective("Different", "clinical")

        consensus = await agents.judge_facet(
            lead,
            [same],
            "scope",
            ["We share the same scope."],
            provider=None,
        )
        assert consensus.status == "consensus"

        unsettled = await agents.judge_facet(
            lead,
            [different],
            "scope",
            ["The second paper adds another population boundary."],
            provider=None,
        )
        assert unsettled.status == "unsettled"

        disagreement = await agents.judge_facet(
            lead,
            [different],
            "scope",
            ["These scopes are incompatible; I disagree with the lead boundary."],
            provider=None,
        )
        assert disagreement.status == "disagreement"

    asyncio.run(go())


def test_resolution_creates_unsettled_fallback_without_forced_conflict() -> None:
    async def go() -> None:
        resolution = await agents.summarize_round(
            ["scope"],
            [
                FacetVerdict(
                    facet="scope",
                    status="consensus",
                    summary="The panel shares a population boundary.",
                    consensus="Adults receiving empiric treatment.",
                    evidence={
                        "Lead": ["p1"],
                        "Other": ["p2", "p1"],
                    },
                )
            ],
            ["Both panel members accepted the population boundary."],
            provider=None,
        )
        assert resolution.consensus_points
        assert not resolution.disagreement_points
        assert resolution.unsettled_points
        assert "boundary" in resolution.unsettled_points[0].rationale.lower()
        assert resolution.consensus_points[0].citations == ["p1", "p2"]
        assert resolution.unsettled_points[0].citations == ["p1", "p2"]

        questions = await agents.recommend_questions(
            resolution,
            _perspective("Shared", "shared"),
            provider=None,
        )
        assert questions
        assert all(item.source_kind == "unsettled" for item in questions)
        assert all(item.rationale and item.source_point for item in questions)
        assert all(".?" not in item.question for item in questions)

    asyncio.run(go())


def test_model_round_summary_is_normalized_to_process_and_conclusion() -> None:
    class OneSentenceProvider:
        async def generate_structured(self, **_):
            return SimpleNamespace(
                parsed=RoundResolution(
                    summary="The panel compared the two positions and weighed their evidence.",
                    consensus_points=[],
                    disagreement_points=[],
                    unsettled_points=[],
                )
            )

    async def go() -> None:
        resolution = await agents.summarize_round(
            ["scope"],
            [
                FacetVerdict(
                    facet="scope",
                    status="consensus",
                    summary="The panel agreed on the population boundary.",
                    consensus="Shared boundary",
                )
            ],
            ["First position", "Corroborating position"],
            provider=OneSentenceProvider(),
        )

        assert len(agents.split_sentences(resolution.summary)) == 2
        assert resolution.summary.startswith("The panel compared")
        assert "agreed on the population boundary" in resolution.summary

    asyncio.run(go())


def test_hypothesis_uses_consensus_only() -> None:
    async def go() -> None:
        resolution = RoundResolution(
            summary="One shared boundary; other matters remain open.",
            consensus_points=[
                DeliberationPoint(
                    facet="scope",
                    text="Shared adult inpatient boundary",
                    citations=["paper"],
                )
            ],
            disagreement_points=[
                DeliberationPoint(
                    facet="explanation",
                    text="FORBIDDEN DISAGREEMENT CLAIM",
                )
            ],
            unsettled_points=[
                DeliberationPoint(
                    facet="approach",
                    text="FORBIDDEN UNSETTLED CLAIM",
                )
            ],
        )
        hypothesis = await agents.develop_hypothesis_from_consensus(
            resolution,
            provider=None,
        )
        text = " ".join(hypothesis.model_dump().values())
        assert "Shared adult inpatient boundary" in text
        assert "FORBIDDEN" not in text

    asyncio.run(go())


def test_live_provider_failure_is_typed_not_silently_fabricated() -> None:
    async def go() -> None:
        with pytest.raises(FocusedAgentError):
            await agents.suggest_queries(
                PROBLEM,
                QUESTIONS,
                provider=FlakingProvider(),
            )

    asyncio.run(go())


def test_full_facet_round_records_resolution_metrics_rating_and_child_branch() -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            facets=["scope", "explanation"],
        )
        deliberation = state.deliberations[0]
        round_state = deliberation.rounds[0]

        assert round_state.completed
        assert round_state.facets == ["scope", "explanation"]
        assert {verdict.facet for verdict in round_state.verdicts} == {
            "scope",
            "explanation",
        }
        assert round_state.resolution is not None
        assert round_state.resolution.summary.startswith("The panel compared")
        assert 2 <= len(agents.split_sentences(round_state.resolution.summary)) <= 3
        assert round_state.metrics is not None
        assert round_state.metrics.after == []
        assert round_state.metrics.method == "unavailable:no-semantic-embedder"
        assert round_state.metrics.direction == "insufficient"
        assert not deliberation.no_agreement
        assert deliberation.hypothesis is not None
        assert deliberation.hypothesis.problem != "Not established yet."
        assert deliberation.hypothesis.reasoning != "Not established yet."
        assert deliberation.hypothesis.hypothesis != "Not established yet."
        assert deliberation.recommended_questions
        assert all(
            question.source_kind == "unsettled"
            for question in deliberation.recommended_questions
        )
        assert all(
            question.source_round == round_state.n
            for question in deliberation.recommended_questions
        )

        state = await service.confirm_deliberation_hypothesis(
            session_id,
            deliberation_id,
            deliberation.hypothesis,
        )
        state = await service.save_deliberation_hypothesis(
            session_id,
            deliberation_id,
        )
        state = await service.complete_deliberation(session_id, deliberation_id)
        state = await service.rate_deliberation(
            session_id,
            deliberation_id,
            DeliberationRating(
                divergent=6,
                convergent=3,
                note="Broadened the boundary",
            ),
        )
        assert state.deliberations[0].rating is not None
        assert state.deliberations[0].rating.divergent == 6

        question = state.deliberations[0].recommended_questions[0]
        view = await service.create_child_investigation(
            state.workspace_id,
            session_id,
            question.id,
        )
        parent = service.get(session_id)
        child = view.active
        assert (
            parent.deliberations[0].recommended_questions[0].status == "investigating"
        )
        assert child.parent_investigation_id == parent.id
        assert child.origin_question_id == question.id
        assert child.research_questions == [question.question]
        assert child.papers == []
        assert child.perspectives == []
        assert child.agents == []

        exported = service.export_workspace(state.workspace_id)
        assert exported["schema_version"] == 4
        exported_deliberation = exported["investigations"][0]["deliberations"][0]
        assert exported_deliberation["rounds"][0]["metrics"]["method"].startswith(
            "unavailable:"
        )
        assert "rating" not in exported_deliberation["rounds"][0]
        assert exported_deliberation["rating"]["convergent"] == 3

    asyncio.run(go())


def test_demo_hypothesis_progresses_across_separate_rounds() -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            facets=["scope"],
        )
        first = state.deliberations[0]
        assert first.hypothesis is not None
        assert first.hypothesis.problem != "Not established yet."
        first_hypothesis = first.hypothesis.model_copy(deep=True)
        assert first.hypothesis.previous_work != "Not established yet."
        assert first.hypothesis.reasoning == "Not established yet."
        assert first.hypothesis.hypothesis == "Not established yet."

        state = await service.confirm_deliberation_hypothesis(
            session_id,
            deliberation_id,
            first_hypothesis,
        )
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[1],
            facets=["explanation"],
        )
        second = state.deliberations[0]
        assert second.hypothesis is not None
        assert second.hypothesis.problem == first_hypothesis.problem
        assert second.hypothesis.reasoning != "Not established yet."
        assert second.hypothesis.hypothesis != "Not established yet."
        assert "broader and longer exposure" in second.hypothesis.hypothesis.lower()

    asyncio.run(go())


def test_unchanged_consensus_does_not_create_pending_update(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            facets=["scope"],
        )
        candidate = state.deliberations[0].hypothesis
        assert candidate is not None
        state = await service.confirm_deliberation_hypothesis(
            session_id,
            deliberation_id,
            candidate,
        )
        applied = state.deliberations[0].applied_hypothesis
        assert applied is not None

        async def unchanged_hypothesis(*_args, **_kwargs):
            return applied.model_copy(
                deep=True,
                update={
                    "problem": f"  {applied.problem}  ",
                    "reasoning": "   ",
                },
            )

        monkeypatch.setattr(
            agents,
            "develop_hypothesis_from_consensus",
            unchanged_hypothesis,
        )
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[1],
            facets=["explanation"],
        )
        deliberation = state.deliberations[0]
        assert deliberation.hypothesis == applied
        assert deliberation.hypothesis_confirmed

    asyncio.run(go())


def test_round_accepts_only_one_or_two_unique_facets() -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        with pytest.raises(SessionError, match="one or two"):
            await service.run_round(
                session_id,
                deliberation_id,
                lead_iid=agent_iids[0],
                facets=[],
            )
        with pytest.raises(SessionError, match="one or two"):
            await service.run_round(
                session_id,
                deliberation_id,
                lead_iid=agent_iids[0],
                facets=["scope", "explanation", "approach"],
            )
        with pytest.raises(SessionError, match="one or two"):
            await service.run_round(
                session_id,
                deliberation_id,
                lead_iid=agent_iids[0],
                facets=["scope", "scope"],
            )

    asyncio.run(go())


def test_semantic_cosine_metric_records_all_facets_and_direction() -> None:
    async def go() -> None:
        embedder = SemanticEmbedder()
        service = FocusedPanelService(
            embedder=embedder.embed_batch,
            embedding_model=embedder.embedding_model,
        )
        state = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        before = {
            1: {facet: "same" for facet in FACETS},
            2: {facet: "same" for facet in FACETS},
        }
        after = {
            1: {facet: "same" for facet in FACETS},
            2: {
                facet: ("opposite" if facet == "scope" else "same") for facet in FACETS
            },
        }
        metrics = await service._round_metrics(
            service._require(state.id),
            before,
            after,
        )
        assert metrics.method == "semantic:fixture-semantic"
        assert [item.facet for item in metrics.after] == FACETS
        assert metrics.after[0].distance == pytest.approx(1.0)
        assert all(item.distance == pytest.approx(0.0) for item in metrics.before)
        assert metrics.direction == "divergent"
        assert metrics.delta is not None and metrics.delta > 0

    asyncio.run(go())


def test_consensus_round_proposes_and_evolves_working_hypothesis() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        state = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        state.papers = [
            ExpPaper(
                id="paper",
                title="Shared evidence",
                abstract="Shared evidence.",
                abstract_sentences=["Shared evidence."],
            )
        ]
        first = _perspective("First", "shared")
        second = _perspective("Second", "shared")
        first.facets["explanation"].text = "FORBIDDEN PROFILE DETAIL"
        second.facets["explanation"].text = "FORBIDDEN PROFILE DETAIL"
        state.perspectives = [first, second]
        state = await service.create_deliberation(state.id)
        deliberation = state.deliberations[0]
        agent_iids = [agent.iid for agent in state.agents]
        state = await service.run_round(
            state.id,
            deliberation.id,
            lead_iid=agent_iids[0],
            facets=["scope"],
        )

        deliberation = state.deliberations[0]
        round_state = deliberation.rounds[0]
        assert round_state.verdicts[0].status == "consensus"
        assert deliberation.hypothesis is not None
        hypothesis_text = " ".join(deliberation.hypothesis.model_dump().values())
        assert "shared scope account" in hypothesis_text.lower()
        assert "FORBIDDEN PROFILE DETAIL" not in hypothesis_text
        assert round_state.metrics is not None
        assert round_state.metrics.method == "unavailable:no-semantic-embedder"

        first_problem = deliberation.hypothesis.problem
        with pytest.raises(SessionError, match="pending shared-ground update"):
            await service.run_round(
                state.id,
                deliberation.id,
                lead_iid=agent_iids[1],
                facets=["approach"],
            )

        state = await service.confirm_deliberation_hypothesis(
            state.id,
            deliberation.id,
            deliberation.hypothesis,
        )
        assert state.deliberations[0].hypothesis_confirmed

        state = await service.run_round(
            state.id,
            deliberation.id,
            lead_iid=agent_iids[1],
            facets=["approach"],
        )
        evolved = state.deliberations[0]
        assert len(evolved.rounds) == 2
        assert evolved.hypothesis is not None
        assert evolved.hypothesis.problem == first_problem
        assert "shared approach account" in evolved.hypothesis.reasoning.lower()
        assert evolved.hypothesis_confirmed is False

    asyncio.run(go())


def test_edited_facets_are_not_misrepresented_as_abstract_provenance() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        state = service.create_workspace(
            problem=PROBLEM, research_questions=[], demo=True
        ).active
        state = await service.suggest_queries(state.id)
        state = await service.run_search(
            state.id,
            [query.query for query in state.suggested_queries[:2]],
        )
        cluster = state.clusters[0]
        edited = [item.model_copy(deep=True) for item in cluster.facets]
        edited[0].text = "Researcher-defined scope"
        edited[0].edited = True
        state = await service.generate_perspective(
            state.id,
            cluster_id=cluster.id,
            facets=edited,
        )
        evidence = state.perspectives[0].facets["scope"]
        assert evidence.edited
        assert evidence.paper_id is None
        assert evidence.sentence_index is None
        assert evidence.sentence is None

    asyncio.run(go())


def test_panel_perspectives_cannot_be_removed_after_first_round() -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            facets=["scope"],
        )
        perspective_id = service.get(session_id).agents[0].perspective_id
        with pytest.raises(SessionError, match="cannot be removed"):
            await service.remove_perspective(session_id, perspective_id)

    asyncio.run(go())
