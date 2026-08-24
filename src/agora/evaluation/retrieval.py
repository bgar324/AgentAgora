from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Sequence
from pathlib import Path
from statistics import mean, median
from typing import Literal, Protocol

import numpy as np
from pydantic import BaseModel, Field, model_validator
from sklearn.metrics import adjusted_rand_score, silhouette_score

TARGET_CLUSTER_MIN = 20
TARGET_CLUSTER_MAX = 100
TARGET_PERSPECTIVES = 3
REPRESENTATIVE_METRIC_K = 5
QUERY_RESULT_DEPTH = 20
PERSPECTIVE_EVIDENCE_BUDGET = 5
MATCHED_DELIVERY_DEPTH = 60


class RetrievalCase(BaseModel):
    id: str = Field(min_length=1)
    problem: str = Field(min_length=3)
    research_questions: list[str] = Field(default_factory=list)
    expected_concepts: list[str] = Field(default_factory=list)
    relevant_paper_ids: list[str] = Field(default_factory=list)


class ExecutedQuery(BaseModel):
    text: str = Field(min_length=1)
    paper_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_paper_ids(self) -> ExecutedQuery:
        self.text = " ".join(self.text.split())
        self.paper_ids = list(dict.fromkeys(self.paper_ids))
        return self


class EvalPaper(BaseModel):
    id: str
    title: str
    abstract: str = ""
    embedding: list[float] | None = None


class EvalCluster(BaseModel):
    id: str
    paper_ids: list[str] = Field(default_factory=list)
    representative_ids: list[str] = Field(default_factory=list)


class EvalPerspective(BaseModel):
    cluster_id: str
    name: str
    framing: str = ""
    position: str = ""
    facets: dict[str, str] = Field(default_factory=dict)
    evidence_paper_ids: list[str] = Field(default_factory=list)


class ModelUsage(BaseModel):
    model: str
    calls: int = Field(default=0, ge=0)
    cached_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)


class PipelineTelemetry(BaseModel):
    latency_s: float = Field(default=0.0, ge=0.0)
    cache_scope: str = ""
    peak_rss_mb: float | None = Field(default=None, ge=0.0)
    retrieval_calls: int = Field(default=0, ge=0)
    cache_mode: Literal["off", "per-run", "shared", "unknown"] = "unknown"
    order_index: int = Field(default=0, ge=0)
    model_usage: list[ModelUsage] = Field(default_factory=list)

    @property
    def model_cost_usd(self) -> float | None:
        costs = [item.cost_usd for item in self.model_usage if item.cost_usd is not None]
        return sum(costs) if costs else None


class PerspectivePairScore(BaseModel):
    left_cluster_id: str
    right_cluster_id: str
    score: float = Field(ge=0.0, le=1.0)


class JudgmentProvenance(BaseModel):
    judge_model: str
    rubric_version: str
    packet_digest: str
    cache_scope: str = ""
    model_usage: list[ModelUsage] = Field(default_factory=list)

