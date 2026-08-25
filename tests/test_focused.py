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
    DeliberationThread,
    ExpPaper,
    Facet,
    FacetEvidence,
    Perspective,
    RecommendedQuestion,
    RoundResolution,
    SessionState,
    SharedGroundAssentDraft,
    Statement,
    ThreadVerdict,
    TurnKind,
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


def _scientific_thread(*facets: Facet) -> DeliberationThread:
    related = list(facets) or ["scope"]
    return DeliberationThread(
        id="thread",
        title="Boundary question",
        question="Which boundary should govern the solution?",
        context="The Perspectives describe different boundaries.",
        facets=related,
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
    state = await service.initialize_deliberation(
        state.id,
        deliberation.id,
        state.agents[0].perspective_id,
    )
    deliberation = state.deliberations[0]
    assert deliberation.agent_iids == agent_iids
    return service, state.id, deliberation.id, agent_iids


def _thread_id(
    service: FocusedPanelService,
    session_id: str,
    facet: Facet = "scope",
) -> str:
    deliberation = service.get(session_id).deliberations[0]
    return next(issue.id for issue in deliberation.threads if facet in issue.facets)


async def _run_and_accept_rounds(
    service: FocusedPanelService,
    session_id: str,
    deliberation_id: str,
    lead_iid: int,
    facets: list[Facet],
) -> SessionState:
    state = service.get(session_id)
    for facet in facets:
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=lead_iid,
            thread_id=_thread_id(service, session_id, facet),
        )
        deliberation = state.deliberations[0]
        if not deliberation.hypothesis_confirmed:
            assert deliberation.hypothesis is not None
            state = await service.confirm_deliberation_hypothesis(
                session_id,
                deliberation_id,
                deliberation.hypothesis,
            )
    return state


def test_compacts_prose_queries_and_relaxes_to_broad_terms() -> None:
    query = (
        "How can a compiler identify explicit obligations relevant to a request "
        "x in a large system prompt P?"
    )
    assert (
        agents.compact_search_query(query)
        == "compiler explicit obligations large system prompt"
    )
    assert agents.relaxed_search_query(query) == "large system prompt"
    assert (
        agents.compact_search_query(
            '"critical-obligation compliance" AND "task quality"'
        )
        == "critical-obligation compliance task quality"
    )
    assert (
        agents.compact_search_query('"AI writing tools" AND "team output diversity"')
        == "ai writing tools team output diversity"
    )
    assert (
        agents.compact_search_query("ai writing tools workplace 2")
        == "ai writing tools workplace 2"
    )
    acronym_query = (
        "How does GPT-4 compare to LLM RAG pipelines for clinical QA accuracy?"
    )
    assert (
        agents.compact_search_query(acronym_query)
        == "gpt-4 compare llm rag pipelines clinical"
    )
    assert agents.relaxed_search_query(acronym_query) == "clinical qa accuracy"
    assert (
        agents.compact_search_query(
            "Does COVID-19 vaccination reduce long-term fatigue in adults?"
        )
        == "covid-19 vaccination reduce long-term fatigue adults"
    )


