import asyncio
from collections.abc import Mapping, Sequence

import dspy

from agora.deliberation.contract import DIALOGUE_CONTRACT
from agora.deliberation.proposal import (
    renumber_to_evidence,
    Citation,
    evidence_links,
    proposal_text,
)
from agora.deliberation.resolution import resolution_text
from agora.deliberation.thread import optional_text
from agora.panel.perspective import (
    SynthesizePerspective,
    facet_lines,
    perspective_text,
)
from agora.research.evidence import (
    cited_prose,
    observation_catalogue,
    observations_by_id,
    prose,
)
from agora.schemas.deliberation import (
    Argument,
    Claim,
    Evidence,
    FacetRevision,
    PanelReview,
    PerspectiveState,
    Proposal,
    Refinement,
    Reflection,
    Resolution,
    Thread,
)
from agora.schemas.panel import (
    Observation,
    Perspective,
    PerspectiveFacets,
    ResearcherProfile,
)


class RefineProposal(dspy.Signature):
    __doc__ = """
    Reconsider the current research direction after the supplied exchange.

    State as the reason one sentence saying what changed in this
    direction, or that it is unchanged, in terms of the phenomenon.
    Revise only what the cited findings change or qualify; a claim may
    stay unchanged while the reasoning or evidence changes. Treat a
    possibility, an absence of a relationship, and a positive association
    as different claims, and preserve competing interpretations the
    findings do not distinguish. Keep the claim to one sentence of at
    most thirty words, write the reasoning with [n] markers after the
    statements they support, and keep at least one supporting citation in
    the evidence field.

    Return a facet revision only when the exchange contradicts or
    materially extends what a facet states; participation or an
    already-incorporated point is not a revision, and an empty list is
    the expected result. Write a revised facet as its current scientific
    content. Most exchanges leave no open question; write exactly "none"
    unless one specific issue remains.
    """ + DIALOGUE_CONTRACT

    research_question: str = dspy.InputField()
    perspective: str = dspy.InputField()
    facets: list[str] = dspy.InputField()
    proposal: str = dspy.InputField()
    exchange: list[str] = dspy.InputField()
    observations: list[str] = dspy.InputField()

    reason: str = dspy.OutputField()
    claim: str = dspy.OutputField()
    reasoning: str = dspy.OutputField()
    evidence: list[Citation] = dspy.OutputField()
    facet_revisions: list[FacetRevision] = dspy.OutputField()
    open_question: str = dspy.OutputField()


class ReflectPerspective(dspy.Signature):
    """
    Reconsider the current Perspective after an accepted Thread Resolution.

    State as the reason one sentence saying what changed in this
    Perspective, or that nothing did, in terms of the phenomenon. Return
    a facet revision only when the resolved findings contradict or
    materially extend what a facet states; participation, confirmation,
    or an already-incorporated point is not a revision, and an empty list
    is the expected result. Write a revised facet as its current
    scientific content.

    Return as the perspective the current Framing and Position, revised
    only when a facet revision changes what they state. Most Threads
    leave no open question; write exactly "none" unless the accepted
    Resolution leaves one specific issue unresolved.
    """

    research_question: str = dspy.InputField()
    current_perspective: str = dspy.InputField()
    current_facets: list[str] = dspy.InputField()
    resolution: str = dspy.InputField()
    observations: list[str] = dspy.InputField()

    reason: str = dspy.OutputField()
    facet_revisions: list[FacetRevision] = dspy.OutputField()
    perspective: Perspective = dspy.OutputField()
    open_question: str = dspy.OutputField()


def revise_facets(
    facets: PerspectiveFacets,
    revisions: Sequence[FacetRevision],
) -> tuple[PerspectiveFacets, list[FacetRevision]]:
    updates: dict[str, str] = {}
    changed: list[FacetRevision] = []

    for revision in revisions:
        if revision.facet in updates:
            raise ValueError(
                f"Duplicate revision for {revision.facet}"
            )

        text = prose(revision.text)

        if not text or text == getattr(facets, revision.facet):
            continue

        updates[revision.facet] = text
        changed.append(FacetRevision(facet=revision.facet, text=text))

    return (facets.model_copy(update=updates), changed)