class PipelineRun(BaseModel):
    pipeline: str
    case_id: str
    repeat: int = Field(default=1, ge=1)
    queries: list[ExecutedQuery] = Field(default_factory=list)
    papers: list[EvalPaper] = Field(default_factory=list)
    clusters: list[EvalCluster] = Field(default_factory=list)
    perspectives: list[EvalPerspective] = Field(default_factory=list)
    unassigned_paper_ids: list[str] = Field(default_factory=list)
    perspective_failures: dict[str, str] = Field(default_factory=dict)
    relevance_scores: dict[str, float] = Field(default_factory=dict)
    perspective_scores: dict[str, float] = Field(default_factory=dict)
    perspective_distinctness: float | None = Field(default=None, ge=0.0, le=1.0)
    perspective_grounding_scores: dict[str, float] = Field(default_factory=dict)
    perspective_pair_scores: list[PerspectivePairScore] = Field(default_factory=list)
    query_intent_diversity: float | None = Field(default=None, ge=0.0, le=1.0)
    grounding_evidence_counts: dict[str, int] = Field(default_factory=dict)
    query_research_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    judgment: JudgmentProvenance | None = None
    telemetry: PipelineTelemetry = Field(default_factory=PipelineTelemetry)

    @model_validator(mode="after")
    def validate_graph(self) -> PipelineRun:
        paper_ids = [paper.id for paper in self.papers]
        if len(set(paper_ids)) != len(paper_ids):
            raise ValueError("paper IDs must be unique within a run")
        known = set(paper_ids)
        assigned: set[str] = set()
        cluster_ids: set[str] = set()
        for cluster in self.clusters:
            if cluster.id in cluster_ids:
                raise ValueError("cluster IDs must be unique within a run")
            cluster_ids.add(cluster.id)
            members = set(cluster.paper_ids)
            if len(members) != len(cluster.paper_ids):
                raise ValueError("a cluster cannot contain one paper twice")
            if not members <= known:
                raise ValueError("a cluster references an unknown paper")
            if assigned & members:
                raise ValueError("a paper cannot belong to two clusters")
            assigned.update(members)
            if not set(cluster.representative_ids) <= members:
                raise ValueError("representatives must belong to their cluster")
        unassigned = set(self.unassigned_paper_ids)
        if not unassigned <= known:
            raise ValueError("unassigned IDs must reference retrieved papers")
        if assigned & unassigned:
            raise ValueError("a paper cannot be assigned and unassigned")
        if assigned | unassigned != known:
            raise ValueError("every retrieved paper must be assigned or unassigned")
        if not set(self.relevance_scores) <= known:
            raise ValueError("relevance scores must reference retrieved papers")
        if any(not 0.0 <= score <= 1.0 for score in self.relevance_scores.values()):
            raise ValueError("relevance scores must be between zero and one")
        if not set(self.perspective_scores) <= cluster_ids:
            raise ValueError("perspective scores must reference known clusters")
        if any(
            not 0.0 <= score <= 1.0 for score in self.perspective_scores.values()
        ):
            raise ValueError("perspective scores must be between zero and one")
        if not set(self.perspective_grounding_scores) <= cluster_ids:
            raise ValueError("grounding scores must reference known clusters")
        if any(
            not 0.0 <= score <= 1.0
            for score in self.perspective_grounding_scores.values()
        ):
            raise ValueError("grounding scores must be between zero and one")
        seen_pairs: set[frozenset[str]] = set()
        for pair in self.perspective_pair_scores:
            members = frozenset({pair.left_cluster_id, pair.right_cluster_id})
            if len(members) != 2 or not members <= cluster_ids:
                raise ValueError("Perspective pairs must reference two known clusters")
            if members in seen_pairs:
                raise ValueError("Perspective pairs must be unique")
            seen_pairs.add(members)
        if not set(self.grounding_evidence_counts) <= cluster_ids:
            raise ValueError("grounding evidence counts must reference known clusters")
        if any(count < 0 for count in self.grounding_evidence_counts.values()):
            raise ValueError("grounding evidence counts cannot be negative")
        perspective_clusters = [item.cluster_id for item in self.perspectives]
        if len(set(perspective_clusters)) != len(perspective_clusters):
            raise ValueError("a cluster can produce only one Perspective")
        if not set(perspective_clusters) <= cluster_ids:
            raise ValueError("a Perspective must reference a known cluster")
        failed_clusters = set(self.perspective_failures)
        if not failed_clusters <= cluster_ids:
            raise ValueError("Perspective failures must reference known clusters")
        if failed_clusters & set(perspective_clusters):
            raise ValueError("a cluster cannot both form and fail a Perspective")
        for perspective in self.perspectives:
            cluster = next(
                item for item in self.clusters if item.id == perspective.cluster_id
            )
            if not set(perspective.evidence_paper_ids) <= set(cluster.paper_ids):
                raise ValueError("Perspective evidence must belong to its cluster")
        dimensions = {
            len(paper.embedding)
            for paper in self.papers
            if paper.embedding is not None
        }
        if len(dimensions) > 1:
            raise ValueError("paper embeddings must share one dimension")
        return self


class RunScore(BaseModel):
    pipeline: str
    case_id: str
    matched_delivered_relevance_mean: float | None = None
    matched_delivery_depth: int = 0
    repeat: int
    retrieved_papers: int
    relevance_mean: float | None = None
    relevance_precision: float | None = None
    relevant_papers_retrieved: float | None = None
    delivered_relevance_mean: float | None = None
    relevant_papers_delivered: float | None = None
    retained_relevance_recall: float | None = None
    filter_lift: float | None = None
    discarded_papers: int = 0
    gold_recall: float | None = None
    delivered_gold_recall: float | None = None
    perspective_quality: float | None = None
    perspective_distinctness: float | None = None
    perspective_grounding: float | None = None
    perspective_coverage: float | None = None
    evidence_coverage: float | None = None
    query_diversity: float | None = None
    query_intent_diversity: float | None = None
    query_research_coverage: float | None = None
    retrieval_intent_diversity: float | None = None
    corpus_expansion: float | None = None
    executed_queries: int = 0
    unique_queries: int = 0
    query_terms_mean: float | None = None
    cluster_count: int
    cluster_sizes: list[int]
    cluster_size_mean: float | None = None
    cluster_size_median: float | None = None
    evidence_size_conformance: float | None = None
    assigned_fraction: float | None = None
    silhouette: float | None = None
    balanced_silhouette: float | None = None
    balanced_silhouette_clusters: int = 0
    balanced_silhouette_papers_per_cluster: int = 0
    representative_centrality: float | None = None
    representative_diversity: float | None = None
    representative_centrality_at_5: float | None = None
    representative_diversity_at_5: float | None = None
    latency_s: float
    peak_rss_mb: float | None = None
    retrieval_calls: int
    model_cost_usd: float | None = None
    cached_model_calls: int = 0
    cache_mode: Literal["off", "per-run", "shared", "unknown"] = "unknown"


class PipelineSummary(BaseModel):
    pipeline: str
    matched_delivered_relevance_mean: float | None = None
    matched_delivery_depth: float | None = None
    runs: int
    relevance_mean: float | None = None
    relevance_precision: float | None = None
    relevant_papers_retrieved: float | None = None
    delivered_relevance_mean: float | None = None
    relevant_papers_delivered: float | None = None
    retained_relevance_recall: float | None = None
    filter_lift: float | None = None
    discarded_papers: float | None = None
    gold_recall: float | None = None
    delivered_gold_recall: float | None = None
    perspective_quality: float | None = None
    perspective_distinctness: float | None = None
    perspective_grounding: float | None = None
    perspective_coverage: float | None = None
    evidence_coverage: float | None = None
    query_diversity: float | None = None
    query_intent_diversity: float | None = None
    query_research_coverage: float | None = None
    retrieval_intent_diversity: float | None = None
    corpus_expansion: float | None = None
    executed_queries: float | None = None
    unique_queries: float | None = None
    query_terms_mean: float | None = None
    cluster_count_mean: float | None = None
    cluster_size_mean: float | None = None
    evidence_size_conformance: float | None = None
    assigned_fraction: float | None = None
    silhouette: float | None = None
    balanced_silhouette: float | None = None
    representative_centrality: float | None = None
    representative_diversity: float | None = None
    representative_centrality_at_5: float | None = None
    representative_diversity_at_5: float | None = None
    cluster_stability: float | None = None
    corpus_stability: float | None = None
    assigned_stability: float | None = None
    cluster_stability_support: float | None = None
    latency_s: float | None = None
    peak_rss_mb: float | None = None
    retrieval_calls: float | None = None
    model_cost_usd: float | None = None