def test_added_perspective_restarts_deliberation_from_scratch() -> None:
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
        for cluster in state.clusters[:2]:
            state = await service.generate_perspective(
                state.id,
                cluster_id=cluster.id,
            )
        state = await service.create_deliberation(state.id)
        deliberation = state.deliberations[0]
        state = await service.initialize_deliberation(
            state.id,
            deliberation.id,
            state.agents[0].perspective_id,
        )
        deliberation = state.deliberations[0]
        state = await service.run_round(
            state.id,
            deliberation.id,
            lead_iid=deliberation.agent_iids[0],
            thread_id=_thread_id(service, state.id, "scope"),
        )
        deliberation = state.deliberations[0]
        assert deliberation.hypothesis is not None
        state = await service.confirm_deliberation_hypothesis(
            state.id,
            deliberation.id,
            deliberation.hypothesis,
        )
        state = await service.save_deliberation_hypothesis(
            state.id,
            deliberation.id,
        )
        saved_version_id = state.applied_hypothesis_version_id
        invited_id = state.perspectives[0].id
        previous_iids = set(state.deliberations[0].agent_iids)

        state = await service.generate_perspective(
            state.id,
            cluster_id=state.clusters[2].id,
            invited_perspective_ids=[invited_id],
        )

        deliberation = state.deliberations[0]
        assert len(deliberation.completion_history) == 1
        archived = deliberation.completion_history[0]
        assert archived.reason == "restarted"
        assert len(archived.rounds) == 1
        assert archived.hypothesis is not None
        assert archived.applied_hypothesis_version_id == saved_version_id
        archived_json = archived.model_dump_json()
        assert deliberation.rounds == []
        assert deliberation.recommended_questions == []
        assert deliberation.chat == []
        assert deliberation.hypothesis is None
        assert deliberation.applied_hypothesis is None
        assert not deliberation.hypothesis_confirmed
        assert deliberation.completed_at is None
        assert deliberation.final_hypothesis_version_id is None
        assert deliberation.rating is None
        assert previous_iids.isdisjoint(deliberation.agent_iids)
        roster = {
            next(agent for agent in state.agents if agent.iid == iid).perspective_id
            for iid in deliberation.agent_iids
        }
        assert roster == {invited_id, state.perspectives[-1].id}
        roster_iids = list(deliberation.agent_iids)
        state = await service.create_deliberation(state.id)
        deliberation = state.deliberations[0]
        assert deliberation.agent_iids == roster_iids
        state = await service.initialize_deliberation(
            state.id,
            deliberation.id,
            next(
                agent.perspective_id
                for agent in state.agents
                if agent.iid == deliberation.agent_iids[0]
            ),
        )
        deliberation = state.deliberations[0]
        with pytest.raises(SessionError, match="cannot be removed"):
            await service.remove_perspective(state.id, invited_id)
        for iid in deliberation.agent_iids:
            agent = next(item for item in state.agents if item.iid == iid)
            perspective = next(
                item for item in state.perspectives if item.id == agent.perspective_id
            )
            assert agent.facets == perspective.facets
            assert agent.facet_version == 1

        state = await service.run_round(
            state.id,
            deliberation.id,
            lead_iid=deliberation.agent_iids[0],
            thread_id=_thread_id(service, state.id, "explanation"),
        )
        assert (
            state.deliberations[0].completion_history[0].model_dump_json()
            == archived_json
        )
        current = state.deliberations[0]
        assert len(current.rounds) == 1
        assert current.hypothesis is not None
        state = await service.confirm_deliberation_hypothesis(
            state.id,
            current.id,
            current.hypothesis,
        )
        state = await service.save_deliberation_hypothesis(state.id, current.id)
        view = service.workspace_view(state.workspace_id)
        latest = view.workspace.hypothesis_versions[-1]
        assert latest.parent_ids == []
        assert set(latest.step_sources.values()) == {latest.id}
        summary = next(item for item in view.investigations if item.id == state.id)
        assert summary.completed_rounds == 2

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


def test_thread_judgement_does_not_treat_difference_as_disagreement() -> None:
    async def go() -> None:
        lead = _perspective("Lead", "population")
        same = _perspective("Same", "population")
        different = _perspective("Different", "clinical")
        thread = _scientific_thread("scope")

        consensus = await agents.judge_thread(
            lead,
            [same],
            thread,
            ["We share the same scope."],
            provider=None,
        )
        assert consensus.status == "consensus"

        unsettled = await agents.judge_thread(
            lead,
            [different],
            thread,
            ["The second paper adds another population boundary."],
            provider=None,
        )
        assert unsettled.status == "unsettled"

        disagreement = await agents.judge_thread(
            lead,
            [different],
            thread,
            ["These scopes are incompatible; I disagree with the lead boundary."],
            provider=None,
        )
        assert disagreement.status == "disagreement"

    asyncio.run(go())


