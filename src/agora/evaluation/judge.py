from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Iterable, Sequence
from itertools import combinations
from statistics import mean
from uuid import uuid4

from pydantic import BaseModel, Field

from agora.core.errors import ProviderError
from agora.evaluation.retrieval import (
    EvalCluster,
    EvalPaper,
    EvalPerspective,
    JudgmentProvenance,
    PerspectivePairScore,
    PipelineRun,
    RetrievalCase,
)
from agora.llm.providers.base import LLMProvider

RUBRIC_VERSION = "fair-v2"
PAPERS_PER_BATCH = 40
PERSPECTIVES_PER_RUN = 3
EVIDENCE_PER_PERSPECTIVE = 5
EVIDENCE_ABSTRACT_CHARS = 1_200


class PaperJudgment(BaseModel):
    alias: str
    relevance: int = Field(ge=0, le=4)


class PaperJudgments(BaseModel):
    papers: list[PaperJudgment]


class PerspectiveQualityJudgment(BaseModel):
    alias: str
    coherence: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    specificity: float = Field(ge=0.0, le=1.0)

    @property
    def quality(self) -> float:
        return mean((self.coherence, self.relevance, self.specificity))


class PairwiseDistinctnessJudgment(BaseModel):
    left_alias: str
    right_alias: str
    distinctness: float = Field(ge=0.0, le=1.0)


class PerspectiveQualityJudgments(BaseModel):
    perspectives: list[PerspectiveQualityJudgment]
    pairs: list[PairwiseDistinctnessJudgment] = Field(default_factory=list)


class PerspectiveGroundingJudgment(BaseModel):
    alias: str
    support: float = Field(ge=0.0, le=1.0)
    unsupported_claims: int = Field(default=0, ge=0)


class PerspectiveGroundingJudgments(BaseModel):
    perspectives: list[PerspectiveGroundingJudgment]


class QuerySetJudgment(BaseModel):
    set_alias: str
    intent_diversity: float = Field(ge=0.0, le=1.0)
    research_coverage: float = Field(ge=0.0, le=1.0)


class QuerySetJudgments(BaseModel):
    sets: list[QuerySetJudgment]


def _digest(messages: Sequence[dict[str, str]]) -> str:
    content = "\n\n".join(
        f"{message['role']}\n{message['content']}" for message in messages
    )
    return hashlib.sha256(content.encode()).hexdigest()


def _aliases(keys: Iterable[str], *, prefix: str, scope: str) -> dict[str, str]:
    ordered = sorted(
        set(keys),
        key=lambda key: hashlib.sha256(f"{scope}:{key}".encode()).digest(),
    )
    width = max(2, len(str(len(ordered))))
    return {
        key: f"{prefix}{index:0{width}d}"
        for index, key in enumerate(ordered, start=1)
    }


def _run_key(run: PipelineRun) -> str:
    return f"{run.pipeline}\x1f{run.repeat}"


def _perspective_key(run: PipelineRun, perspective: EvalPerspective) -> str:
    return f"{_run_key(run)}\x1f{perspective.cluster_id}"


def _trim_abstract(value: str) -> str:
    text = value.strip()
    if len(text) <= EVIDENCE_ABSTRACT_CHARS:
        return text
    cut = text[:EVIDENCE_ABSTRACT_CHARS]
    boundary = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[: boundary + 1] if boundary >= EVIDENCE_ABSTRACT_CHARS // 2 else cut


def _selected_perspectives(run: PipelineRun) -> list[EvalPerspective]:
    cluster_sizes = {cluster.id: len(cluster.paper_ids) for cluster in run.clusters}
    return sorted(
        run.perspectives,
        key=lambda item: (-cluster_sizes.get(item.cluster_id, 0), item.cluster_id),
    )[:PERSPECTIVES_PER_RUN]


def _scrub_perspective_text(value: str, runs: Sequence[PipelineRun]) -> str:
    result = value
    cluster_ids = sorted(
        {cluster.id for run in runs for cluster in run.clusters},
        key=len,
        reverse=True,
    )
    for cluster_id in cluster_ids:
        result = result.replace(cluster_id, "[cluster]")
    for pipeline in {run.pipeline for run in runs}:
        result = re.sub(
            rf"\b{re.escape(pipeline)}\b",
            "[pipeline]",
            result,
            flags=re.IGNORECASE,
        )
    return result


