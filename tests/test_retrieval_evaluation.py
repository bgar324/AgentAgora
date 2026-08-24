from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from agora.evaluation.judge import (
    BlindedSolJudge,
    PaperJudgment,
    PaperJudgments,
    PerspectiveGroundingJudgment,
    PerspectiveGroundingJudgments,
    PerspectiveQualityJudgment,
    PerspectiveQualityJudgments,
    QuerySetJudgment,
    QuerySetJudgments,
)
from agora.evaluation.metering import dspy_model_usage
from agora.evaluation.professor import ProfessorRetrievalPipeline
from agora.evaluation.retrieval import (
    EvalCluster,
    EvalPaper,
    EvalPerspective,
    ExecutedQuery,
    PipelineRun,
    PipelineTelemetry,
    RetrievalCase,
    evaluate_pipelines,
    load_cases,
    score_run,
    score_runs,
)
from agora.focused.models import (
    FACETS,
    ClusterCard,
    ExpPaper,
    FacetEvidence,
    FramingPosition,
    Perspective,
)
from scripts.export_retrieval_gold_pool import build_pool


def paper(paper_id: str, x: float, y: float) -> EvalPaper:
    return EvalPaper(
        id=paper_id,
        title=f"Paper {paper_id}",
        abstract=f"Evidence from {paper_id}",
        embedding=[x, y],
    )

def query(text: str, *paper_ids: str) -> ExecutedQuery:
    return ExecutedQuery(text=text, paper_ids=list(paper_ids))



def test_scores_both_pipelines_without_collapsing_tradeoffs() -> None:
    case = RetrievalCase(
        id="hci",
        problem="How do explanations affect calibrated trust?",
        relevant_paper_ids=["p1", "p2", "p3"],
    )
    professor = PipelineRun(
        pipeline="professor",
        case_id=case.id,
        queries=[
            query("calibrated trust explanations"),
            query("automation reliance"),
        ],
        papers=[
            paper("p1", 1.0, 0.0),
            paper("p2", 0.9, 0.1),
            paper("p3", 0.0, 1.0),
            paper("p4", 0.1, 0.9),
        ],
        clusters=[
            EvalCluster(
                id="a",
                paper_ids=["p1", "p2"],
                representative_ids=["p1", "p2"],
            ),
            EvalCluster(
                id="b",
                paper_ids=["p3", "p4"],
                representative_ids=["p3", "p4"],
            ),
        ],
        perspectives=[
            EvalPerspective(
                cluster_id="a",
                name="Calibrated trust",
                evidence_paper_ids=["p1", "p2"],
            ),
            EvalPerspective(
                cluster_id="b",
                name="Reliance risks",
                evidence_paper_ids=["p3", "p4"],
            ),
        ],
        perspective_grounding_scores={"a": 0.8, "b": 0.7},
        relevance_scores={"p1": 1.0, "p2": 0.8, "p3": 0.7, "p4": 0.2},
        perspective_scores={"a": 0.9, "b": 0.8},
        perspective_distinctness=0.85,
        telemetry=PipelineTelemetry(
            latency_s=12.0,
            peak_rss_mb=220.0,
            retrieval_calls=4,
        ),
    )
    kat = PipelineRun(
        pipeline="kat",
        case_id=case.id,
        queries=[query("seed query"), query("retrieval-informed direction")],
        papers=[
            paper("p1", 1.0, 0.0),
            paper("p2", 0.9, 0.1),
            paper("p5", -1.0, 0.0),
            paper("p6", -0.9, 0.1),
        ],
        clusters=[
            EvalCluster(
                id="x",
                paper_ids=["p1", "p2"],
                representative_ids=["p1", "p2"],
            ),
            EvalCluster(
                id="y",
                paper_ids=["p5", "p6"],
                representative_ids=["p5", "p6"],
            ),
        ],
        perspectives=[
            EvalPerspective(cluster_id="x", name="Trust", evidence_paper_ids=["p1"]),
            EvalPerspective(cluster_id="y", name="Other", evidence_paper_ids=["p5"]),
        ],
        relevance_scores={"p1": 1.0, "p2": 0.8, "p5": 0.4, "p6": 0.3},
        perspective_scores={"x": 0.8, "y": 0.5},
        perspective_distinctness=0.7,
        perspective_grounding_scores={"x": 0.7, "y": 0.4},
        telemetry=PipelineTelemetry(
            latency_s=35.0,
            peak_rss_mb=680.0,
            retrieval_calls=5,
        ),
    )

    comparison = score_runs([case], [professor, kat])

    assert {summary.pipeline for summary in comparison.summaries} == {
        "professor",
        "kat",
    }
    by_pipeline = {score.pipeline: score for score in comparison.scores}
    assert by_pipeline["professor"].gold_recall == 1.0
    assert comparison.comparability["model_cost_usd"].status == "inadmissible"
    assert (
        comparison.comparability["evidence_size_conformance"].status
        == "inadmissible"
    )
    assert by_pipeline["kat"].gold_recall == pytest.approx(2 / 3)
    assert by_pipeline["professor"].matched_delivery_depth == 4
    assert by_pipeline["kat"].matched_delivery_depth == 4
    assert by_pipeline["professor"].matched_delivered_relevance_mean == pytest.approx(
        0.675
    )
    assert by_pipeline["professor"].relevance_precision == 0.75
    assert by_pipeline["kat"].relevance_precision == 0.5
    assert by_pipeline["professor"].perspective_distinctness == 0.85
    assert by_pipeline["professor"].silhouette is not None
    assert by_pipeline["professor"].representative_centrality is not None
    assert by_pipeline["professor"].representative_diversity is not None
    assert by_pipeline["professor"].perspective_quality == pytest.approx(1.7 / 3)
    assert comparison.comparability["perspective_quality"].status == "inadmissible"
    assert by_pipeline["kat"].balanced_silhouette is not None
    assert (
        by_pipeline["professor"].balanced_silhouette_papers_per_cluster
        == by_pipeline["kat"].balanced_silhouette_papers_per_cluster
    )
    assert by_pipeline["professor"].latency_s == 12.0
    assert by_pipeline["kat"].peak_rss_mb == 680.0