def test_resolution_creates_unsettled_fallback_without_forced_conflict() -> None:
    async def go() -> None:
        resolution = await agents.summarize_thread(
            _scientific_thread("scope"),
            ThreadVerdict(
                facets=["scope"],
                status="consensus",
                summary="The panel shares a population boundary.",
                consensus="Adults receiving empiric treatment.",
                evidence={
                    "Lead": ["p1"],
                    "Other": ["p2", "p1"],
                },
            ),
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


def test_model_thread_summary_is_normalized_to_process_and_conclusion() -> None:
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
        resolution = await agents.summarize_thread(
            _scientific_thread("scope"),
            ThreadVerdict(
                facets=["scope"],
                status="consensus",
                summary="The panel agreed on the population boundary.",
                consensus="Shared boundary",
            ),
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
            thread_id=_thread_id(service, session_id, "scope"),
        )
        deliberation = state.deliberations[0]
        round_state = deliberation.rounds[0]

        assert round_state.completed
        assert round_state.facets == ["scope", "significance"]
        assert round_state.verdict is not None
        assert round_state.verdict.facets == ["scope", "significance"]
        assert round_state.verdict.status == "consensus"
        assert round_state.stop_reason == "unanimous"
        assert len(round_state.moderator_checks) == 2
        assert not round_state.moderator_checks[0].unanimous
        assert all(
            assent.decision == "qualify"
            and assent.challenge_turn_id is not None
            and assent.challenge
            for assent in round_state.moderator_checks[0].assents
        )
        assert round_state.moderator_checks[1].unanimous
        assert all(
            assent.decision == "accept"
            for assent in round_state.moderator_checks[1].assents
        )
        assert {turn.exchange_n for turn in round_state.turns} == {1, 2}
        assert any(turn.relation == "challenge" for turn in round_state.turns)
        assert any(turn.reply_to_turn_id is not None for turn in round_state.turns)
        assert round_state.resolution is not None
        assert round_state.resolution.summary.startswith("The panel compared")
        assert 2 <= len(agents.split_sentences(round_state.resolution.summary)) <= 3
        assert round_state.metrics is not None
        assert round_state.metrics.after == []
        assert round_state.metrics.method == "unavailable:no-semantic-embedder"
        assert round_state.metrics.direction == "insufficient"
        assert not deliberation.no_agreement
        assert deliberation.hypothesis is not None
        assert deliberation.hypothesis.hypothesis != "Not established yet."
        assert round_state.reflections[0].decision == "revised"
        assert service.get(session_id).agents[0].facet_version == 2
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
        state = await _run_and_accept_rounds(
            service,
            session_id,
            deliberation_id,
            agent_iids[0],
            ["explanation", "approach", "significance"],
        )
        state = await service.save_deliberation_hypothesis(
            session_id,
            deliberation_id,
        )
        with pytest.raises(SessionError, match="unknown open questions"):
            await service.complete_deliberation(
                session_id,
                deliberation_id,
                ["missing-question"],
            )
        questions = state.deliberations[0].recommended_questions
        assert len(questions) > 1
        archived_question_id = questions[-1].id
        service.set_question_status(
            state.workspace_id,
            session_id,
            archived_question_id,
            "archived",
        )
        state = service.get(session_id)
        with pytest.raises(SessionError, match="unknown open questions"):
            await service.complete_deliberation(
                session_id,
                deliberation_id,
                [archived_question_id],
            )
        selected_question_id = state.deliberations[0].recommended_questions[0].id
        state = await service.complete_deliberation(
            session_id,
            deliberation_id,
            [selected_question_id],
        )
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
        assert state.deliberations[0].selected_question_ids == [selected_question_id]
        assert next(
            question
            for question in state.deliberations[0].recommended_questions
            if question.id == selected_question_id
        ).selected_for_followup

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
        assert exported["schema_version"] == 6
        exported_deliberation = exported["investigations"][0]["deliberations"][0]
        assert exported_deliberation["rounds"][0]["metrics"]["method"].startswith(
            "unavailable:"
        )
        assert "rating" not in exported_deliberation["rounds"][0]
        assert exported_deliberation["rating"]["convergent"] == 3

    asyncio.run(go())


def test_round_stops_at_exchange_limit_without_unanimous_hypothesis(
    monkeypatch,
) -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        accepted_perspective_id = next(
            agent.perspective_id
            for agent in service.get(session_id).agents
            if agent.iid == agent_iids[0]
        )

        async def mixed_assent(perspective, *_args, **_kwargs):
            accepted = perspective.id == accepted_perspective_id
            return SharedGroundAssentDraft(
                decision="accept" if accepted else "qualify",
                reason=(
                    "The claim is supported."
                    if accepted
                    else "The claim needs a narrower boundary."
                ),
            )

        monkeypatch.setattr(agents, "assent_to_shared_ground", mixed_assent)
        baseline = service.get(session_id).deliberations[0].applied_hypothesis
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "scope"),
        )
        deliberation = state.deliberations[0]
        round_state = deliberation.rounds[0]

        assert round_state.stop_reason == "exchange_limit"
        assert len(round_state.moderator_checks) == 3
        assert not any(check.unanimous for check in round_state.moderator_checks)
        expected_assents = {
            agent_iids[0]: "accept",
            agent_iids[1]: "qualify",
        }
        for check in round_state.moderator_checks:
            assert {
                assent.agent_iid: assent.decision for assent in check.assents
            } == expected_assents
            assert {
                turn.agent_iid
                for turn in round_state.turns
                if turn.exchange_n == check.exchange_n and turn.kind != TurnKind.support
            } == set(agent_iids)
        assert {turn.exchange_n for turn in round_state.turns} == {1, 2, 3}
        assert round_state.verdict is not None
        assert round_state.verdict.status == "unsettled"
        assert round_state.resolution is not None
        assert round_state.resolution.consensus_points == []
        assert round_state.hypothesis_proposal is None
        assert deliberation.hypothesis == baseline
        assert deliberation.hypothesis_confirmed
        assert deliberation.no_agreement

    asyncio.run(go())