def _perspective_text(
    perspective: EvalPerspective,
    *,
    runs: Sequence[PipelineRun],
) -> str:
    facets = "; ".join(
        f"{name}={_scrub_perspective_text(value, runs)}"
        for name, value in sorted(perspective.facets.items())
        if value.strip()
    )
    return "\n".join(
        [
            f"Name: {_scrub_perspective_text(perspective.name, runs)}",
            f"Framing: {_scrub_perspective_text(perspective.framing, runs)}",
            f"Position: {_scrub_perspective_text(perspective.position, runs)}",
            f"Facets: {facets or '(none)'}",
        ]
    )


def _cluster(run: PipelineRun, cluster_id: str) -> EvalCluster:
    return next(cluster for cluster in run.clusters if cluster.id == cluster_id)


def _evidence_papers(
    run: PipelineRun,
    perspective: EvalPerspective,
) -> list[EvalPaper]:
    cluster = _cluster(run, perspective.cluster_id)
    paper_by_id = {paper.id: paper for paper in run.papers}
    ids = list(
        dict.fromkeys(
            [
                *perspective.evidence_paper_ids,
                *cluster.representative_ids,
                *cluster.paper_ids,
            ]
        )
    )
    return [paper_by_id[paper_id] for paper_id in ids if paper_id in paper_by_id][
        :EVIDENCE_PER_PERSPECTIVE
    ]


