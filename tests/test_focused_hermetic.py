"""Hermetic integration checks for search, grounding, and study metrics."""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from typing import Any

import pytest

from agora.focused.models import (
    FACETS,
    ClusterNaming,
    ClusterNamings,
    ExpPaper,
    FacetEvidence,
    FacetExtraction,
    QuerySuggestions,
    QuestionAssessment,
    QuestionEvidence,
    QuestionPlan,
    SuggestedQuery,
    VocabularyPair,
)
from agora.focused.retrieval import FocusedSearchResult, FocusedSemanticScholar
from agora.focused.service import FocusedPanelService, SessionError
from agora.schemas.research import Paper


class HermeticRetrieval:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures: set[str] = set()
        self.papers = {
            "angle-1": FocusedSearchResult(
                id="angle-1",
                title="AI writing tools in knowledge work",
                abstract="AI writing tools alter drafting decisions in workplace knowledge work.",
            ),
            "angle-2": FocusedSearchResult(
                id="angle-2",
                title="Critiques of generative writing support",
                abstract="Generative writing support can narrow the range of workplace outputs.",
            ),
            "q-answer": FocusedSearchResult(
                id="q-answer",
                title="Draft suggestions and output diversity",
                abstract="Early AI draft suggestions reduce diversity of output across writers.",
            ),
            "q-follow": FocusedSearchResult(
                id="q-follow",
                title="Suggestion timing conditions homogenization",
                abstract="Suggestion timing conditions homogenization of written output.",
            ),
        }
        self.results = {
            "ai writing tools workplace": ["angle-1", "angle-2"],
            "ai writing tools workplace 2": ["angle-1", "angle-2"],
            "ai writing tools workplace 3": ["q-follow"],
            "ai suggestions output diversity": ["q-answer"],
            "ai suggestion homogenization": ["q-follow"],
            "withdrawn tool capability": [],
        }

    async def search(self, query: str, limit: int = 8):
        self.calls.append(query)
        if query in self.failures:
            raise RuntimeError("provider unavailable")
        return [self.papers[paper_id] for paper_id in self.results.get(query, [])][
            :limit
        ]


class HermeticProvider:
    name = "hermetic"

    def __init__(self, retrieval: HermeticRetrieval) -> None:
        self.retrieval = retrieval
        self.schemas: list[str] = []

    async def generate_structured(self, *, messages, schema, **_: Any):
        user = messages[-1]["content"]
        self.schemas.append(schema.__name__)
        if schema is QuerySuggestions:
            parsed = QuerySuggestions(
                queries=[
                    SuggestedQuery(
                        query=(
                            "ai suggestions output diversity"
                            if index == 1
                            else f"ai writing tools workplace {index}"
                        ),
                        rationale="Problem-angle literature.",
                    )
                    for index in range(1, 4)
                ]
            )
        elif schema is QuestionPlan:
            if "withdrawn" in user:
                parsed = QuestionPlan(
                    form="mechanism",
                    candidates=["capability persists after withdrawal"],
                    queries=[
                        SuggestedQuery(
                            query="withdrawn tool capability",
                            rationale="Question-specific terms.",
                            kind="question",
                        ),
                        SuggestedQuery(
                            query="durable skills after AI withdrawal",
                            rationale="Alternative question terms.",
                            kind="question",
                        ),
                    ],
                )
            else:
                parsed = QuestionPlan(
                    form="which-condition",
                    candidates=["suggestions arrive before an independent draft"],
                    queries=[
                        SuggestedQuery(
                            query="ai suggestions output diversity",
                            rationale="Question-specific terms.",
                            kind="question",
                        ),
                        SuggestedQuery(
                            query="ai writing homogenization",
                            rationale="Alternative question terms.",
                            kind="question",
                        ),
                    ],
                )
        elif schema is QuestionAssessment:
            if "[q-answer]" in user:
                parsed = QuestionAssessment(
                    selected=[
                        QuestionEvidence(
                            paper_id="q-answer",
                            candidate_index=1,
                            bears="supports",
                            evidence=(
                                "Early AI draft suggestions reduce diversity of "
                                "output across writers."
                            ),
                        ),
                        QuestionEvidence(
                            paper_id="q-answer",
                            candidate_index=1,
                            bears="supports",
                            evidence="Fabricated evidence sentence.",
                        ),
                    ],
                    vocabulary=[
                        VocabularyPair(
                            ours="diversity reduction",
                            theirs="homogenization",
                        )
                    ],
                    round2=[
                        SuggestedQuery(
                            query="ai suggestion homogenization",
                            rationale="Observed literature vocabulary.",
                            kind="question",
                            round=2,
                        )
                    ],
                )
            elif "[q-follow]" in user:
                parsed = QuestionAssessment(
                    selected=[
                        QuestionEvidence(
                            paper_id="q-follow",
                            candidate_index=1,
                            bears="conditions",
                            evidence=(
                                "Suggestion timing conditions homogenization "
                                "of written output."
                            ),
                        )
                    ]
                )
            else:
                parsed = QuestionAssessment()
        elif schema is ClusterNamings:
            cluster_count = len(re.findall(r"^## CLUSTER \d+", user, re.MULTILINE))
            repeated_names = [
                "Writing support",
                "Writing support effects",
                "Writing support evidence",
            ]
            parsed = ClusterNamings(
                clusters=[
                    ClusterNaming(
                        name=repeated_names[index % len(repeated_names)],
                        blurb="Evidence about how generated suggestions shape writing.",
                    )
                    for index in range(cluster_count)
                ]
            )
        elif schema is FacetExtraction:
            match = re.search(r"### ([^:]+):", user)
            assert match is not None
            paper_id = match.group(1)
            sentence = self.retrieval.papers[paper_id].abstract or ""
            parsed = FacetExtraction(
                facets=[
                    FacetEvidence(
                        facet=facet,
                        text=sentence,
                        paper_id=paper_id,
                        sentence_index=0,
                    )
                    for facet in FACETS
                ]
            )
        else:
            raise AssertionError(f"Unexpected schema: {schema.__name__}")
        return SimpleNamespace(parsed=parsed)