def test_retention_metrics_expose_relevant_papers_discarded() -> None:
    case = RetrievalCase(id="case", problem="A concrete research problem")
    run = PipelineRun(
        pipeline="kat",
        case_id=case.id,
        papers=[
            paper("p1", 1.0, 0.0),
            paper("p2", 0.9, 0.1),
            paper("p3", 0.0, 1.0),
            paper("p4", 0.1, 0.9),
        ],
        clusters=[EvalCluster(id="kept", paper_ids=["p3", "p4"])],
        unassigned_paper_ids=["p1", "p2"],
        relevance_scores={"p1": 1.0, "p2": 0.8, "p3": 0.2, "p4": 0.1},
    )

    score = score_run(case, run)

    assert score.assigned_fraction == 0.5
    assert score.relevant_papers_retrieved == pytest.approx(2.1)
    assert score.relevant_papers_delivered == pytest.approx(0.3)
    assert score.retained_relevance_recall == pytest.approx(0.3 / 2.1)
    assert score.filter_lift is not None and score.filter_lift < 1.0


def test_result_diversity_ignores_keyword_versus_prose_form() -> None:
    case = RetrievalCase(id="case", problem="A concrete research problem")

    def build(pipeline: str, queries: list[ExecutedQuery]) -> PipelineRun:
        return PipelineRun(
            pipeline=pipeline,
            case_id=case.id,
            queries=queries,
            papers=[
                paper("p1", 1.0, 0.0),
                paper("p2", 0.9, 0.1),
                paper("p3", 0.0, 1.0),
            ],
            clusters=[EvalCluster(id=f"{pipeline}-cluster", paper_ids=["p1", "p2"])],
            unassigned_paper_ids=["p3"],
            relevance_scores={"p1": 1.0, "p2": 0.8, "p3": 0.2},
        )

    terse = build(
        "terse",
        [
            query("antibiotic resistance", "p1", "p2"),
            query("patient susceptibility", "p2", "p3"),
        ],
    )
    prose = build(
        "prose",
        [
            query(
                "randomized evidence about broad spectrum antibiotic resistance",
                "p1",
                "p2",
            ),
            query(
                "observational evidence about patient pathogen susceptibility",
                "p2",
                "p3",
            ),
        ],
    )

    terse_score = score_run(case, terse)
    prose_score = score_run(case, prose)

    assert terse_score.query_diversity != prose_score.query_diversity
    assert terse_score.retrieval_intent_diversity == pytest.approx(
        prose_score.retrieval_intent_diversity
    )
    assert terse_score.corpus_expansion == pytest.approx(
        prose_score.corpus_expansion
    )