class MetricComparability(BaseModel):
    status: Literal["comparable", "provisional", "inadmissible"]
    reason: str | None = None


class RetrievalComparison(BaseModel):
    cases: list[RetrievalCase]
    runs: list[PipelineRun]
    scores: list[RunScore]
    summaries: list[PipelineSummary]
    comparability: dict[str, MetricComparability] = Field(default_factory=dict)

    def write_json(
        self,
        path: str | Path,
        *,
        include_embeddings: bool = False,
    ) -> None:
        exclude = (
            None
            if include_embeddings
            else {
                "runs": {
                    "__all__": {
                        "papers": {"__all__": {"abstract", "embedding"}}
                    }
                }
            }
        )
        Path(path).write_text(
            self.model_dump_json(indent=2, exclude=exclude),
            encoding="utf-8",
        )


class RetrievalPipeline(Protocol):
    name: str

    async def run(self, case: RetrievalCase, *, repeat: int) -> PipelineRun: ...


class RetrievalJudge(Protocol):
    async def judge(
        self,
        case: RetrievalCase,
        runs: Sequence[PipelineRun],
    ) -> list[PipelineRun]: ...


def load_cases(path: str | Path) -> list[RetrievalCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [RetrievalCase.model_validate(item) for item in payload]


def load_runs(paths: Sequence[str | Path]) -> list[PipelineRun]:
    runs: list[PipelineRun] = []
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        items = payload if isinstance(payload, list) else payload.get("runs", [])
        runs.extend(PipelineRun.model_validate(item) for item in items)
    return runs


def _content_terms(text: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.casefold())
        if len(term) > 2
    }


def _query_diversity(queries: Sequence[ExecutedQuery]) -> float | None:
    terms = [_content_terms(query.text) for query in queries if query.text.strip()]
    if len(terms) < 2:
        return None
    distances = []
    for index, left in enumerate(terms):
        for right in terms[index + 1 :]:
            union = left | right
            distances.append(1.0 - len(left & right) / len(union) if union else 0.0)
    return mean(distances) if distances else None

def _query_result_metrics(
    queries: Sequence[ExecutedQuery],
    *,
    depth: int = 20,
) -> tuple[float | None, float | None, int]:
    by_text: dict[str, set[str]] = {}
    for query in queries:
        key = " ".join(re.findall(r"\w+", query.text.casefold()))
        if not key:
            continue
        by_text.setdefault(key, set()).update(query.paper_ids[:depth])
    result_sets = [paper_ids for paper_ids in by_text.values() if paper_ids]
    if not result_sets:
        return None, None, len(by_text)
    total = sum(len(paper_ids) for paper_ids in result_sets)
    expansion = len(set().union(*result_sets)) / total if total else None
    if len(result_sets) < 2:
        return None, expansion, len(by_text)
    distances = [
        1.0 - len(left & right) / len(left | right)
        for index, left in enumerate(result_sets)
        for right in result_sets[index + 1 :]
        if left | right
    ]
    return (
        mean(distances) if distances else None,
        expansion,
        len(by_text),
    )