def test_unanimous_narrow_ground_preserves_disagreement(monkeypatch) -> None:
    async def go() -> None:
        async def disagreement_with_shared_ground(*_args, **_kwargs):
            return ThreadVerdict(
                facets=["scope"],
                status="disagreement",
                summary="The panel disagrees about the governing population.",
                proposed_shared_ground="The evidence concerns antibiotic exposure.",
                disagreement="Which exposed population should govern the claim.",
                contested_by=["Host and microbiome"],
            )

        monkeypatch.setattr(
            agents,
            "judge_thread",
            disagreement_with_shared_ground,
        )
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "scope"),
        )
        round_state = state.deliberations[0].rounds[0]

        assert round_state.stop_reason == "unanimous"
        assert round_state.verdict is not None
        assert round_state.verdict.status == "disagreement"
        assert (
            round_state.verdict.consensus
            == "The evidence concerns antibiotic exposure."
        )
        assert (
            round_state.verdict.disagreement
            == "Which exposed population should govern the claim."
        )
        assert round_state.resolution is not None
        assert len(round_state.resolution.consensus_points) == 1
        assert len(round_state.resolution.disagreement_points) == 1
        assert round_state.hypothesis_proposal is not None
        assert state.deliberations[0].recommended_questions
        assert all(
            question.source_kind == "disagreement"
            for question in state.deliberations[0].recommended_questions
        )

    asyncio.run(go())


def test_shared_ground_assent_fails_closed_without_provider() -> None:
    async def go() -> None:
        assent = await agents.assent_to_shared_ground(
            _perspective("Boundary", "bounded"),
            "scope",
            "The supported population is narrowly bounded.",
            ["Boundary: The population is bounded."],
            provider=None,
            demo=False,
        )
        assert assent.decision == "reject"

    asyncio.run(go())


def test_generated_questions_are_normalized_to_unselected_open_state(
    monkeypatch,
) -> None:
    async def go() -> None:
        async def selected_question(*_args, **_kwargs):
            return [
                RecommendedQuestion(
                    id="model-controlled",
                    question="Which boundary remains unresolved?",
                    rationale="The model proposed a follow-up.",
                    source_kind="unsettled",
                    source_point="A boundary remains unresolved.",
                    facets=["scope"],
                    status="investigating",
                    child_investigation_id="model-controlled-child",
                    selected_for_followup=True,
                )
            ]

        monkeypatch.setattr(agents, "recommend_questions", selected_question)
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "scope"),
        )
        question = state.deliberations[0].recommended_questions[0]

        assert question.status == "open"
        assert question.child_investigation_id is None
        assert not question.selected_for_followup

    asyncio.run(go())