class FailingEmbedder:
    embedding_model = "broken"

    async def embed_batch(self, _texts: list[str]):
        raise RuntimeError("embedding unavailable")


class FailingRetrieval:
    async def search(self, _query: str, **_: Any):
        raise RuntimeError("provider unavailable")


def test_question_search_records_reach_and_miss() -> None:
    async def go() -> None:
        retrieval = HermeticRetrieval()
        retrieval.failures.add("withdrawn tool capability")
        provider = HermeticProvider(retrieval)
        service = FocusedPanelService(provider=provider, s2=retrieval)
        state = service.create_workspace(
            problem="How do AI writing tools affect knowledge work?",
            research_questions=[
                "When do draft suggestions reduce output diversity?",
                "What capability remains after the tool is withdrawn?",
            ],
            demo=False,
        ).active
        state = await service.suggest_queries(state.id)
        selected = [query.query for query in state.suggested_queries]
        assert len(state.suggested_queries) == 5
        assert [
            (query.kind, query.question_index) for query in state.suggested_queries[:2]
        ] == [("question", 0), ("question", 1)]
        assert len({query.query.casefold() for query in state.suggested_queries}) == 5
        state = await service.run_search(state.id, selected)

        assert "ai suggestion homogenization" not in retrieval.calls
        assert "withdrawn tool capability" in retrieval.calls
        assert all(not reach.queries_r2 for reach in state.question_reach)
        assert state.question_reach[0].reached
        assert {evidence.paper_id for evidence in state.question_reach[0].selected} == {
            "q-answer"
        }
        assert state.question_reach[1].reached is False
        assert state.question_reach[1].selected == []
        assert state.clusters
        assert len({cluster.name.casefold() for cluster in state.clusters}) == len(
            state.clusters
        )
        assert provider.schemas.count("ClusterNamings") == 1
        papers = {paper.id: paper for paper in state.papers}
        for cluster in state.clusters:
            assert [item.facet for item in cluster.facets] == FACETS
            assert all(item.paper_id for item in cluster.facets)
            assert all(
                item.paper_id in papers
                and item.sentence in (papers[item.paper_id].abstract or "")
                for item in cluster.facets
                if item.paper_id
            )

    asyncio.run(go())


def test_live_retrieval_relaxes_zero_result_prose_query() -> None:
    async def go() -> None:
        retrieval = HermeticRetrieval()
        retrieval.results["large system prompt"] = ["angle-1"]
        service = FocusedPanelService(s2=retrieval)
        query = (
            "How can a compiler identify explicit obligations relevant to a "
            "request x in a large system prompt P?"
        )
        papers, succeeded = await service._live_retrieve([query])
        assert succeeded
        assert retrieval.calls == [query, "large system prompt"]
        assert [paper.id for paper in papers] == ["angle-1"]
        assert papers[0].source_query == "large system prompt"

    asyncio.run(go())


def test_live_retrieval_surfaces_provider_failure() -> None:
    async def go() -> None:
        retrieval = HermeticRetrieval()
        provider = HermeticProvider(retrieval)
        service = FocusedPanelService(provider=provider, s2=FailingRetrieval())
        state = service.create_workspace(
            problem="How do AI writing tools affect knowledge work?",
            research_questions=[],
            demo=False,
        ).active
        state = await service.suggest_queries(state.id)
        selected = [query.query for query in state.suggested_queries]
        with pytest.raises(SessionError, match="temporarily unavailable") as error:
            await service.run_search(state.id, selected)
        assert error.value.status == 503
        assert not service.get(state.id).searched

    asyncio.run(go())


