import asyncio
import logging
from collections.abc import Sequence

import dspy

from agora.schemas.panel import (
    LiteratureAnnotation,
    Perspective,
    PerspectiveFacets,
    PerspectiveFormationResult,
    ResearchDomain,
    ResearcherProfile,
)
from agora.schemas.research import (
    ClusteredLiterature,
    LiteratureCluster,
    RepresentativePaper,
)

logger = logging.getLogger("agora.panel")

FACET_FIELDS = (
    "scope",
    "explanation",
    "approach",
    "significance",
)

PAPER_CHAR_LIMIT = 1_800
NEIGHBOR_LIMIT = 3
NEIGHBOR_TERMS = 5


def paper_text(paper: RepresentativePaper) -> str:
    abstract = " ".join(paper.abstract.split())[:PAPER_CHAR_LIMIT]
    return "\n".join(
        (
            f"Paper ID: {paper.source_id}",
            f"Title: {paper.title.strip() or 'Untitled paper'}",
            f"Abstract: {abstract}",
        )
    )


def neighbor_context(
    clusters: Sequence[LiteratureCluster],
    cluster_id: str,
    *,
    limit: int = NEIGHBOR_LIMIT,
    n_terms: int = NEIGHBOR_TERMS,
) -> list[str]:
    lines = []

    for cluster in clusters:
        if cluster.id == cluster_id:
            continue
        if not cluster.representatives:
            continue

        title = cluster.representatives[0].title
        terms = cluster.topic.terms[:n_terms] if cluster.topic else []
        lines.append(f"{title} | terms: {', '.join(terms)}")

        if len(lines) == limit:
            break

    return lines


class LabelTopic(dspy.Signature):
    """
    Name the subject shared by the representative papers.

    Use the terms to distinguish this cluster from nearby literature. Return
    a noun phrase of at most five words using terminology from the field.
    """

    terms: list[str] = dspy.InputField()
    titles: list[str] = dspy.InputField()

    label: str = dspy.OutputField()


class AnnotateLiterature(dspy.Signature):
    """
    Describe the body of literature represented by these papers.

    Summarize the recurring findings, approaches, subthemes, and limits in the
    papers. Use the terms and neighboring clusters only to distinguish this
    literature from nearby work. Preserve mixed findings and uncertainty.
    """

    papers: list[str] = dspy.InputField()
    terms: list[str] = dspy.InputField()
    neighbors: list[str] = dspy.InputField()

    annotation: LiteratureAnnotation = dspy.OutputField()


class ResearchSynthesis(dspy.Module):
    def __init__(self):
        super().__init__()

        self.label_topic = dspy.Predict(LabelTopic)
        self.annotate_literature = dspy.Predict(AnnotateLiterature)

    async def aforward(self, *, literature: ClusteredLiterature):
        clusters = literature.clusters

        if not clusters:
            raise ValueError("Research synthesis requires assigned clusters")

        named = await asyncio.gather(
            *[
                self.label_topic.acall(
                    terms=cluster.topic.terms if cluster.topic else [],
                    titles=[paper.title for paper in cluster.representatives],
                )
                for cluster in clusters
            ]
        )

        labels = {
            cluster.id: prediction.label.strip().strip('"')
            for cluster, prediction in zip(clusters, named, strict=True)
        }

        if not all(labels.values()):
            raise ValueError("Every cluster requires a label")

        annotated = await asyncio.gather(
            *[
                self.annotate_literature.acall(
                    papers=[paper_text(paper) for paper in cluster.representatives],
                    terms=cluster.topic.terms if cluster.topic else [],
                    neighbors=neighbor_context(clusters, cluster.id),
                )
                for cluster in clusters
            ]
        )

        domains = {
            cluster.id: ResearchDomain(
                cluster_id=cluster.id,
                label=labels[cluster.id],
                literature=prediction.annotation,
            )
            for cluster, prediction in zip(clusters, annotated, strict=True)
        }

        return dspy.Prediction(domains=domains)


class SynthesizePerspectiveFacets(dspy.Signature):
    """
    Form the Perspective facets supported by this literature in relation to
    the research question.

    Scope states what phenomena, settings, populations, tasks, or conditions
    are in view. Explanation states how the phenomenon is understood. Approach
    states how it should be investigated or established. Significance states
    why the issue is consequential.

    Keep the facets distinct, preserve uncertainty, and leave an unsupported
    facet unset. Write direct scientific statements.
    """

    question: str = dspy.InputField()
    label: str = dspy.InputField()
    literature: LiteratureAnnotation = dspy.InputField()

    facets: PerspectiveFacets = dspy.OutputField()


