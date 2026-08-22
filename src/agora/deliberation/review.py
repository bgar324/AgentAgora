import asyncio
from collections.abc import Mapping, Sequence

import dspy

from agora.deliberation.contract import DIALOGUE_CONTRACT
from agora.deliberation.proposal import proposal_text
from agora.deliberation.thread import optional_text
from agora.panel.perspective import perspective_text
from agora.research.evidence import (
    cited_prose,
    text_citations,
    cited_observations,
    observation_catalogue,
    observations_by_id,
    prose,
)
from agora.schemas.deliberation import (
    PanelReview,
    PerspectiveState,
    Proposal,
    ReviewAssignment,
)
from agora.schemas.panel import Observation, ResearcherProfile


class ReviewProposal(dspy.Signature):
    __doc__ = """
    Respond to one research direction from another Perspective.

    State in the first sentence what the direction gets right or where it
    overreaches, then make exactly one evidence-based change: narrow the
    warranted scope, add a missing condition, name the discriminating
    comparison, or connect a construct it omits. Write two or three
    sentences with [n] markers after the statements they support, and
    list the numbers in the citations field. If nothing cited bears on
    the direction, state what the direction needs that current findings
    do not give, and return no citations.

    Ask one focused question only when a specific issue remains
    unresolved; write exactly "none" otherwise, and never repeat the
    question inside the response.
    """ + DIALOGUE_CONTRACT

    research_question: str = dspy.InputField()
    reviewer: str = dspy.InputField()
    proposal: str = dspy.InputField()
    observations: list[str] = dspy.InputField()

    response: str = dspy.OutputField()
    question: str = dspy.OutputField()
    citations: list[int] = dspy.OutputField()


def review_assignments(
    proposals: Sequence[Proposal],
) -> list[ReviewAssignment]:
    if len(proposals) < 2:
        raise ValueError(
            "Proposal review requires at least two Perspectives"
        )

    perspective_ids = [proposal.perspective_id for proposal in proposals]

    if len(set(perspective_ids)) != len(perspective_ids):
        raise ValueError(
            "Each Proposal must belong to a distinct Perspective"
        )

    return [
        ReviewAssignment(
            proposal_id=proposal.id,
            author_id=proposal.perspective_id,
            reviewer_id=perspective_ids[i - 1],
        )
        for i, proposal in enumerate(proposals)
    ]


async def review_proposal(
    predict: dspy.Module,
    *,
    assignment: ReviewAssignment,
    question: str,
    reviewer: ResearcherProfile,
    proposal: Proposal,
    observations: list[Observation],
) -> PanelReview:
    if assignment.proposal_id != proposal.id:
        raise ValueError("ReviewAssignment refers to another Proposal")

    if assignment.author_id != proposal.perspective_id:
        raise ValueError("ReviewAssignment refers to another author")

    if assignment.reviewer_id == assignment.author_id:
        raise ValueError("A Perspective cannot review its own Proposal")

    prediction = await predict.acall(
        research_question=question,
        reviewer=perspective_text(reviewer),
        proposal=proposal_text(proposal),
        observations=observation_catalogue(observations),
    )
    response = cited_prose(prediction.response, len(observations))
    positions = list(
        dict.fromkeys([*prediction.citations, *text_citations(response)])
    )
    cited = cited_observations(positions, observations)
    review_question = optional_text(prediction.question)

    if review_question:
        trailing = review_question.casefold().rstrip("?")
        deduplicated = response.casefold().rstrip("?").rstrip()
        if deduplicated.endswith(trailing):
            response = response[
                : len(deduplicated) - len(trailing)
            ].rstrip()

    if not response:
        raise ValueError("The Review requires a response")

    return PanelReview(
        id=(
            f"{proposal.id}:review:"
            f"{assignment.reviewer_id}:v{proposal.version}"
        ),
        proposal_id=proposal.id,
        proposal_version=proposal.version,
        reviewer_id=assignment.reviewer_id,
        response=response,
        question=review_question,
        observation_ids=[observation.id for observation in cited],
    )


async def review_panel(
    *,
    question: str,
    proposals: list[Proposal],
    perspectives: Mapping[str, PerspectiveState],
    max_parallel: int = 3,
) -> list[PanelReview]:
    if max_parallel < 1:
        raise ValueError("max_parallel must be positive")

    predict = dspy.Predict(ReviewProposal)
    assignments = review_assignments(proposals)
    proposals_by_id = {proposal.id: proposal for proposal in proposals}
    proposals_by_author = {
        proposal.perspective_id: proposal for proposal in proposals
    }
    semaphore = asyncio.Semaphore(max_parallel)

    async def review(assignment: ReviewAssignment) -> PanelReview:
        proposal = proposals_by_id[assignment.proposal_id]
        reviewer = perspectives[assignment.reviewer_id]
        reviewer_proposal = proposals_by_author[assignment.reviewer_id]
        observations = observations_by_id(
            [
                evidence.observation_id
                for evidence in reviewer_proposal.argument.evidence
            ],
            reviewer.observations,
        )

        async with semaphore:
            return await review_proposal(
                predict,
                assignment=assignment,
                question=question,
                reviewer=reviewer.profile,
                proposal=proposal,
                observations=observations,
            )

    return await asyncio.gather(
        *[review(assignment) for assignment in assignments]
    )
