from __future__ import annotations

from typing import Any
from uuid import uuid4

from agora.evaluation.metering import MeteredLLMProvider
from agora.evaluation.retrieval import (
    EvalCluster,
    EvalPaper,
    EvalPerspective,
    ExecutedQuery,
    PipelineRun,
    PipelineTelemetry,
    RetrievalCase,
)
from agora.focused.provider import FocusedProvider
from agora.focused.service import FocusedPanelService, SessionError


class _CountingRetrieval:
    def __init__(self, retrieval: Any) -> None:
        self._retrieval = retrieval
        self.calls = 0
        self.queries: list[ExecutedQuery] = []

    async def search(self, query: str, *, limit: int):
        self.calls += 1
        papers = await self._retrieval.search(query, limit=limit)
        self.queries.append(
            ExecutedQuery(
                text=query,
                paper_ids=[paper.id for paper in papers],
            )
        )
        return papers


class ProfessorRetrievalPipeline:
    """Run the professor's two-round, answer-filtered retrieval architecture."""

    name = "professor"

    def __init__(
        self,
        *,
        provider: FocusedProvider,
        retrieval: Any,
        meter: MeteredLLMProvider | None = None,
        perspectives: int = 3,
    ) -> None:
        if not 1 <= perspectives <= 6:
            raise ValueError("perspectives must be between one and six")
        self._provider = provider
        self._retrieval = retrieval
        self._meter = meter
        self._perspectives = perspectives

    async def run(self, case: RetrievalCase, *, repeat: int) -> PipelineRun:
        cache_scope = uuid4().hex
        self._provider.set_cache_scope(cache_scope)
        if self._meter is not None:
            self._meter.snapshot(reset=True)
        retrieval = _CountingRetrieval(self._retrieval)
        service = FocusedPanelService(
            provider=self._provider,
            s2=retrieval,
            retain_search_embeddings=True,
        )
        state = service.create_workspace(
            problem=case.problem,
            research_questions=case.research_questions,
            demo=False,
        ).active
        state = await service.suggest_queries(state.id)
        state = await service.run_search(
            state.id,
            [query.query for query in state.suggested_queries],
        )
        selected_clusters = sorted(
            state.clusters,
            key=lambda cluster: (-len(cluster.paper_ids), cluster.id),
        )[: self._perspectives]
        perspective_failures: dict[str, str] = {}
        for cluster in selected_clusters:
            try:
                state = await service.generate_perspective(
                    state.id,
                    cluster_id=cluster.id,
                )
            except SessionError as exc:
                perspective_failures[cluster.id] = str(exc)
        papers = {
            paper.id: EvalPaper(
                id=paper.id,
                title=paper.title,
                abstract=paper.abstract or "",
                embedding=paper.specter_v2,
            )
            for paper in state.papers
        }
        clusters = [
            EvalCluster(
                id=cluster.id,
                paper_ids=list(cluster.paper_ids),
                representative_ids=list(cluster.representative_paper_ids),
            )
            for cluster in selected_clusters
        ]
        formed = {perspective.origin: perspective for perspective in state.perspectives}
        perspectives = []
        for cluster in selected_clusters:
            perspective = formed.get(cluster.id)
            if perspective is None or perspective.framing is None:
                continue
            perspectives.append(
                EvalPerspective(
                    cluster_id=cluster.id,
                    name=perspective.name,
                    framing=perspective.framing.framing,
                    position=perspective.framing.position,
                    facets={
                        facet: evidence.text
                        for facet, evidence in perspective.facets.items()
                        if evidence.text.strip()
                    },
                    evidence_paper_ids=list(perspective.sources),
                )
            )
        assigned = {
            paper_id
            for cluster in selected_clusters
            for paper_id in cluster.paper_ids
        }
        return PipelineRun(
            pipeline=self.name,
            case_id=case.id,
            repeat=repeat,
            queries=retrieval.queries,
            papers=list(papers.values()),
            clusters=clusters,
            perspectives=perspectives,
            unassigned_paper_ids=[
                paper_id for paper_id in papers if paper_id not in assigned
            ],
            perspective_failures=perspective_failures,
            telemetry=PipelineTelemetry(
                retrieval_calls=retrieval.calls,
                cache_scope=cache_scope,
                model_usage=(
                    self._meter.snapshot(reset=True)
                    if self._meter is not None
                    else []
                ),
            ),
        )