def test_cluster_stability_never_compares_different_cases() -> None:
    cases = [
        RetrievalCase(id="case-a", problem="First concrete research problem"),
        RetrievalCase(id="case-b", problem="Second concrete research problem"),
    ]
    papers = [
        paper("p1", 1.0, 0.0),
        paper("p2", 0.9, 0.1),
        paper("p3", 0.0, 1.0),
    ]
    runs = [
        PipelineRun(
            pipeline="professor",
            case_id="case-a",
            papers=papers,
            clusters=[
                EvalCluster(id="a1", paper_ids=["p1", "p2"]),
                EvalCluster(id="a2", paper_ids=["p3"]),
            ],
            relevance_scores={"p1": 1.0, "p2": 0.8, "p3": 0.7},
        ),
        PipelineRun(
            pipeline="professor",
            case_id="case-b",
            papers=papers,
            clusters=[
                EvalCluster(id="b1", paper_ids=["p1", "p3"]),
                EvalCluster(id="b2", paper_ids=["p2"]),
            ],
            relevance_scores={"p1": 1.0, "p2": 0.8, "p3": 0.7},
        ),
    ]

    comparison = score_runs(cases, runs)

    assert comparison.summaries[0].cluster_stability is None


def test_comparison_writer_omits_embeddings_by_default(tmp_path: Path) -> None:
    case = RetrievalCase(
        id="case",
        problem="A concrete research problem",
        relevant_paper_ids=["p1"],
    )
    run = PipelineRun(
        pipeline="professor",
        case_id=case.id,
        papers=[paper("p1", 1.0, 0.0)],
        clusters=[EvalCluster(id="cluster", paper_ids=["p1"])],
        relevance_scores={"p1": 1.0},
    )
    comparison = score_runs([case], [run])
    compact_path = tmp_path / "comparison.json"
    raw_path = tmp_path / "comparison.raw.json"

    comparison.write_json(compact_path)
    comparison.write_json(raw_path, include_embeddings=True)

    compact = json.loads(compact_path.read_text())
    raw = json.loads(raw_path.read_text())
    assert "embedding" not in compact["runs"][0]["papers"][0]
    assert "abstract" not in compact["runs"][0]["papers"][0]
    assert raw["runs"][0]["papers"][0]["embedding"] == [1.0, 0.0]


def test_rejects_a_paper_assigned_to_two_clusters() -> None:
    with pytest.raises(ValueError, match="two clusters"):
        PipelineRun(
            pipeline="broken",
            case_id="case",
            papers=[paper("p1", 1.0, 0.0)],
            clusters=[
                EvalCluster(id="a", paper_ids=["p1"]),
                EvalCluster(id="b", paper_ids=["p1"]),
            ],
        )