def review_exchange(
    reviews: Sequence[PanelReview],
    perspectives: Mapping[str, PerspectiveState],
) -> list[str]:
    reviewers = {
        perspective.id: perspective.profile.focus
        for perspective in perspectives.values()
    }
    return [
        (
            f"{reviewers.get(review.reviewer_id, review.reviewer_id)}: "
            f"{review.response}"
            + (f" Question: {review.question}" if review.question else "")
        )
        for review in reviews
    ]


class ProposalRevision(dspy.Module):
    def __init__(self):
        super().__init__()

        self.refine_proposal = dspy.Predict(RefineProposal)
        self.synthesize_perspective = dspy.Predict(SynthesizePerspective)

    async def aforward(
        self,
        *,
        refinement_id: str,
        origin_ids: list[str],
        question: str,
        profile: ResearcherProfile,
        proposal: Proposal,
        exchange: list[str],
        observations: list[Observation],
        label: str = "",
        subthemes: list[str] | None = None,
    ):
        if not exchange:
            raise ValueError(
                "Proposal revision requires a Review or Thread exchange"
            )

        prediction = await self.refine_proposal.acall(
            research_question=question,
            perspective=perspective_text(profile),
            facets=facet_lines(profile),
            proposal=proposal_text(proposal),
            exchange=exchange,
            observations=observation_catalogue(observations),
        )

        facets, facet_revisions = revise_facets(
            profile.facets,
            prediction.facet_revisions,
        )
        revised_profile = profile

        if facet_revisions:
            synthesized = await self.synthesize_perspective.acall(
                question=question,
                facets=facets,
                label=label,
                subthemes=subthemes or [],
                peers=[],
            )
            revised_profile = ResearcherProfile(
                focus=profile.focus,
                facets=facets,
                perspective=Perspective(
                    framing=prose(synthesized.perspective.framing),
                    position=prose(synthesized.perspective.position),
                ),
            )

        claim_text = prose(prediction.claim)
        reasoning = cited_prose(prediction.reasoning, len(observations))
        reason = prose(prediction.reason)
        open_question = optional_text(prediction.open_question)

        for citation in prediction.evidence:
            if not 1 <= citation.observation <= len(observations):
                raise ValueError(
                    "The Refinement cites an Observation outside the "
                    f"catalogue: {citation.observation}"
                )

        cited = [
            Evidence(
                observation_id=observations[citation.observation - 1].id,
                relation=citation.relation,
            )
            for citation in prediction.evidence
        ]

        if not cited:
            known_ids = {observation.id for observation in observations}
            cited = [
                item
                for item in proposal.argument.evidence
                if item.observation_id in known_ids
            ]

        evidence = evidence_links(cited, observations)
        reasoning = renumber_to_evidence(reasoning, observations, evidence)

        if not claim_text or not reasoning or not reason:
            raise ValueError(
                "A Refinement requires a reason, claim, and reasoning"
            )

        profile_changed = revised_profile != profile
        proposal_changed = (
            claim_text != proposal.claim.text
            or reasoning != proposal.argument.reasoning
            or evidence != proposal.argument.evidence
        )
        revised_proposal = proposal

        if proposal_changed:
            version = proposal.version + 1
            claim = Claim(
                id=f"{proposal.id}:v{version}:claim",
                text=claim_text,
            )
            revised_proposal = Proposal(
                id=proposal.id,
                version=version,
                perspective_id=proposal.perspective_id,
                perspective_version=(
                    proposal.perspective_version + 1
                    if profile_changed
                    else proposal.perspective_version
                ),
                claim=claim,
                argument=Argument(
                    id=f"{proposal.id}:v{version}:argument",
                    claim_id=claim.id,
                    reasoning=reasoning,
                    evidence=evidence,
                ),
            )
        elif profile_changed:
            revised_proposal = proposal.model_copy(
                update={
                    "perspective_version": proposal.perspective_version + 1,
                }
            )

        refinement = Refinement(
            id=refinement_id,
            proposal_id=proposal.id,
            from_version=proposal.version,
            origin_ids=origin_ids,
            decision="revise" if facet_revisions else "unchanged",
            reason=reason,
            open_question=open_question,
            facet_revisions=facet_revisions,
            profile=revised_profile,
            proposal=revised_proposal,
        )

        return dspy.Prediction(
            refinement=refinement,
            profile_changed=profile_changed,
            proposal_changed=proposal_changed,
        )