def test_child_research_starts_a_fresh_deliberation_cycle() -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "scope"),
        )
        proposal = state.deliberations[0].hypothesis
        assert proposal is not None
        state = await service.confirm_deliberation_hypothesis(
            session_id,
            deliberation_id,
            proposal,
        )
        state = await _run_and_accept_rounds(
            service,
            session_id,
            deliberation_id,
            agent_iids[0],
            ["explanation", "approach", "significance"],
        )
        state = await service.save_deliberation_hypothesis(
            session_id,
            deliberation_id,
        )
        state = await service.complete_deliberation(session_id, deliberation_id)
        state = await service.rate_deliberation(
            session_id,
            deliberation_id,
            DeliberationRating(divergent=6, convergent=5),
        )
        parent = state
        question = parent.deliberations[0].recommended_questions[0]
        child = (
            await service.create_child_investigation(
                parent.workspace_id,
                parent.id,
                question.id,
            )
        ).active
        child = await service.suggest_queries(child.id)
        child = await service.run_search(
            child.id,
            [query.query for query in child.suggested_queries[:3]],
        )
        for cluster in child.clusters[2:4]:
            child = await service.generate_perspective(
                child.id,
                cluster_id=cluster.id,
            )

        view = await service.integrate_child_investigation(
            parent.workspace_id,
            parent.id,
            child.id,
        )
        assert view.active.id == parent.id
        continued = service.get(parent.id)
        deliberation = continued.deliberations[0]
        assert deliberation.rounds == []
        assert deliberation.recommended_questions == []
        assert deliberation.chat == []
        assert deliberation.hypothesis is None
        assert deliberation.applied_hypothesis is None
        assert continued.applied_hypothesis_version_id == "H1"
        assert deliberation.completed_at is None
        assert deliberation.final_hypothesis_version_id is None
        assert deliberation.rating is None
        assert len(deliberation.completion_history) == 1
        completion = deliberation.completion_history[0]
        assert completion.reason == "completed"
        assert completion.final_hypothesis_version_id == "H1"
        assert completion.applied_hypothesis_version_id == "H1"
        assert len(completion.rounds) == 4
        assert completion.agent_iids == agent_iids
        assert question.id in completion.question_ids
        assert completion.recommended_questions[0].status == "addressed"
        assert completion.rating is not None
        assert completion.rating.divergent == 6
        assert len(continued.agents) == 6
        assert len(deliberation.agent_iids) == 4
        assert set(deliberation.agent_iids).isdisjoint(agent_iids)
        imported_perspectives = [
            perspective
            for perspective in continued.perspectives
            if perspective.source_question_id == question.id
        ]
        assert len(imported_perspectives) == 2
        assert service.get(child.id).integrated_into_parent_at is not None
        with pytest.raises(SessionError, match="already continued"):
            await service.integrate_child_investigation(
                parent.workspace_id,
                parent.id,
                child.id,
            )
        with pytest.raises(SessionError, match="already continued"):
            await service.generate_perspective(
                child.id,
                cluster_id=child.clusters[0].id,
            )
        with pytest.raises(SessionError, match="Complete a focused round"):
            await service.complete_deliberation(parent.id, deliberation.id)

        state = await service.initialize_deliberation(
            parent.id,
            deliberation.id,
            next(
                agent.perspective_id
                for agent in continued.agents
                if agent.iid == deliberation.agent_iids[-1]
            ),
        )
        deliberation = state.deliberations[0]
        state = await service.run_round(
            parent.id,
            deliberation.id,
            lead_iid=deliberation.agent_iids[-1],
            thread_id=_thread_id(service, parent.id, "explanation"),
        )
        continued_deliberation = state.deliberations[0]
        if not continued_deliberation.hypothesis_confirmed:
            assert continued_deliberation.hypothesis is not None
            state = await service.confirm_deliberation_hypothesis(
                parent.id,
                deliberation.id,
                continued_deliberation.hypothesis,
            )
        state = await _run_and_accept_rounds(
            service,
            parent.id,
            deliberation.id,
            deliberation.agent_iids[-1],
            ["scope", "approach", "significance"],
        )
        state = await service.save_deliberation_hypothesis(
            parent.id,
            deliberation.id,
        )
        state = await service.complete_deliberation(parent.id, deliberation.id)
        first_question_ids = set(
            state.deliberations[0].completion_history[0].question_ids
        )
        next_question = next(
            question
            for question in state.deliberations[0].recommended_questions
            if question.status == "open"
        )
        second_child = (
            await service.create_child_investigation(
                state.workspace_id,
                parent.id,
                next_question.id,
            )
        ).active
        second_child = await service.suggest_queries(second_child.id)
        second_child = await service.run_search(
            second_child.id,
            [query.query for query in second_child.suggested_queries[:3]],
        )
        second_child = await service.generate_perspective(
            second_child.id,
            cluster_id=second_child.clusters[4].id,
        )
        await service.integrate_child_investigation(
            state.workspace_id,
            parent.id,
            second_child.id,
        )
        twice_continued = service.get(parent.id)
        second_history = twice_continued.deliberations[0].completion_history
        assert len(second_history) == 2
        assert first_question_ids.isdisjoint(second_history[1].question_ids)
        second_import = next(
            perspective
            for perspective in twice_continued.perspectives
            if perspective.source_question_id == next_question.id
        )
        assert second_import.panel_cycle == 2

    asyncio.run(go())