def _normalized_embeddings(run: PipelineRun) -> tuple[list[str], np.ndarray] | None:
    embedded = [paper for paper in run.papers if paper.embedding is not None]
    if not embedded:
        return None
    matrix = np.asarray([paper.embedding for paper in embedded], dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    valid = np.isfinite(matrix).all(axis=1) & (norms[:, 0] > 0)
    if not valid.any():
        return None
    matrix = matrix[valid] / norms[valid]
    ids = [paper.id for paper, keep in zip(embedded, valid, strict=True) if keep]
    return ids, matrix


def _silhouette(run: PipelineRun) -> float | None:
    embedded = _normalized_embeddings(run)
    if embedded is None:
        return None
    ids, matrix = embedded
    labels_by_id = {
        paper_id: index
        for index, cluster in enumerate(run.clusters)
        for paper_id in cluster.paper_ids
    }
    selected = [index for index, paper_id in enumerate(ids) if paper_id in labels_by_id]
    if len(selected) < 3:
        return None
    labels = [labels_by_id[ids[index]] for index in selected]
    if len(set(labels)) < 2 or len(set(labels)) >= len(labels):
        return None
    return float(silhouette_score(matrix[selected], labels, metric="cosine"))


def _representative_scores(
    run: PipelineRun,
    *,
    limit: int | None = None,
) -> tuple[float | None, float | None]:
    embedded = _normalized_embeddings(run)
    if embedded is None:
        return None, None
    ids, matrix = embedded
    by_id = {paper_id: matrix[index] for index, paper_id in enumerate(ids)}
    centralities: list[float] = []
    diversities: list[float] = []
    for cluster in run.clusters:
        members = [by_id[paper_id] for paper_id in cluster.paper_ids if paper_id in by_id]
        representative_ids = (
            cluster.representative_ids
            if limit is None
            else cluster.representative_ids[:limit]
        )
        reps = [
            by_id[paper_id]
            for paper_id in representative_ids
            if paper_id in by_id
        ]
        if members and reps:
            centroid = np.mean(np.asarray(members), axis=0)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid /= norm
                centralities.extend(float(rep @ centroid) for rep in reps)
        if len(reps) > 1:
            for index, left in enumerate(reps):
                diversities.extend(
                    1.0 - float(np.clip(left @ right, -1.0, 1.0))
                    for right in reps[index + 1 :]
                )
    return (
        mean(centralities) if centralities else None,
        mean(diversities) if diversities else None,
    )


def _selected_perspectives_for_score(run: PipelineRun) -> list[EvalPerspective]:
    cluster_sizes = {cluster.id: len(cluster.paper_ids) for cluster in run.clusters}
    return sorted(
        run.perspectives,
        key=lambda item: (-cluster_sizes.get(item.cluster_id, 0), item.cluster_id),
    )[:TARGET_PERSPECTIVES]


def score_run(case: RetrievalCase, run: PipelineRun) -> RunScore:
    relevance = list(run.relevance_scores.values())
    relevant_ids = set(case.relevant_paper_ids)
    retrieved_ids = {paper.id for paper in run.papers}
    sizes = [len(cluster.paper_ids) for cluster in run.clusters]
    assigned = {paper_id for cluster in run.clusters for paper_id in cluster.paper_ids}
    assigned_relevance = [
        run.relevance_scores[paper_id]
        for paper_id in assigned
        if paper_id in run.relevance_scores
    ]
    relevance_mean = mean(relevance) if relevance else None
    delivered_relevance_mean = (
        mean(assigned_relevance) if assigned_relevance else None
    )
    relevant_papers_retrieved = sum(relevance) if relevance else None
    relevant_papers_delivered = (
        sum(assigned_relevance) if assigned_relevance else None
    )
    retained_relevance_recall = (
        relevant_papers_delivered / relevant_papers_retrieved
        if relevant_papers_delivered is not None
        and relevant_papers_retrieved is not None
        and relevant_papers_retrieved > 0
        else None
    )
    discarded_papers = len(run.papers) - len(assigned)
    filter_lift = (
        delivered_relevance_mean / relevance_mean
        if discarded_papers > 0
        and delivered_relevance_mean is not None
        and relevance_mean is not None
        and relevance_mean > 0
        else None
    )
    perspective_slots = TARGET_PERSPECTIVES
    perspective_quality = (
        sum(run.perspective_scores.values()) / perspective_slots
        if perspective_slots
        else None
    )
    perspective_grounding = (
        sum(run.perspective_grounding_scores.values()) / perspective_slots
        if perspective_slots
        else None
    )
    perspective_coverage = (
        len(run.perspective_scores) / perspective_slots
        if perspective_slots
        else None
    )
    declared_evidence = sum(
        bool(perspective.evidence_paper_ids)
        for perspective in _selected_perspectives_for_score(run)
    )
    evidence_coverage = (
        declared_evidence / perspective_slots if perspective_slots else None
    )
    lexical_diversity = _query_diversity(run.queries)
    result_diversity, corpus_expansion, unique_queries = _query_result_metrics(
        run.queries,
        depth=QUERY_RESULT_DEPTH,
    )
    query_term_counts = [
        len(_content_terms(query.text)) for query in run.queries if query.text.strip()
    ]
    centrality, diversity = _representative_scores(run)
    centrality_at_5, diversity_at_5 = _representative_scores(
        run,
        limit=REPRESENTATIVE_METRIC_K,
    )
    cached_model_calls = sum(
        usage.cached_calls for usage in run.telemetry.model_usage
    )
    return RunScore(
        pipeline=run.pipeline,
        case_id=run.case_id,
        repeat=run.repeat,
        retrieved_papers=len(run.papers),
        relevance_mean=relevance_mean,
        relevance_precision=(
            sum(score >= 0.5 for score in relevance) / len(relevance)
            if relevance
            else None
        ),
        relevant_papers_retrieved=relevant_papers_retrieved,
        delivered_relevance_mean=delivered_relevance_mean,
        relevant_papers_delivered=relevant_papers_delivered,
        retained_relevance_recall=retained_relevance_recall,
        filter_lift=filter_lift,
        discarded_papers=discarded_papers,
        gold_recall=(
            len(relevant_ids & retrieved_ids) / len(relevant_ids)
            if relevant_ids
            else None
        ),
        delivered_gold_recall=(
            len(relevant_ids & assigned) / len(relevant_ids)
            if relevant_ids
            else None
        ),
        perspective_quality=perspective_quality,
        perspective_distinctness=run.perspective_distinctness,
        perspective_grounding=perspective_grounding,
        perspective_coverage=perspective_coverage,
        evidence_coverage=evidence_coverage,
        query_diversity=lexical_diversity,
        query_intent_diversity=run.query_intent_diversity,
        query_research_coverage=run.query_research_coverage,
        retrieval_intent_diversity=result_diversity,
        corpus_expansion=corpus_expansion,
        executed_queries=len(run.queries),
        unique_queries=unique_queries,
        query_terms_mean=mean(query_term_counts) if query_term_counts else None,
        cluster_count=len(run.clusters),
        cluster_sizes=sizes,
        cluster_size_mean=mean(sizes) if sizes else None,
        cluster_size_median=median(sizes) if sizes else None,
        evidence_size_conformance=(
            sum(TARGET_CLUSTER_MIN <= size <= TARGET_CLUSTER_MAX for size in sizes)
            / len(sizes)
            if sizes
            else None
        ),
        assigned_fraction=len(assigned) / len(run.papers) if run.papers else None,
        silhouette=_silhouette(run),
        representative_centrality=centrality,
        representative_diversity=diversity,
        representative_centrality_at_5=centrality_at_5,
        representative_diversity_at_5=diversity_at_5,
        latency_s=run.telemetry.latency_s,
        peak_rss_mb=run.telemetry.peak_rss_mb,
        retrieval_calls=run.telemetry.retrieval_calls,
        model_cost_usd=run.telemetry.model_cost_usd,
        cached_model_calls=cached_model_calls,
        cache_mode=run.telemetry.cache_mode,
    )


def _balanced_silhouettes(
    runs: Sequence[PipelineRun],
) -> dict[tuple[str, str, int], tuple[float, int, int]]:
    if len(runs) < 2:
        return {}
    cluster_count = min(
        TARGET_PERSPECTIVES,
        *(len(run.clusters) for run in runs),
    )
    if cluster_count < 2:
        return {}
    selected: dict[tuple[str, str, int], list[EvalCluster]] = {
        (run.pipeline, run.case_id, run.repeat): sorted(
            run.clusters,
            key=lambda cluster: (-len(cluster.paper_ids), cluster.id),
        )[:cluster_count]
        for run in runs
    }
    embedded_by_run: dict[tuple[str, str, int], dict[str, np.ndarray]] = {}
    available_counts: list[int] = []
    for run in runs:
        key = (run.pipeline, run.case_id, run.repeat)
        embedded = _normalized_embeddings(run)
        if embedded is None:
            return {}
        ids, matrix = embedded
        by_id = {paper_id: matrix[index] for index, paper_id in enumerate(ids)}
        embedded_by_run[key] = by_id
        available_counts.extend(
            sum(paper_id in by_id for paper_id in cluster.paper_ids)
            for cluster in selected[key]
        )
    papers_per_cluster = min(20, *available_counts)
    if papers_per_cluster < 2:
        return {}
    result: dict[tuple[str, str, int], tuple[float, int, int]] = {}
    for run in runs:
        key = (run.pipeline, run.case_id, run.repeat)
        by_id = embedded_by_run[key]
        sample: list[np.ndarray] = []
        labels: list[int] = []
        for label, cluster in enumerate(selected[key]):
            members = [
                (paper_id, by_id[paper_id])
                for paper_id in cluster.paper_ids
                if paper_id in by_id
            ]
            members.sort(
                key=lambda item: hashlib.sha256(
                    f"{run.case_id}:{run.repeat}:{run.pipeline}:"
                    f"{cluster.id}:{item[0]}".encode()
                ).digest()
            )
            sample.extend(vector for _, vector in members[:papers_per_cluster])
            labels.extend([label] * papers_per_cluster)
        score = float(
            silhouette_score(np.asarray(sample), labels, metric="cosine")
        )
        result[key] = (score, cluster_count, papers_per_cluster)
    return result


def _optional_mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None and math.isfinite(value)]
    return mean(present) if present else None