class BlindedSolJudge:
    """Judge pooled pipeline outputs through opaque, shape-normalized packets."""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        model: str = "gpt-5.6-sol",
        paper_batch_size: int = PAPERS_PER_BATCH,
        disable_prompt_cache: bool = False,
    ) -> None:
        if paper_batch_size < 1:
            raise ValueError("paper_batch_size must be positive")
        self._llm = llm
        self._model = model
        self._paper_batch_size = paper_batch_size
        self._disable_prompt_cache = disable_prompt_cache
        self._cache_scope = ""

    def _cache_namespace(self, packet_digest: str) -> str:
        if self._disable_prompt_cache:
            return ""
        return (
            f"retrieval-eval:{RUBRIC_VERSION}:{self._cache_scope}:"
            f"{packet_digest}"
        )
    async def _generate_structured(
        self,
        *,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        max_output_tokens: int,
    ):
        packet_digest = _digest(messages)
        for attempt in range(4):
            try:
                return await self._llm.generate_structured(
                    model=self._model,
                    messages=messages,
                    schema=schema,
                    temperature=None,
                    max_output_tokens=max_output_tokens,
                    reasoning_effort="high",
                    cache_namespace=self._cache_namespace(packet_digest),
                )
            except ProviderError:
                if attempt == 3:
                    raise
                await asyncio.sleep(5 * 2**attempt)
        raise AssertionError("unreachable")

    async def _judge_papers(
        self,
        case: RetrievalCase,
        runs: Sequence[PipelineRun],
    ) -> tuple[dict[str, float], list[str]]:
        paper_by_id: dict[str, EvalPaper] = {}
        for run in runs:
            for paper in run.papers:
                paper_by_id.setdefault(paper.id, paper)
        aliases = _aliases(
            paper_by_id,
            prefix="D",
            scope=f"{case.id}:{runs[0].repeat}:papers",
        )
        ordered = sorted(paper_by_id.values(), key=lambda item: aliases[item.id])
        scores: dict[str, float] = {}
        digests: list[str] = []
        for start in range(0, len(ordered), self._paper_batch_size):
            batch = ordered[start : start + self._paper_batch_size]
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a blinded scientific-retrieval evaluator. Grade every "
                        "paper on this ordinal scale: 4 directly answers the stated "
                        "relationship for a relevant population or setting; 3 directly "
                        "addresses a research question but does not answer the full "
                        "relationship; 2 studies a related mechanism, construct, or "
                        "measure; 1 supplies background or a method only; 0 is off-topic. "
                        "Return every opaque document alias exactly once."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Research problem:\n{case.problem}\n\n"
                        "Research questions:\n"
                        + "\n".join(f"- {item}" for item in case.research_questions)
                        + "\n\nExpected concepts:\n"
                        + "\n".join(f"- {item}" for item in case.expected_concepts)
                        + "\n\nDocuments:\n"
                        + "\n\n".join(
                            f"[{aliases[paper.id]}] {paper.title}\n{paper.abstract}"
                            for paper in batch
                        )
                    ),
                },
            ]
            packet_digest = _digest(messages)
            digests.append(packet_digest)
            response = await self._generate_structured(
                messages=messages,
                schema=PaperJudgments,
                max_output_tokens=max(12_000, len(batch) * 160),
            )
            known = {aliases[paper.id] for paper in batch}
            returned = [item.alias for item in response.parsed.papers]
            if len(set(returned)) != len(returned) or set(returned) != known:
                raise ValueError("paper judge must return every opaque alias exactly once")
            reverse = {alias: paper_id for paper_id, alias in aliases.items()}
            scores.update(
                {
                    reverse[item.alias]: item.relevance / 4.0
                    for item in response.parsed.papers
                }
            )
        return scores, digests

    def _perspective_packet(
        self,
        case: RetrievalCase,
        runs: Sequence[PipelineRun],
    ) -> tuple[
        dict[str, str],
        dict[str, str],
        dict[str, list[EvalPerspective]],
    ]:
        selected = {_run_key(run): _selected_perspectives(run) for run in runs}
        perspective_keys = [
            _perspective_key(run, perspective)
            for run in runs
            for perspective in selected[_run_key(run)]
        ]
        perspective_aliases = _aliases(
            perspective_keys,
            prefix="V",
            scope=f"{case.id}:{runs[0].repeat}:perspectives",
        )
        set_aliases = _aliases(
            [_run_key(run) for run in runs],
            prefix="S",
            scope=f"{case.id}:{runs[0].repeat}:sets",
        )
        return perspective_aliases, set_aliases, selected

    async def _judge_perspective_quality(
        self,
        case: RetrievalCase,
        runs: Sequence[PipelineRun],
        perspective_aliases: dict[str, str],
        set_aliases: dict[str, str],
        selected: dict[str, list[EvalPerspective]],
    ) -> tuple[
        dict[str, float],
        dict[str, list[PerspectivePairScore]],
        list[str],
    ]:
        sections: list[str] = []
        expected_pairs: set[frozenset[str]] = set()
        for run in runs:
            run_key = _run_key(run)
            entries = []
            aliases = []
            for perspective in selected[run_key]:
                alias = perspective_aliases[_perspective_key(run, perspective)]
                aliases.append(alias)
                entries.append(
                    f"[{alias}]\n{_perspective_text(perspective, runs=runs)}"
                )
            expected_pairs.update(frozenset(pair) for pair in combinations(aliases, 2))
            sections.append(
                f"## SET {set_aliases[run_key]}\n" + "\n\n".join(entries)
            )
        if not perspective_aliases:
            return {}, {_run_key(run): [] for run in runs}, []
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a blinded evaluator of scientific Perspectives. For every "
                    "Perspective, separately score coherence, relevance to the research "
                    "problem, and specificity from 0 to 1. No evidence is supplied in "
                    "this step, so neither reward nor penalize citations. For every "
                    "unordered pair within each set, score distinctness: 1 means "
                    "materially different scientific positions and 0 means cosmetic "
                    "restatements. Return every Perspective alias and every required "
                    "within-set pair exactly once. Do not compare writing length or style."
                ),
            },
            {
                "role": "user",
                "content": f"Research problem:\n{case.problem}\n\n" + "\n\n".join(sections),
            },
        ]
        expected_aliases = set(perspective_aliases.values())
        for attempt in range(2):
            request_messages = messages
            if attempt:
                request_messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "Completeness correction: return all Perspective aliases "
                            "and all required within-set pairs exactly once."
                        ),
                    },
                ]
            packet_digest = _digest(request_messages)
            response = await self._generate_structured(
                messages=request_messages,
                schema=PerspectiveQualityJudgments,
                max_output_tokens=max(12_000, len(perspective_aliases) * 400),
            )
            returned = [item.alias for item in response.parsed.perspectives]
            returned_pairs = [
                frozenset({item.left_alias, item.right_alias})
                for item in response.parsed.pairs
            ]
            complete_aliases = (
                len(set(returned)) == len(returned)
                and set(returned) == expected_aliases
            )
            complete_pairs = (
                not any(len(pair) != 2 for pair in returned_pairs)
                and len(set(returned_pairs)) == len(returned_pairs)
                and set(returned_pairs) == expected_pairs
            )
            if complete_aliases and complete_pairs:
                break
        else:
            raise ValueError(
                "quality judge must return every alias and pair exactly once"
            )
        reverse = {alias: key for key, alias in perspective_aliases.items()}
        quality = {
            reverse[item.alias]: item.quality for item in response.parsed.perspectives
        }
        pair_scores: dict[str, list[PerspectivePairScore]] = {
            _run_key(run): [] for run in runs
        }
        run_by_perspective = {
            perspective_aliases[_perspective_key(run, perspective)]: _run_key(run)
            for run in runs
            for perspective in selected[_run_key(run)]
        }
        cluster_by_alias = {
            perspective_aliases[_perspective_key(run, perspective)]: perspective.cluster_id
            for run in runs
            for perspective in selected[_run_key(run)]
        }
        for item in response.parsed.pairs:
            run_key = run_by_perspective[item.left_alias]
            if run_by_perspective[item.right_alias] != run_key:
                raise ValueError("distinctness judge returned a cross-set pair")
            pair_scores[run_key].append(
                PerspectivePairScore(
                    left_cluster_id=cluster_by_alias[item.left_alias],
                    right_cluster_id=cluster_by_alias[item.right_alias],
                    score=item.distinctness,
                )
            )
        return quality, pair_scores, [packet_digest]

    async def _judge_perspective_grounding(
        self,
        case: RetrievalCase,
        runs: Sequence[PipelineRun],
        perspective_aliases: dict[str, str],
        selected: dict[str, list[EvalPerspective]],
    ) -> tuple[dict[str, float], list[str], dict[str, int]]:
        sections = []
        evidence_counts: dict[str, int] = {}
        for run in runs:
            for perspective in selected[_run_key(run)]:
                alias = perspective_aliases[_perspective_key(run, perspective)]
                evidence = _evidence_papers(run, perspective)
                evidence_counts[_perspective_key(run, perspective)] = len(evidence)
                evidence_block = "\n\n".join(
                    f"[E{index:02d}] {paper.title}\n{_trim_abstract(paper.abstract)}"
                    for index, paper in enumerate(evidence, start=1)
                )
                sections.append(
                    f"## [{alias}]\n{_perspective_text(perspective, runs=runs)}\n"
                    f"Supporting abstracts ({len(evidence)} available):\n"
                    f"{evidence_block or '(none)'}"
                )
        if not perspective_aliases:
            return {}, [], {}
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a blinded evidence-grounding evaluator. For every "
                    "Perspective, score support from 0 to 1 based only on whether its "
                    "substantive claims follow from at least one supplied abstract. Do "
                    "not reward the number or length of abstracts. Also count unsupported "
                    "substantive claims. Return every opaque Perspective alias exactly once."
                ),
            },
            {
                "role": "user",
                "content": f"Research problem:\n{case.problem}\n\n" + "\n\n".join(sections),
            },
        ]
        packet_digest = _digest(messages)
        response = await self._generate_structured(
            messages=messages,
            schema=PerspectiveGroundingJudgments,
            max_output_tokens=max(12_000, len(perspective_aliases) * 300),
        )
        returned = [item.alias for item in response.parsed.perspectives]
        if len(set(returned)) != len(returned) or set(returned) != set(
            perspective_aliases.values()
        ):
            raise ValueError("grounding judge must return every Perspective alias exactly once")
        reverse = {alias: key for key, alias in perspective_aliases.items()}
        return (
            {reverse[item.alias]: item.support for item in response.parsed.perspectives},
            [packet_digest],
            evidence_counts,
        )

    async def _judge_query_sets(
        self,
        case: RetrievalCase,
        runs: Sequence[PipelineRun],
        set_aliases: dict[str, str],
    ) -> tuple[dict[str, QuerySetJudgment], list[str]]:
        sections = []
        for run in runs:
            queries = list(
                dict.fromkeys(
                    query.text.strip() for query in run.queries if query.text.strip()
                )
            )
            sections.append(
                f"## SET {set_aliases[_run_key(run)]}\n"
                + "\n".join(f"- {query}" for query in queries)
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a blinded evaluator of scientific search-query sets. Score "
                    "intent_diversity from 0 to 1 based on whether the queries pursue "
                    "materially different populations, mechanisms, interventions, "
                    "outcomes, methods, or counterpositions. Score research_coverage from "
                    "0 to 1 based on coverage of the supplied questions and expected "
                    "concepts. Ignore grammar, verbosity, and whether a query uses terse "
                    "keywords or prose. Do not reward extra words. Return every opaque "
                    "set alias exactly once."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Research problem:\n{case.problem}\n\nResearch questions:\n"
                    + "\n".join(f"- {item}" for item in case.research_questions)
                    + "\n\nExpected concepts:\n"
                    + "\n".join(f"- {item}" for item in case.expected_concepts)
                    + "\n\nQuery sets:\n"
                    + "\n\n".join(sections)
                ),
            },
        ]
        packet_digest = _digest(messages)
        response = await self._generate_structured(
            messages=messages,
            schema=QuerySetJudgments,
            max_output_tokens=max(4_000, len(runs) * 500),
        )
        returned = [item.set_alias for item in response.parsed.sets]
        if len(set(returned)) != len(returned) or set(returned) != set(
            set_aliases.values()
        ):
            raise ValueError("query judge must return every opaque set alias exactly once")
        return {item.set_alias: item for item in response.parsed.sets}, [packet_digest]

    async def judge(
        self,
        case: RetrievalCase,
        runs: Sequence[PipelineRun],
    ) -> list[PipelineRun]:
        if not runs:
            return []
        repeats = {run.repeat for run in runs}
        if len(repeats) != 1 or any(run.case_id != case.id for run in runs):
            raise ValueError("pooled judging requires one case and one repeat")
        self._cache_scope = uuid4().hex
        snapshot = getattr(self._llm, "snapshot", None)
        if callable(snapshot):
            snapshot(reset=True)

        paper_scores, digests = await self._judge_papers(case, runs)
        perspective_aliases, set_aliases, selected = self._perspective_packet(case, runs)
        quality, pair_scores, quality_digests = await self._judge_perspective_quality(
            case,
            runs,
            perspective_aliases,
            set_aliases,
            selected,
        )
        grounding, grounding_digests, grounding_counts = (
            await self._judge_perspective_grounding(
                case,
                runs,
                perspective_aliases,
                selected,
            )
        )
        query_scores, query_digests = await self._judge_query_sets(
            case,
            runs,
            set_aliases,
        )
        digests.extend(quality_digests)
        digests.extend(grounding_digests)
        digests.extend(query_digests)
        packet_digest = hashlib.sha256("".join(digests).encode()).hexdigest()
        usage = snapshot(reset=True) if callable(snapshot) else []

        judged: list[PipelineRun] = []
        for run in runs:
            run_key = _run_key(run)
            selected_keys = {
                _perspective_key(run, perspective): perspective.cluster_id
                for perspective in selected[run_key]
            }
            run_quality = {
                cluster_id: quality[key]
                for key, cluster_id in selected_keys.items()
                if key in quality
            }
            run_grounding = {
                cluster_id: grounding[key]
                for key, cluster_id in selected_keys.items()
                if key in grounding
            }
            run_grounding_counts = {
                cluster_id: grounding_counts[key]
                for key, cluster_id in selected_keys.items()
                if key in grounding_counts
            }
            pairs = pair_scores[run_key]
            query_score = query_scores[set_aliases[run_key]]
            judged.append(
                run.model_copy(
                    deep=True,
                    update={
                        "relevance_scores": {
                            paper.id: paper_scores[paper.id] for paper in run.papers
                        },
                        "perspective_scores": run_quality,
                        "perspective_grounding_scores": run_grounding,
                        "grounding_evidence_counts": run_grounding_counts,
                        "perspective_pair_scores": pairs,
                        "perspective_distinctness": (
                            mean(pair.score for pair in pairs) if pairs else None
                        ),
                        "query_intent_diversity": query_score.intent_diversity,
                        "query_research_coverage": query_score.research_coverage,
                        "judgment": JudgmentProvenance(
                            judge_model=self._model,
                            rubric_version=RUBRIC_VERSION,
                            packet_digest=packet_digest,
                            cache_scope=self._cache_scope,
                            model_usage=usage,
                        ),
                    },
                )
            )
        return judged