def test_demo_baseline_and_proposals_progress_across_rounds() -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "scope"),
        )
        first = state.deliberations[0]
        assert first.baseline_hypothesis is not None
        assert first.hypothesis is not None
        first_hypothesis = first.hypothesis.model_copy(deep=True)
        first_round = first.rounds[0]
        assert first_round.hypothesis_before == first.baseline_hypothesis
        assert first_round.hypothesis_proposal == first.hypothesis

        state = await service.confirm_deliberation_hypothesis(
            session_id,
            deliberation_id,
            first_hypothesis,
        )
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "explanation"),
        )
        second = state.deliberations[0]
        assert second.hypothesis is not None
        second_round = second.rounds[1]
        assert second_round.hypothesis_before == first_hypothesis
        assert second_round.hypothesis_proposal == second.hypothesis
        assert second.lead_perspective_id == first.lead_perspective_id

    asyncio.run(go())


def test_unchanged_consensus_does_not_create_pending_update(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "scope"),
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
                update={"hypothesis": f"  {applied.hypothesis}  "},
            )

        monkeypatch.setattr(
            agents,
            "develop_hypothesis_from_consensus",
            unchanged_hypothesis,
        )
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "explanation"),
        )
        deliberation = state.deliberations[0]
        assert deliberation.hypothesis == applied
        assert deliberation.hypothesis_confirmed

    asyncio.run(go())


def test_round_requires_an_identified_thread() -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        with pytest.raises(SessionError, match="Thread"):
            await service.run_round(
                session_id,
                deliberation_id,
                lead_iid=agent_iids[0],
                thread_id="missing-thread",
            )

        thread = service.get(session_id).deliberations[0].threads[0]
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=thread.id,
        )
        round_state = state.deliberations[0].rounds[0]
        assert round_state.thread_id == thread.id
        assert round_state.facets == thread.facets

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