def _stability_metrics(
    runs: Sequence[PipelineRun],
) -> tuple[float | None, float | None, float | None, float | None]:
    corpus_by_case: list[float] = []
    assigned_by_case: list[float] = []
    partition_by_case: list[float] = []
    support_by_case: list[float] = []
    for case_id in sorted({run.case_id for run in runs}):
        case_runs = [run for run in runs if run.case_id == case_id]
        corpus_pairs: list[float] = []
        assigned_pairs: list[float] = []
        partition_pairs: list[float] = []
        support_pairs: list[float] = []
        for index, left in enumerate(case_runs):
            left_papers = {paper.id for paper in left.papers}
            left_labels = {
                paper_id: label
                for label, cluster in enumerate(left.clusters)
                for paper_id in cluster.paper_ids
            }
            for right in case_runs[index + 1 :]:
                if left.repeat == right.repeat:
                    continue
                right_papers = {paper.id for paper in right.papers}
                right_labels = {
                    paper_id: label
                    for label, cluster in enumerate(right.clusters)
                    for paper_id in cluster.paper_ids
                }
                paper_union = left_papers | right_papers
                if paper_union:
                    corpus_pairs.append(
                        len(left_papers & right_papers) / len(paper_union)
                    )
                assigned_union = set(left_labels) | set(right_labels)
                if assigned_union:
                    assigned_pairs.append(
                        len(set(left_labels) & set(right_labels))
                        / len(assigned_union)
                    )
                common = sorted(set(left_labels) & set(right_labels))
                support = len(common)
                enough_overlap = (
                    support >= 30
                    and support
                    >= 0.25 * min(len(left_labels), len(right_labels))
                )
                independent = (
                    left.telemetry.cache_mode in {"off", "per-run"}
                    and right.telemetry.cache_mode in {"off", "per-run"}
                    and not any(
                        usage.cached_calls
                        for run in (left, right)
                        for usage in run.telemetry.model_usage
                    )
                )
                if enough_overlap and independent:
                    partition_pairs.append(
                        float(
                            adjusted_rand_score(
                                [left_labels[paper_id] for paper_id in common],
                                [right_labels[paper_id] for paper_id in common],
                            )
                        )
                    )
                    support_pairs.append(float(support))
        if corpus_pairs:
            corpus_by_case.append(mean(corpus_pairs))
        if assigned_pairs:
            assigned_by_case.append(mean(assigned_pairs))
        if partition_pairs:
            partition_by_case.append(mean(partition_pairs))
            support_by_case.append(mean(support_pairs))
    return (
        mean(corpus_by_case) if corpus_by_case else None,
        mean(assigned_by_case) if assigned_by_case else None,
        mean(partition_by_case) if partition_by_case else None,
        mean(support_by_case) if support_by_case else None,
    )