def test_dspy_metering_excludes_cache_replays() -> None:
    lm = SimpleNamespace(
        model="openai/gpt-5.6-terra",
        history=[
            {
                "model": "openai/gpt-5.6-terra",
                "usage": {"input_tokens": 100, "output_tokens": 20},
                "cost": 0.02,
                "response": SimpleNamespace(cache_hit=False),
            },
            {
                "model": "openai/gpt-5.6-terra",
                "usage": {},
                "cost": 0.02,
                "response": SimpleNamespace(cache_hit=True),
            },
        ],
    )

    usage = dspy_model_usage([(lm, 0)])

    assert len(usage) == 1
    assert usage[0].calls == 1
    assert usage[0].cached_calls == 1
    assert usage[0].input_tokens == 100
    assert usage[0].output_tokens == 20
    assert usage[0].cost_usd == 0.02

def test_gold_pool_is_blind_and_unions_assigned_papers() -> None:
    case = RetrievalCase(id="case", problem="A concrete research problem")
    first = PipelineRun(
        pipeline="professor",
        case_id=case.id,
        papers=[paper("p1", 1.0, 0.0), paper("p2", 0.0, 1.0)],
        clusters=[EvalCluster(id="a", paper_ids=["p1"])],
        unassigned_paper_ids=["p2"],
    )
    second = PipelineRun(
        pipeline="kat",
        case_id=case.id,
        papers=[paper("p2", 0.0, 1.0), paper("p3", -1.0, 0.0)],
        clusters=[EvalCluster(id="b", paper_ids=["p2"])],
        unassigned_paper_ids=["p3"],
    )

    rows, mapping = build_pool([case], [first, second], depth_per_run=1)

    assert {item["paper_id"] for item in mapping.values()} == {"p1", "p2"}
    assert all("pipeline" not in row for row in rows)
    assert all(row["relevance_0_to_4"] == "" for row in rows)
    assert all(row["alias"] in mapping for row in rows)
    with pytest.raises(ValueError, match="gold depth requires 3"):
        build_pool([case], [first, second], depth_per_run=3)



def test_acceptance_gate_requires_relevance_judgments() -> None:
    case = RetrievalCase(id="case", problem="A concrete research problem")
    run = PipelineRun(pipeline="professor", case_id=case.id)
    with pytest.raises(ValueError, match="blinded relevance"):
        score_runs([case], [run])


def test_measurement_runs_execute_serially() -> None:
    class RecordingPipeline:
        def __init__(self, name: str, shared: dict[str, int]) -> None:
            self.name = name
            self.shared = shared

        async def run(self, case: RetrievalCase, *, repeat: int) -> PipelineRun:
            self.shared["active"] += 1
            self.shared["maximum"] = max(
                self.shared["maximum"], self.shared["active"]
            )
            await asyncio.sleep(0)
            self.shared["active"] -= 1
            return PipelineRun(
                pipeline=self.name,
                case_id=case.id,
                repeat=repeat,
            )

    async def go() -> None:
        shared = {"active": 0, "maximum": 0}
        pipelines = [
            RecordingPipeline("professor", shared),
            RecordingPipeline("kat", shared),
        ]
        cases = [
            RetrievalCase(
                id="one",
                problem="First research problem",
                relevant_paper_ids=["gold-one"],
            ),
            RetrievalCase(
                id="two",
                problem="Second research problem",
                relevant_paper_ids=["gold-two"],
            ),
        ]
        comparison = await evaluate_pipelines(cases, pipelines, repeats=2)
        assert shared["maximum"] == 1
        assert len(comparison.runs) == 8

    asyncio.run(go())


def test_fixed_problem_set_loads() -> None:
    cases = load_cases(Path("evals/retrieval_cases.json"))
    assert len(cases) == 5
    assert cases[0].id == "hci-decision-transparency"
    assert all(case.expected_concepts for case in cases)