class SynthesizePerspective(dspy.Signature):
    """
    Form one Perspective from the supported facets.

    Name the aspect of the research question that this literature foregrounds.
    Use the peer summaries to avoid duplicating an existing Focus or Position,
    but do not invent a difference that the facets do not support.

    Write a Framing that defines the problem and a Position that states the
    resulting scientific orientation. Preserve qualifications and conditions.
    Do not refer to the papers, cluster, literature, or supplied inputs.

    Use two to five words for the Focus, one or two sentences for the Framing,
    one sentence for the Position, and a short researcher label ending in
    "Researcher".
    """

    question: str = dspy.InputField()
    facets: PerspectiveFacets = dspy.InputField()
    label: str = dspy.InputField()
    peers: list[str] = dspy.InputField()

    focus: str = dspy.OutputField()
    researcher: str = dspy.OutputField()
    perspective: Perspective = dspy.OutputField()


def perspective_text(
    profile: ResearcherProfile,
    *,
    include_facets: bool = False,
) -> str:
    lines = [
        f"Focus: {profile.focus}",
        f"Framing: {profile.perspective.framing}",
        f"Position: {profile.perspective.position}",
    ]

    if include_facets:
        lines.extend(facet_lines(profile))

    return "\n".join(lines)


def facet_lines(profile: ResearcherProfile) -> list[str]:
    return [
        f"{name.title()}: {value}"
        for name in FACET_FIELDS
        if (value := getattr(profile.facets, name))
    ]


def peer_text(profile: ResearcherProfile) -> str:
    return f"{profile.focus} | {profile.perspective.position}"


def has_facets(facets: PerspectiveFacets) -> bool:
    return any(getattr(facets, name) is not None for name in FACET_FIELDS)


def normalize_facets(facets: PerspectiveFacets) -> PerspectiveFacets:
    values: dict[str, str | None] = {}

    for name in FACET_FIELDS:
        facet = getattr(facets, name)
        text = " ".join(facet.split()) if facet else ""
        if text.casefold() == "none":
            text = ""
        values[name] = text or None

    return PerspectiveFacets(**values)


class PerspectiveFormation(dspy.Module):
    def __init__(self):
        super().__init__()

        self.synthesize_perspective_facets = dspy.Predict(
            SynthesizePerspectiveFacets
        )
        self.synthesize_perspective = dspy.Predict(SynthesizePerspective)

    async def aforward(
        self,
        *,
        question: str,
        domain: ResearchDomain,
        peers: list[str] | None = None,
    ):
        prediction = await self.synthesize_perspective_facets.acall(
            question=question,
            label=domain.label,
            literature=domain.literature,
        )

        facets = normalize_facets(prediction.facets)

        if not has_facets(facets):
            logger.warning(
                "No Perspective facet was established for %s (%s)",
                domain.label,
                domain.cluster_id,
            )
            result = PerspectiveFormationResult(
                cluster_id=domain.cluster_id,
                domain=domain,
                profile=None,
            )

            return dspy.Prediction(result=result)

        prediction = await self.synthesize_perspective.acall(
            question=question,
            facets=facets,
            label=domain.label,
            peers=peers or [],
        )

        focus = " ".join(prediction.focus.split())
        researcher = " ".join(prediction.researcher.split())

        perspective = Perspective(
            framing=" ".join(prediction.perspective.framing.split()),
            position=" ".join(prediction.perspective.position.split()),
        )

        if not focus:
            raise ValueError("The ResearcherProfile requires a Focus")

        if not researcher:
            raise ValueError("The ResearcherProfile requires a name")

        if not perspective.framing or not perspective.position:
            raise ValueError("The Perspective requires Framing and Position")

        profile = ResearcherProfile(
            name=researcher,
            focus=focus,
            facets=facets,
            perspective=perspective,
        )

        result = PerspectiveFormationResult(
            cluster_id=domain.cluster_id,
            domain=domain,
            profile=profile,
        )

        return dspy.Prediction(result=result)


async def form_profiles(
    *,
    question: str,
    literature: ClusteredLiterature,
    formation: PerspectiveFormation,
    synthesis: ResearchSynthesis,
) -> dict[str, PerspectiveFormationResult]:
    domains = (await synthesis.acall(literature=literature)).domains

    results: dict[str, PerspectiveFormationResult] = {}
    formed: list[str] = []

    for cluster in literature.clusters:
        remaining = [
            domains[other.id].label
            for other in literature.clusters
            if other.id != cluster.id and other.id not in results
        ]
        prediction = await formation.acall(
            question=question,
            domain=domains[cluster.id],
            peers=[*formed, *remaining],
        )
        results[cluster.id] = prediction.result
        profile = prediction.result.profile

        if profile is not None:
            formed.append(peer_text(profile))

    return results