def score_runs(
    cases: Sequence[RetrievalCase],
    runs: Sequence[PipelineRun],
) -> RetrievalComparison:
    by_case = {case.id: case for case in cases}
    for run in runs:
        case = by_case.get(run.case_id)
        if case is None:
            raise ValueError(f"run references unknown case: {run.case_id}")
        if not run.relevance_scores and not case.relevant_paper_ids:
            raise ValueError(
                "each run needs blinded relevance judgments or curated gold IDs"
            )
        if run.relevance_scores and set(run.relevance_scores) != {
            paper.id for paper in run.papers
        }:
            raise ValueError("relevance judgments must cover every retrieved paper")
        if run.perspectives and not run.perspective_scores:
            raise ValueError("Perspective outputs need blinded quality judgments")
        if run.perspective_scores and not run.perspective_grounding_scores:
            raise ValueError("Perspective outputs need blinded grounding judgments")
        if run.telemetry.cache_mode in {"off", "per-run"} and any(
            usage.cached_calls for usage in run.telemetry.model_usage
        ):
            raise ValueError("independent evaluation cannot contain cached model calls")

    scores = [score_run(by_case[run.case_id], run) for run in runs]
    for case_id in sorted({run.case_id for run in runs}):
        repeats = sorted(
            {run.repeat for run in runs if run.case_id == case_id}
        )
        for repeat in repeats:
            group = [
                run
                for run in runs
                if run.case_id == case_id and run.repeat == repeat
            ]
            balanced = _balanced_silhouettes(group)
            assigned_by_run = {
                (run.pipeline, run.case_id, run.repeat): {
                    paper_id
                    for cluster in run.clusters
                    for paper_id in cluster.paper_ids
                }
                for run in group
            }
            matched_depth = min(
                MATCHED_DELIVERY_DEPTH,
                *(len(paper_ids) for paper_ids in assigned_by_run.values()),
            )
            score_by_key = {
                (score.pipeline, score.case_id, score.repeat): score
                for score in scores
            }
            for run in group:
                key = (run.pipeline, run.case_id, run.repeat)
                sample = sorted(
                    assigned_by_run[key],
                    key=lambda paper_id: hashlib.sha256(
                        f"{case_id}:{repeat}:{run.pipeline}:{paper_id}".encode()
                    ).digest(),
                )[:matched_depth]
                values = [
                    run.relevance_scores[paper_id]
                    for paper_id in sample
                    if paper_id in run.relevance_scores
                ]
                score_by_key[key].matched_delivery_depth = matched_depth
                score_by_key[key].matched_delivered_relevance_mean = (
                    mean(values) if len(values) == matched_depth and values else None
                )
            for score in scores:
                key = (score.pipeline, score.case_id, score.repeat)
                if key not in balanced:
                    continue
                value, clusters, papers_per_cluster = balanced[key]
                score.balanced_silhouette = value
                score.balanced_silhouette_clusters = clusters
                score.balanced_silhouette_papers_per_cluster = papers_per_cluster

    def case_weighted(
        pipeline_scores: Sequence[RunScore],
        field: str,
    ) -> float | None:
        case_values = []
        for case_id in sorted({score.case_id for score in pipeline_scores}):
            value = _optional_mean(
                [
                    getattr(score, field)
                    for score in pipeline_scores
                    if score.case_id == case_id
                ]
            )
            if value is not None:
                case_values.append(value)
        return mean(case_values) if case_values else None

    pipelines = sorted({run.pipeline for run in runs})
    summaries: list[PipelineSummary] = []
    for pipeline in pipelines:
        pipeline_runs = [run for run in runs if run.pipeline == pipeline]
        pipeline_scores = [score for score in scores if score.pipeline == pipeline]
        corpus_stability, assigned_stability, partition_stability, support = (
            _stability_metrics(pipeline_runs)
        )

        def metric(
            field: str,
            selected_scores: Sequence[RunScore] = pipeline_scores,
        ) -> float | None:
            return case_weighted(selected_scores, field)

        summaries.append(
            PipelineSummary(
                pipeline=pipeline,
                runs=len(pipeline_runs),
                matched_delivered_relevance_mean=metric(
                    "matched_delivered_relevance_mean"
                ),
                matched_delivery_depth=metric("matched_delivery_depth"),
                relevance_mean=metric("relevance_mean"),
                relevance_precision=metric("relevance_precision"),
                relevant_papers_retrieved=metric("relevant_papers_retrieved"),
                delivered_relevance_mean=metric("delivered_relevance_mean"),
                relevant_papers_delivered=metric("relevant_papers_delivered"),
                retained_relevance_recall=metric("retained_relevance_recall"),
                filter_lift=metric("filter_lift"),
                discarded_papers=metric("discarded_papers"),
                gold_recall=metric("gold_recall"),
                delivered_gold_recall=metric("delivered_gold_recall"),
                perspective_quality=metric("perspective_quality"),
                perspective_distinctness=metric("perspective_distinctness"),
                perspective_grounding=metric("perspective_grounding"),
                perspective_coverage=metric("perspective_coverage"),
                evidence_coverage=metric("evidence_coverage"),
                query_diversity=metric("query_diversity"),
                query_intent_diversity=metric("query_intent_diversity"),
                query_research_coverage=metric("query_research_coverage"),
                retrieval_intent_diversity=metric(
                    "retrieval_intent_diversity"
                ),
                corpus_expansion=metric("corpus_expansion"),
                executed_queries=metric("executed_queries"),
                unique_queries=metric("unique_queries"),
                query_terms_mean=metric("query_terms_mean"),
                cluster_count_mean=metric("cluster_count"),
                cluster_size_mean=metric("cluster_size_mean"),
                evidence_size_conformance=metric("evidence_size_conformance"),
                assigned_fraction=metric("assigned_fraction"),
                silhouette=metric("silhouette"),
                balanced_silhouette=metric("balanced_silhouette"),
                representative_centrality=metric(
                    "representative_centrality"
                ),
                representative_diversity=metric(
                    "representative_diversity"
                ),
                representative_centrality_at_5=metric(
                    "representative_centrality_at_5"
                ),
                representative_diversity_at_5=metric(
                    "representative_diversity_at_5"
                ),
                cluster_stability=partition_stability,
                corpus_stability=corpus_stability,
                assigned_stability=assigned_stability,
                cluster_stability_support=support,
                latency_s=metric("latency_s"),
                peak_rss_mb=metric("peak_rss_mb"),
                retrieval_calls=metric("retrieval_calls"),
                model_cost_usd=metric("model_cost_usd"),
            )
        )

    paired_groups = [
        [
            score
            for score in scores
            if score.case_id == case_id and score.repeat == repeat
        ]
        for case_id in sorted({score.case_id for score in scores})
        for repeat in sorted(
            {score.repeat for score in scores if score.case_id == case_id}
        )
    ]
    coverage_mismatch = any(
        len(group) > 1
        and not math.isclose(
            max(score.assigned_fraction or 0.0 for score in group),
            min(score.assigned_fraction or 0.0 for score in group),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        for group in paired_groups
    )
    corpus_size_mismatch = any(
        len(group) > 1
        and min(score.retrieved_papers for score in group) > 0
        and max(score.retrieved_papers for score in group)
        / min(score.retrieved_papers for score in group)
        > 2.0
        for group in paired_groups
    )
    representative_counts = {
        min(
            (
                len(cluster.representative_ids)
                for cluster in run.clusters
                if cluster.representative_ids
            ),
            default=0,
        )
        for run in runs
    }
    delivery_size_mismatch = any(
        len(group) > 1
        and len(
            {
                score.retrieved_papers - score.discarded_papers
                for score in group
            }
        )
        > 1
        for group in paired_groups
    )
    fair_rubric = all(
        run.judgment is not None
        and run.judgment.rubric_version == "fair-v2"
        for run in runs
    )
    perspective_complete = all(
        len(run.clusters) == TARGET_PERSPECTIVES
        and len(run.perspective_scores) == TARGET_PERSPECTIVES
        and not run.perspective_failures
        for run in runs
    )
    grounding_matched = all(
        len(run.grounding_evidence_counts) == TARGET_PERSPECTIVES
        and all(
            count == PERSPECTIVE_EVIDENCE_BUDGET
            for count in run.grounding_evidence_counts.values()
        )
        for run in runs
    )
    independent = all(
        run.telemetry.cache_mode in {"off", "per-run"}
        and not any(usage.cached_calls for usage in run.telemetry.model_usage)
        for run in runs
    )
    has_gold = all(case.relevant_paper_ids for case in cases)
    cost_complete = all(
        run.telemetry.model_usage
        and all(usage.cost_usd is not None for usage in run.telemetry.model_usage)
        for run in runs
    )
    comparability = {
        "relevance_mean": MetricComparability(
            status=(
                "inadmissible"
                if corpus_size_mismatch
                else "comparable" if has_gold else "provisional"
            ),
            reason=(
                "retrieved corpus sizes differ by more than 2x"
                if corpus_size_mismatch
                else None if has_gold else "no human gold labels"
            ),
        ),
        "gold_recall": MetricComparability(
            status="comparable" if has_gold else "inadmissible",
            reason=None if has_gold else "no human gold labels",
        ),
        "delivered_gold_recall": MetricComparability(
            status="comparable" if has_gold else "inadmissible",
            reason=None if has_gold else "no human gold labels",
        ),
        "delivered_relevance_mean": MetricComparability(
            status=(
                "inadmissible"
                if delivery_size_mismatch
                else "comparable" if has_gold else "provisional"
            ),
            reason=(
                "delivered evidence counts differ by more than 10%"
                if delivery_size_mismatch
                else None if has_gold else "LLM judgments; no human gold labels"
            ),
        ),
        "matched_delivered_relevance_mean": MetricComparability(
            status="comparable" if has_gold else "provisional",
            reason=None if has_gold else "LLM judgments; no human gold labels",
        ),
        "relevant_papers_delivered": MetricComparability(
            status="comparable" if has_gold else "provisional",
            reason=None if has_gold else "LLM judgments; no human gold labels",
        ),
        "retained_relevance_recall": MetricComparability(
            status="comparable" if has_gold else "provisional",
            reason=None if has_gold else "LLM judgments; no human gold labels",
        ),
        "perspective_quality": MetricComparability(
            status=(
                "comparable"
                if fair_rubric and perspective_complete
                else "inadmissible"
            ),
            reason=(
                None
                if fair_rubric and perspective_complete
                else "legacy rubric or fewer than three formed Perspectives"
            ),
        ),
        "perspective_distinctness": MetricComparability(
            status=(
                "comparable"
                if fair_rubric and perspective_complete
                else "inadmissible"
            ),
            reason=(
                None
                if fair_rubric and perspective_complete
                else "legacy rubric or fewer than three formed Perspectives"
            ),
        ),
        "perspective_grounding": MetricComparability(
            status=(
                "comparable"
                if fair_rubric and perspective_complete and grounding_matched
                else "inadmissible"
            ),
            reason=(
                None
                if fair_rubric and perspective_complete and grounding_matched
                else (
                    "legacy evidence judging"
                    if not fair_rubric
                    else "fewer than five evidence abstracts for a Perspective"
                )
            ),
        ),
        "silhouette": MetricComparability(
            status="inadmissible" if coverage_mismatch else "comparable",
            reason="assigned coverage differs" if coverage_mismatch else None,
        ),
        "balanced_silhouette": MetricComparability(
            status=(
                "comparable"
                if all(score.balanced_silhouette is not None for score in scores)
                else "inadmissible"
            ),
            reason=(
                None
                if all(score.balanced_silhouette is not None for score in scores)
                else "insufficient matched embedded clusters"
            ),
        ),
        "representative_centrality": MetricComparability(
            status=(
                "inadmissible" if len(representative_counts) > 1 else "comparable"
            ),
            reason=(
                "representative counts differ"
                if len(representative_counts) > 1
                else None
            ),
        ),
        "representative_centrality_at_5": MetricComparability(
            status="comparable",
        ),
        "representative_diversity_at_5": MetricComparability(
            status="comparable",
        ),
        "query_diversity": MetricComparability(
            status="provisional",
            reason="lexical Jaccard rewards verbosity and anchor removal",
        ),
        "query_intent_diversity": MetricComparability(
            status="comparable" if fair_rubric else "inadmissible",
            reason=None if fair_rubric else "legacy query rubric",
        ),
        "retrieval_intent_diversity": MetricComparability(
            status="comparable",
        ),
        "evidence_size_conformance": MetricComparability(
            status="inadmissible",
            reason="product conformance only; not clustering quality",
        ),
        "cluster_stability": MetricComparability(
            status=(
                "comparable"
                if all(
                    summary.cluster_stability is not None
                    for summary in summaries
                )
                else "inadmissible"
            ),
            reason=(
                None
                if all(
                    summary.cluster_stability is not None
                    for summary in summaries
                )
                else "replayed or insufficient-overlap repeats"
            ),
        ),
        "latency_s": MetricComparability(
            status="comparable" if independent else "inadmissible",
            reason=None if independent else "warm or mixed cache modes",
        ),
        "model_cost_usd": MetricComparability(
            status="comparable" if cost_complete else "inadmissible",
            reason=(
                None
                if cost_complete
                else "provider-priced cost missing for at least one model call"
            ),
        ),
    }
    return RetrievalComparison(
        cases=list(cases),
        runs=list(runs),
        scores=scores,
        summaries=summaries,
        comparability=comparability,
    )


async def evaluate_pipelines(
    cases: Sequence[RetrievalCase],
    pipelines: Sequence[RetrievalPipeline],
    *,
    judge: RetrievalJudge | None = None,
    repeats: int = 1,
    repeat_start: int = 1,
    cache_mode: Literal["off", "per-run", "shared", "unknown"] = "unknown",
) -> RetrievalComparison:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    if repeat_start < 1:
        raise ValueError("repeat_start must be positive")

    async def execute(
        pipeline: RetrievalPipeline,
        case: RetrievalCase,
        repeat: int,
    ) -> PipelineRun:
        started = time.perf_counter()
        run = await pipeline.run(case, repeat=repeat)
        latency = time.perf_counter() - started
        if run.pipeline != pipeline.name or run.case_id != case.id:
            raise ValueError("pipeline returned a result for the wrong pipeline or case")
        if run.telemetry.cache_mode == "unknown":
            run.telemetry.cache_mode = cache_mode
        if run.repeat != repeat:
            raise ValueError("pipeline returned the wrong repeat number")
        if run.telemetry.latency_s == 0.0:
            run.telemetry.latency_s = latency
        return run

    runs: list[PipelineRun] = []
    for repeat in range(repeat_start, repeat_start + repeats):
        ordered_pipelines = list(pipelines)
        if repeat % 2 == 0:
            ordered_pipelines.reverse()
        for case in cases:
            case_runs = []
            for order_index, pipeline in enumerate(ordered_pipelines):
                run = await execute(pipeline, case, repeat)
                run.telemetry.order_index = order_index
                case_runs.append(run)
            if judge is not None:
                case_runs = await judge.judge(case, case_runs)
            for run in case_runs:
                if not run.relevance_scores and not case.relevant_paper_ids:
                    raise ValueError(
                        "each run needs blinded relevance judgments or curated gold IDs"
                    )
                if run.perspectives and not run.perspective_scores:
                    raise ValueError(
                        "Perspective outputs need blinded quality judgments"
                    )
            runs.extend(case_runs)
    return score_runs(cases, runs)