def test_professor_adapter_judges_formed_perspectives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def facets_for(paper_id: str) -> list[FacetEvidence]:
        return [
            FacetEvidence(
                facet=facet,
                text=f"Grounded {facet}",
                paper_id=paper_id,
                sentence_index=0,
            )
            for facet in FACETS
        ]

    state = SimpleNamespace(
        id="workspace",
        suggested_queries=[SimpleNamespace(query="query")],
        papers=[
            ExpPaper(
                id=f"p{index}",
                title=f"Paper {index}",
                abstract="Grounded evidence.",
                specter_v2=[float(index), 1.0],
            )
            for index in range(1, 5)
        ],
        clusters=[
            ClusterCard(
                id=f"cluster-{index}",
                name=f"Cluster card {index}",
                blurb="A descriptive cluster blurb.",
                facets=facets_for(f"p{index}"),
                paper_ids=[f"p{index}"],
                representative_paper_ids=[f"p{index}"],
            )
            for index in range(1, 5)
        ],
        perspectives=[],
    )

    class FakeService:
        def __init__(self, **_):
            self.state = state
            assert _["retain_search_embeddings"] is True

        def create_workspace(self, **_):
            return SimpleNamespace(active=self.state)

        async def suggest_queries(self, _):
            return self.state

        async def run_search(self, *_):
            return self.state

        async def generate_perspective(self, _, *, cluster_id):
            paper_id = f"p{cluster_id.rsplit('-', 1)[-1]}"
            facets = facets_for(paper_id)
            self.state.perspectives.append(
                Perspective(
                    id=f"perspective-{paper_id}",
                    name="Formed Perspective",
                    color="#000000",
                    facets={facet.facet: facet for facet in facets},
                    sources=[paper_id],
                    origin=cluster_id,
                    framing=FramingPosition(
                        framing="A scientific framing.",
                        position="A testable position.",
                    ),
                )
            )
            return self.state

    monkeypatch.setattr(
        "agora.evaluation.professor.FocusedPanelService",
        FakeService,
    )
    pipeline = ProfessorRetrievalPipeline(
        provider=SimpleNamespace(set_cache_scope=lambda _scope: None),
        retrieval=SimpleNamespace(),
    )

    run = asyncio.run(
        pipeline.run(
            RetrievalCase(id="case", problem="A concrete research problem"),
            repeat=1,
        )
    )

    assert run.perspectives[0].name == "Formed Perspective"
    assert run.perspectives[0].framing == "A scientific framing."
    assert run.perspectives[0].position == "A testable position."
    assert run.perspectives[0].evidence_paper_ids == ["p1"]
    assert run.clusters[0].representative_ids == ["p1"]
    assert len(run.clusters) == 3
    assert run.telemetry.cache_scope
    assert run.unassigned_paper_ids == ["p4"]