def test_empty_live_search_rolls_back_and_can_retry() -> None:
    async def go() -> None:
        retrieval = HermeticRetrieval()
        provider = HermeticProvider(retrieval)
        service = FocusedPanelService(provider=provider, s2=retrieval)
        state = service.create_workspace(
            problem="How do AI writing tools affect knowledge work?",
            research_questions=[
                "When do draft suggestions reduce output diversity?",
            ],
            demo=False,
        ).active
        state = await service.suggest_queries(state.id)
        selected = [query.query for query in state.suggested_queries]
        retrieval.results.clear()

        with pytest.raises(SessionError, match="search was not saved") as error:
            await service.run_search(state.id, selected)
        assert error.value.status == 422
        failed = service.get(state.id)
        assert not failed.searched
        assert failed.papers == []
        assert failed.searched_queries == []

        failed.searched = True
        failed.searched_queries = selected
        updated = service.update_brief(
            state.id,
            problem=state.problem,
            research_questions=state.research_questions,
        )
        assert not updated.searched
        assert updated.searched_queries == []

        updated = await service.suggest_queries(state.id)
        selected = [query.query for query in updated.suggested_queries]
        retrieval.results["ai suggestions output diversity"] = ["q-answer"]
        retried = await service.run_search(state.id, selected)
        assert retried.searched
        assert [paper.id for paper in retried.papers] == ["q-answer"]

    asyncio.run(go())


def test_automated_facet_without_abstract_grounding_is_blank() -> None:
    service = FocusedPanelService()
    paper = ExpPaper(
        id="paper",
        title="Grounded paper",
        abstract="The abstract establishes a narrow population boundary.",
        abstract_sentences=["The abstract establishes a narrow population boundary."],
    )
    bad_source = service._validate_facet_source(
        FacetEvidence(
            facet="scope",
            text="Unsupported population claim",
            paper_id="ghost",
        ),
        {paper.id: paper},
    )
    assert bad_source.text == ""
    assert bad_source.paper_id is None

    bad_text = service._validate_facet_source(
        FacetEvidence(
            facet="scope",
            text="A fabricated statement with unrelated vocabulary",
            paper_id=paper.id,
            sentence_index=99,
        ),
        {paper.id: paper},
    )
    assert bad_text.text == ""
    assert bad_text.sentence_index is None

    researcher_edit = service._validate_facet_source(
        FacetEvidence(
            facet="scope",
            text="Researcher-authored boundary",
            paper_id=paper.id,
            edited=True,
        ),
        {paper.id: paper},
    )
    assert researcher_edit.text == "Researcher-authored boundary"
    assert researcher_edit.paper_id is None


def test_metric_failure_is_explicitly_unavailable() -> None:
    async def go() -> None:
        service = FocusedPanelService(provider=FailingEmbedder())
        state = service.create_workspace(
            problem="A metric test",
            research_questions=[],
            demo=False,
        ).active
        snapshot = {
            1: {facet: "first account" for facet in FACETS},
            2: {facet: "second account" for facet in FACETS},
        }
        metrics = await service._round_metrics(
            service._require(state.id),
            snapshot,
            snapshot,
        )
        assert metrics.method == "unavailable:embedding-failed"
        assert metrics.direction == "insufficient"
        assert metrics.before == []
        assert metrics.after == []

    asyncio.run(go())


def test_citation_filter_accepts_only_known_allowed_sources() -> None:
    state = (
        FocusedPanelService()
        .create_workspace(
            problem="Citation filter",
            research_questions=[],
            demo=True,
        )
        .active
    )
    state.papers = [
        ExpPaper(id="p1", title="Allowed paper"),
        ExpPaper(id="p2", title="Other paper"),
    ]
    citations = FocusedPanelService._canonical_citations(
        state,
        ["Allowed paper", "p2", "ghost"],
        {"p1"},
    )
    assert citations == ["p1"]


def test_focused_retrieval_uses_one_full_paper_search() -> None:
    class FullPaperClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        async def search_papers(self, query: str, *, limit: int) -> list[Paper]:
            self.calls.append((query, limit))
            return [
                Paper(
                    source_id="42",
                    paper_id="paper-42",
                    s2_corpus_id="42",
                    title="Meal timing and insulin sensitivity",
                    abstract="Earlier meals improved insulin sensitivity.",
                    tldr="Meal timing changed metabolic outcomes.",
                    year=2025,
                    venue="Metabolism",
                    authors=["Ada Researcher"],
                    specter_v2=[0.1, 0.2],
                )
            ]

    async def go() -> None:
        client = FullPaperClient()
        retrieval = FocusedSemanticScholar(client)
        papers = await retrieval.search("meal timing", limit=5)

        assert client.calls == [("meal timing", 5)]
        assert len(papers) == 1
        assert papers[0].id == "42"
        assert papers[0].abstract == "Earlier meals improved insulin sensitivity."
        assert papers[0].authors[0].name == "Ada Researcher"
        assert papers[0].specter_v2 == [0.1, 0.2]

    asyncio.run(go())
