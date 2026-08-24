from __future__ import annotations

from typing import Any
from uuid import uuid4

import dspy

from agora.evaluation.metering import dspy_model_usage
from agora.evaluation.retrieval import (
    EvalCluster,
    EvalPaper,
    EvalPerspective,
    ExecutedQuery,
    PipelineRun,
    PipelineTelemetry,
    RetrievalCase,
)
from agora.panel.perspective import (
    PerspectiveFormation,
    ResearchSynthesis,
    form_profiles,
)
from agora.research.discovery import ResearchDiscovery
from agora.research.model import LiteratureModel
from agora.research.search import LiteratureSearch, RetrievalProgress
from agora.schemas.research import ClusteredLiterature, ResearchIdea


class KatRetrievalPipeline:
    """Run Kat's seed, direction, HDBSCAN, and DPP retrieval architecture."""

    name = "kat"

    def __init__(
        self,
        *,
        client: Any,
        query_lm: Any,
        reasoning_lm: Any,
        perspectives: int = 3,
    ) -> None:
        if not 1 <= perspectives <= 6:
            raise ValueError("perspectives must be between one and six")
        self._client = client
        self._query_lm = query_lm
        self._reasoning_lm = reasoning_lm
        self._perspectives = perspectives

    async def run(self, case: RetrievalCase, *, repeat: int) -> PipelineRun:
        cache_scope = uuid4().hex
        retrieval_calls = 0
        executed_queries: list[ExecutedQuery] = []
        query_history_start = len(getattr(self._query_lm, "history", []))
        reasoning_history_start = len(getattr(self._reasoning_lm, "history", []))

        async def progress(update: RetrievalProgress) -> None:
            nonlocal retrieval_calls
            if update.stage == "query_completed":
                retrieval_calls += 1
                if update.query:
                    executed_queries.append(
                        ExecutedQuery(
                            text=update.query,
                            paper_ids=list(update.source_ids),
                        )
                    )

        search = LiteratureSearch(self._client, progress=progress)
        discovery = ResearchDiscovery(search)
        idea = case.problem
        if case.research_questions:
            idea += "\n\nQuestions to preserve:\n" + "\n".join(
                f"- {question}" for question in case.research_questions
            )
        with dspy.context(lm=self._query_lm):
            prediction = await discovery.acall(
                idea=ResearchIdea(idea=idea),
                n=self._perspectives,
            )
        plan = prediction.search_plan
        run_id = uuid4().hex
        result = await search.search(
            corpus_id=f"eval-corpus-{run_id}",
            investigation_id=f"eval-{case.id}-{run_id}",
            plan=plan,
        )
        full_literature = LiteratureModel().fit(result.corpus.papers)
        kept = sorted(
            full_literature.clusters,
            key=lambda cluster: len(cluster.source_ids),
            reverse=True,
        )[: self._perspectives]
        kept_ids = {
            source_id for cluster in kept for source_id in cluster.source_ids
        }
        literature = ClusteredLiterature(
            clusters=kept,
            unassigned_source_ids=[
                paper.source_id
                for paper in result.corpus.papers
                if paper.source_id not in kept_ids
            ],
        )
        with dspy.context(lm=self._reasoning_lm):
            profiles = await form_profiles(
                question=plan.research_question.main_question,
                literature=literature,
                formation=PerspectiveFormation(),
                synthesis=ResearchSynthesis(),
            )
        papers = [
            EvalPaper(
                id=paper.source_id,
                title=paper.title,
                abstract=paper.abstract or "",
                embedding=paper.specter_v2,
            )
            for paper in result.corpus.papers
        ]
        clusters = [
            EvalCluster(
                id=cluster.id,
                paper_ids=list(cluster.source_ids),
                representative_ids=[
                    paper.source_id for paper in cluster.representatives
                ],
            )
            for cluster in literature.clusters
        ]
        perspectives = []
        for cluster in literature.clusters:
            formation = profiles[cluster.id]
            profile = formation.profile
            if profile is None:
                continue
            perspectives.append(
                EvalPerspective(
                    cluster_id=cluster.id,
                    name=profile.focus,
                    framing=profile.perspective.framing,
                    position=profile.perspective.position,
                    facets={
                        name: value
                        for name in (
                            "scope",
                            "explanation",
                            "approach",
                            "significance",
                        )
                        if (value := getattr(profile.facets, name)) is not None
                    },
                    evidence_paper_ids=[
                        paper.source_id for paper in cluster.representatives
                    ],
                )
            )
        return PipelineRun(
            pipeline=self.name,
            case_id=case.id,
            repeat=repeat,
            queries=executed_queries,
            papers=papers,
            clusters=clusters,
            perspectives=perspectives,
            unassigned_paper_ids=list(literature.unassigned_source_ids),
            telemetry=PipelineTelemetry(
                retrieval_calls=retrieval_calls,
                cache_scope=cache_scope,
                model_usage=dspy_model_usage(
                    [
                        (self._query_lm, query_history_start),
                        (self._reasoning_lm, reasoning_history_start),
                    ]
                ),
            ),
        )
