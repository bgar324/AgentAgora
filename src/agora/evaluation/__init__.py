"""Evaluation harnesses for comparing research pipelines."""

from agora.evaluation.retrieval import (
    PipelineRun,
    RetrievalCase,
    RetrievalComparison,
    RetrievalPipeline,
    evaluate_pipelines,
    score_runs,
)

__all__ = [
    "PipelineRun",
    "RetrievalCase",
    "RetrievalComparison",
    "RetrievalPipeline",
    "evaluate_pipelines",
    "score_runs",
]