async def refine_panel(
    *,
    question: str,
    proposals: list[Proposal],
    reviews: list[PanelReview],
    perspectives: Mapping[str, PerspectiveState],
    max_parallel: int = 3,
) -> list[Refinement]:
    if max_parallel < 1:
        raise ValueError("max_parallel must be positive")

    revision = ProposalRevision()
    reviews_by_proposal: dict[str, list[PanelReview]] = {}

    for review in reviews:
        reviews_by_proposal.setdefault(review.proposal_id, []).append(review)

    available = [
        observation
        for perspective in perspectives.values()
        for observation in perspective.observations
    ]
    semaphore = asyncio.Semaphore(max_parallel)

    async def refine(proposal: Proposal) -> Refinement:
        perspective = perspectives[proposal.perspective_id]
        proposal_reviews = reviews_by_proposal.get(proposal.id, [])
        observations = observations_by_id(
            [
                *[
                    evidence.observation_id
                    for evidence in proposal.argument.evidence
                ],
                *[
                    observation_id
                    for review in proposal_reviews
                    for observation_id in review.observation_ids
                ],
            ],
            available,
        )

        async with semaphore:
            prediction = await revision.acall(
                refinement_id=(
                    f"{proposal.id}:refinement:v{proposal.version}"
                ),
                origin_ids=[review.id for review in proposal_reviews],
                question=question,
                profile=perspective.profile,
                proposal=proposal,
                exchange=review_exchange(
                    proposal_reviews,
                    perspectives,
                ),
                observations=observations,
                label=perspective.label,
                subthemes=perspective.subthemes,
            )
            return prediction.refinement

    return await asyncio.gather(
        *[refine(proposal) for proposal in proposals]
    )


async def reflect_perspectives(
    *,
    question: str,
    thread: Thread,
    resolution: Resolution,
    perspective_ids: Sequence[str],
    perspectives: Mapping[str, PerspectiveState],
    max_parallel: int = 3,
) -> list[Reflection]:
    if max_parallel < 1:
        raise ValueError("max_parallel must be positive")

    if thread.status != "closed" or resolution.status != "accepted":
        raise ValueError(
            "Perspective reflection requires a closed Thread and accepted "
            "Resolution"
        )

    predict = dspy.Predict(ReflectPerspective)
    available = [
        observation
        for perspective in perspectives.values()
        for observation in perspective.observations
    ]
    observations = observations_by_id(resolution.observation_ids, available)
    semaphore = asyncio.Semaphore(max_parallel)

    async def reflect(perspective_id: str) -> Reflection:
        state = perspectives[perspective_id]
        profile = state.profile

        async with semaphore:
            prediction = await predict.acall(
                research_question=question,
                current_perspective=perspective_text(profile),
                current_facets=facet_lines(profile),
                resolution=resolution_text(resolution),
                observations=observation_catalogue(observations),
            )

        facets, facet_revisions = revise_facets(
            profile.facets,
            prediction.facet_revisions,
        )
        revised_profile = profile

        if facet_revisions:
            revised_profile = ResearcherProfile(
                focus=profile.focus,
                facets=facets,
                perspective=Perspective(
                    framing=prose(prediction.perspective.framing),
                    position=prose(prediction.perspective.position),
                ),
            )

        reason = prose(prediction.reason)

        if not reason:
            raise ValueError("A Reflection requires a reason")

        return Reflection(
            id=f"{perspective_id}:reflect:{thread.id}",
            thread_id=thread.id,
            perspective_id=perspective_id,
            from_version=state.version,
            perspective_version=(
                state.version + 1 if facet_revisions else state.version
            ),
            decision="revise" if facet_revisions else "unchanged",
            reason=reason,
            open_question=optional_text(prediction.open_question),
            facet_revisions=facet_revisions,
            profile=revised_profile,
        )

    return await asyncio.gather(
        *[
            reflect(perspective_id)
            for perspective_id in dict.fromkeys(perspective_ids)
        ]
    )