def test_consensus_threads_propose_and_evolve_the_working_hypothesis() -> None:
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
        second.facets["explanation"].text = "FORBIDDEN PROFILE DETAIL"
        state.perspectives = [first, second]
        state = await service.create_deliberation(state.id)
        deliberation = state.deliberations[0]
        agent_iids = [agent.iid for agent in state.agents]
        state = await service.initialize_deliberation(
            state.id,
            deliberation.id,
            first.id,
        )
        deliberation = state.deliberations[0]
        state = await service.run_round(
            state.id,
            deliberation.id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, state.id, "scope"),
        )

        deliberation = state.deliberations[0]
        round_state = deliberation.rounds[0]
        assert round_state.verdict is not None
        assert round_state.verdict.status == "consensus"
        assert deliberation.hypothesis is not None
        hypothesis_text = " ".join(deliberation.hypothesis.model_dump().values())
        assert "shared scope account" in hypothesis_text.lower()
        assert "FORBIDDEN PROFILE DETAIL" not in hypothesis_text
        assert round_state.metrics is not None
        assert round_state.metrics.method == "unavailable:no-semantic-embedder"

        first_candidate = deliberation.hypothesis.hypothesis
        if not deliberation.hypothesis_confirmed:
            state = await service.confirm_deliberation_hypothesis(
                state.id,
                deliberation.id,
                deliberation.hypothesis,
            )
        assert state.deliberations[0].hypothesis_confirmed

        state = await service.run_round(
            state.id,
            deliberation.id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, state.id, "approach"),
        )
        evolved = state.deliberations[0]
        assert len(evolved.rounds) == 2
        assert evolved.hypothesis is not None
        assert evolved.hypothesis.hypothesis != first_candidate
        assert "shared approach account" in evolved.hypothesis.hypothesis.lower()
        assert evolved.lead_perspective_id == first.id

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
            thread_id=_thread_id(service, session_id, "scope"),
        )
        perspective_id = service.get(session_id).agents[0].perspective_id
        with pytest.raises(SessionError, match="cannot be removed"):
            await service.remove_perspective(session_id, perspective_id)

    asyncio.run(go())


def test_deliberation_requires_a_lead_baseline_and_keeps_that_lead() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        state = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        state.perspectives = [
            _perspective("First", "first"),
            _perspective("Second", "second"),
        ]
        state = await service.create_deliberation(state.id)
        deliberation = state.deliberations[0]
        agent_iids = [agent.iid for agent in state.agents]

        with pytest.raises(SessionError, match="Choose a lead"):
            await service.run_round(
                state.id,
                deliberation.id,
                lead_iid=agent_iids[0],
                thread_id="not-initialized",
            )

        state = await service.initialize_deliberation(
            state.id,
            deliberation.id,
            state.perspectives[0].id,
        )
        deliberation = state.deliberations[0]
        assert deliberation.lead_perspective_id == state.perspectives[0].id
        assert deliberation.baseline_hypothesis is not None
        assert deliberation.hypothesis == deliberation.baseline_hypothesis
        assert deliberation.applied_hypothesis == deliberation.baseline_hypothesis
        assert deliberation.hypothesis_confirmed
        assert state.agents[0].hypothesis == deliberation.baseline_hypothesis

        await service.run_round(
            state.id,
            deliberation.id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, state.id, "scope"),
        )
        with pytest.raises(SessionError, match="cannot change after round 1"):
            await service.initialize_deliberation(
                state.id,
                deliberation.id,
                state.perspectives[1].id,
            )
        with pytest.raises(SessionError, match="configured lead"):
            await service.run_round(
                state.id,
                deliberation.id,
                lead_iid=agent_iids[1],
                thread_id=_thread_id(service, state.id, "explanation"),
            )

    asyncio.run(go())


def test_round_hypothesis_can_be_rejected_accepted_or_edited(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        proposal_number = 0

        async def distinct_proposal(_resolution, *, current, **_kwargs):
            nonlocal proposal_number
            assert current is not None
            proposal_number += 1
            return current.model_copy(
                deep=True,
                update={
                    "hypothesis": (
                        f"{current.hypothesis.strip()} revision {proposal_number}"
                    )
                },
            )

        monkeypatch.setattr(
            agents,
            "develop_hypothesis_from_consensus",
            distinct_proposal,
        )

        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "scope"),
        )
        first = state.deliberations[0]
        assert first.hypothesis is not None
        assert not first.hypothesis_confirmed
        baseline = first.applied_hypothesis
        assert baseline is not None
        state = await service.confirm_deliberation_hypothesis(
            session_id,
            deliberation_id,
            first.hypothesis,
            mode="reject_pending",
        )
        assert state.deliberations[0].applied_hypothesis == baseline
        assert state.deliberations[0].rounds[0].hypothesis_decision == "rejected"
        assert (
            next(
                agent for agent in state.agents if agent.iid == agent_iids[0]
            ).hypothesis
            == baseline
        )

        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "scope"),
        )
        second = state.deliberations[0]
        assert second.hypothesis is not None
        state = await service.confirm_deliberation_hypothesis(
            session_id,
            deliberation_id,
            second.hypothesis,
        )
        assert state.deliberations[0].rounds[1].hypothesis_decision == "accepted"

        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "explanation"),
        )
        third = state.deliberations[0]
        assert third.hypothesis is not None
        edited = third.hypothesis.model_copy(
            update={"hypothesis": f"{third.hypothesis.hypothesis.strip()} user edit"}
        )
        state = await service.confirm_deliberation_hypothesis(
            session_id,
            deliberation_id,
            edited,
        )
        assert state.deliberations[0].applied_hypothesis == edited
        assert state.deliberations[0].rounds[2].hypothesis_decision == "edited"
        assert (
            next(
                agent for agent in state.agents if agent.iid == agent_iids[0]
            ).hypothesis
            == edited
        )

    asyncio.run(go())