def test_blinded_judge_normalizes_and_pools_acceptance_scores() -> None:
    class FakeLLM:
        def __init__(self) -> None:
            self.prompts: list[tuple[type, str]] = []

        async def generate_structured(self, *, messages, schema, **_):
            prompt = "\n".join(message["content"] for message in messages)
            self.prompts.append((schema, prompt))
            assert "professor" not in prompt.casefold()
            assert re.search(r"\bkat\b", prompt, re.IGNORECASE) is None
            assert "cluster-1" not in prompt
            if schema is PaperJudgments:
                aliases = re.findall(r"^\[(D\d+)\]", prompt, re.MULTILINE)
                parsed = PaperJudgments(
                    papers=[
                        PaperJudgment(alias=alias, relevance=4) for alias in aliases
                    ]
                )
            elif schema is PerspectiveQualityJudgments:
                aliases = sorted(set(re.findall(r"\[(V\d+)\]", prompt)))
                parsed = PerspectiveQualityJudgments(
                    perspectives=[
                        PerspectiveQualityJudgment(
                            alias=alias,
                            coherence=0.9,
                            relevance=0.8,
                            specificity=0.7,
                        )
                        for alias in aliases
                    ]
                )
            elif schema is PerspectiveGroundingJudgments:
                aliases = sorted(set(re.findall(r"\[(V\d+)\]", prompt)))
                parsed = PerspectiveGroundingJudgments(
                    perspectives=[
                        PerspectiveGroundingJudgment(alias=alias, support=0.75)
                        for alias in aliases
                    ]
                )
            else:
                assert schema is QuerySetJudgments
                aliases = re.findall(r"^## SET (S\d+)", prompt, re.MULTILINE)
                parsed = QuerySetJudgments(
                    sets=[
                        QuerySetJudgment(
                            set_alias=alias,
                            intent_diversity=0.6,
                            research_coverage=0.8,
                        )
                        for alias in aliases
                    ]
                )
            return SimpleNamespace(parsed=parsed)

    async def go() -> None:
        llm = FakeLLM()
        judge = BlindedSolJudge(llm)
        case = RetrievalCase(
            id="hci",
            problem="How do explanations affect calibrated trust?",
            expected_concepts=["calibrated trust"],
        )
        run = PipelineRun(
            pipeline="professor",
            case_id=case.id,
            queries=[
                query("calibrated trust explanations"),
                query("automation reliance"),
            ],
            papers=[
                EvalPaper(
                    id="paper-real-id",
                    title="Explanation and calibrated trust",
                    abstract="Supporting evidence from a controlled study.",
                    embedding=[1.0, 0.0],
                )
            ],
            clusters=[
                EvalCluster(
                    id="cluster-1",
                    paper_ids=["paper-real-id"],
                    representative_ids=["paper-real-id"],
                )
            ],
            perspectives=[
                EvalPerspective(
                    cluster_id="cluster-1",
                    name="Trust calibration",
                    framing="Explanations should calibrate reliance.",
                    position="Match explanation detail to uncertainty.",
                    evidence_paper_ids=[],
                )
            ],
        )
        kat_run = PipelineRun(
            pipeline="kat",
            case_id=case.id,
            queries=[query("explanation reliance", "paper-real-id")],
            papers=run.papers,
            clusters=[
                EvalCluster(
                    id="cluster_deadbeef",
                    paper_ids=["paper-real-id"],
                    representative_ids=["paper-real-id"],
                )
            ],
            perspectives=[
                EvalPerspective(
                    cluster_id="cluster_deadbeef",
                    name="Reliance calibration",
                    framing="Trust depends on system reliability.",
                    position="Expose uncertainty before recommendations.",
                    evidence_paper_ids=["paper-real-id"],
                )
            ],
        )
        judged_runs = await judge.judge(case, [run, kat_run])
        judged = judged_runs[0]
        assert judged.relevance_scores == {"paper-real-id": 1.0}
        assert judged.perspective_scores["cluster-1"] == pytest.approx(0.8)
        assert judged.perspective_grounding_scores == {"cluster-1": 0.75}
        assert judged.perspective_distinctness is None
        assert judged.query_intent_diversity == 0.6
        assert judged.query_research_coverage == 0.8
        assert judged.judgment is not None
        assert judged.judgment.rubric_version == "fair-v2"
        assert judged.judgment.cache_scope
        assert judged_runs[1].relevance_scores == judged.relevance_scores
        quality_prompt = next(
            prompt
            for schema, prompt in llm.prompts
            if schema is PerspectiveQualityJudgments
        )
        grounding_prompt = next(
            prompt
            for schema, prompt in llm.prompts
            if schema is PerspectiveGroundingJudgments
        )
        paper_prompt = next(
            prompt for schema, prompt in llm.prompts if schema is PaperJudgments
        )
        assert len(re.findall(r"^\[(D\d+)\]", paper_prompt, re.MULTILINE)) == 1
        assert "Supporting evidence from a controlled study." not in quality_prompt
        assert "Supporting evidence from a controlled study." in grounding_prompt
        assert any("calibrated trust" in prompt for _, prompt in llm.prompts)

    asyncio.run(go())