def test_edit_applied_replaces_the_whole_candidate() -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        state = await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "scope"),
        )
        deliberation = state.deliberations[0]
        assert deliberation.hypothesis is not None
        state = await service.confirm_deliberation_hypothesis(
            session_id,
            deliberation_id,
            deliberation.hypothesis,
        )
        current = state.deliberations[0].applied_hypothesis
        assert current is not None

        replacement = current.model_copy(
            update={"hypothesis": "Client-authored replacement candidate"}
        )
        state = await service.confirm_deliberation_hypothesis(
            session_id,
            deliberation_id,
            replacement,
            mode="edit_applied",
        )

        assert state.deliberations[0].applied_hypothesis == replacement

    asyncio.run(go())


def test_chat_receives_latest_completed_round_context(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        state = await _run_and_accept_rounds(
            service,
            session_id,
            deliberation_id,
            agent_iids[0],
            ["scope", "explanation"],
        )
        deliberation = state.deliberations[0]
        first_turn = deliberation.rounds[0].turns[0].text
        latest_round = deliberation.rounds[1]
        latest_exchange_n = max(turn.exchange_n or 1 for turn in latest_round.turns)
        latest_turn = next(
            turn.text
            for turn in latest_round.turns
            if (turn.exchange_n or 1) == latest_exchange_n
        )
        captured: dict[str, object] = {}

        async def capture_reply(_perspective, _question, _history, **kwargs):
            captured.update(kwargs)
            return Statement(text="Round-scoped answer", citations=[])

        monkeypatch.setattr(agents, "reply_to_user", capture_reply)
        await service.chat(
            session_id,
            deliberation_id,
            message="Why did the panel reach this conclusion?",
            target_iid=agent_iids[0],
        )

        round_context = captured["round_context"]
        assert isinstance(round_context, str)
        assert latest_turn in round_context
        if first_turn != latest_turn:
            assert first_turn not in round_context
        assert "Moderator resolution:" in round_context
        assert captured["active_facets"] == ["explanation"]
        assert captured["working_hypothesis"] == deliberation.applied_hypothesis

    asyncio.run(go())


def test_round_progress_reports_stages_and_live_turns() -> None:
    async def go() -> None:
        service, session_id, deliberation_id, agent_iids = await _demo_panel()
        generation = service.start_search_progress(session_id)
        await service.run_round(
            session_id,
            deliberation_id,
            lead_iid=agent_iids[0],
            thread_id=_thread_id(service, session_id, "scope"),
            progress_generation=generation,
        )
        progress = service.search_progress(
            session_id,
            generation=generation,
        )
        stage_items = [
            item for item in progress["items"] if item["kind"] == "round_stage"
        ]
        assert [item["step"] for item in stage_items] == list(range(1, 8))
        assert [item["stage"] for item in stage_items] == [
            "lead",
            "panel",
            "judging",
            "summary",
            "lead_revision",
            "hypothesis",
            "saving",
        ]
        turn_items = [
            item for item in progress["items"] if item["kind"] == "round_turn"
        ]
        assert len(turn_items) >= 2
        assert all(item["agent_label"] and item["text"] for item in turn_items)
        check_items = [
            item for item in progress["items"] if item["kind"] == "round_check"
        ]
        assert len(check_items) == 2
        assert [item["exchange_n"] for item in check_items] == [1, 2]
        assert all(item["proposed_shared_ground"] for item in check_items)
        assert [item["unanimous"] for item in check_items] == [False, True]

    asyncio.run(go())
