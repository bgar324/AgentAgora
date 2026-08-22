from collections.abc import Sequence

import re

import dspy

from agora.deliberation.contract import DIALOGUE_CONTRACT
from pydantic import BaseModel

from agora.panel.perspective import perspective_text
from agora.research.evidence import (
    MARKER,
    collapse_repeats,
    cited_prose,
    EvidenceSearch,
    limit_observations,
    observation_catalogue,
    prose,
)
from agora.schemas.deliberation import (
    Argument,
    Claim,
    Evidence,
    EvidenceRelation,
    Proposal,
    ProposalInput,
    ProposalResult,
)
from agora.schemas.panel import Observation


class Citation(BaseModel):
    observation: int
    relation: EvidenceRelation


class WriteProposal(dspy.Signature):
    __doc__ = """
    Write one evidence-linked direction for the shared investigation from
    the supplied Perspective.

    State the direction as the claim: one sentence of at most thirty
    words on what this Perspective adds, distinct from the peer foci.
    Keep the direction provisional when the findings do not establish a
    general relationship. Write the reasoning as a short paragraph of
    what is known about the phenomenon, each statement followed by its
    [n] markers, and cite each supporting Observation in the evidence
    field.
    """ + DIALOGUE_CONTRACT

    question: str = dspy.InputField()
    perspective: str = dspy.InputField()
    peer_foci: list[str] = dspy.InputField()
    observations: list[str] = dspy.InputField()

    claim: str = dspy.OutputField()
    reasoning: str = dspy.OutputField()
    evidence: list[Citation] = dspy.OutputField()


def proposal_text(proposal: Proposal) -> str:
    return "\n".join(
        (
            f"Direction: {proposal.claim.text}",
            f"Reasoning: {proposal.argument.reasoning}",
        )
    )


def renumber_to_evidence(
    text: str,
    observations: Sequence[Observation],
    evidence: Sequence[Evidence],
) -> str:
    ids = [item.observation_id for item in evidence]

    def rewrite(match: re.Match) -> str:
        rewritten = []

        for part in match.group(1).split(","):
            position = int(part)

            if not 1 <= position <= len(observations):
                continue

            observation_id = observations[position - 1].id

            if observation_id in ids:
                rewritten.append(f"[{ids.index(observation_id) + 1}]")

        return "".join(dict.fromkeys(rewritten))

    renumbered = collapse_repeats(MARKER.sub(rewrite, text))
    renumbered = re.sub(r"\s+([.,;:])", r"\1", renumbered)
    return " ".join(renumbered.split())


def evidence_links(
    items: Sequence[Evidence],
    observations: Sequence[Observation],
) -> list[Evidence]:
    known_ids = {observation.id for observation in observations}
    selected: dict[str, Evidence] = {}

    for item in items:
        if item.observation_id not in known_ids:
            raise ValueError(
                "The Proposal refers to an unknown Observation: "
                f"{item.observation_id}"
            )

        current = selected.get(item.observation_id)

        if current is not None and current.relation != item.relation:
            raise ValueError(
                "The Proposal assigns conflicting relations to "
                f"{item.observation_id}"
            )

        selected.setdefault(item.observation_id, item)

    evidence = list(selected.values())

    if not evidence:
        raise ValueError("The Proposal requires at least one Evidence link")

    if not any(item.relation == "support" for item in evidence):
        raise ValueError(
            "The Proposal requires at least one supporting Observation"
        )

    return evidence


class ProposalGenerator(dspy.Module):
    def __init__(self, evidence: EvidenceSearch):
        super().__init__()

        self.write_proposal = dspy.Predict(WriteProposal)
        self.evidence = evidence

    async def aforward(
        self,
        *,
        investigation_id: str,
        corpus_id: str,
        question: str,
        item: ProposalInput,
        peers: list[str] | None = None,
    ):
        observations = list(item.observations)
        new_observations: list[Observation] = []
        snippet_ids: list[str] = []
        observation_snippets: dict[str, str] = {}

        if not observations:
            if not item.source_ids:
                raise ValueError("Evidence search requires cluster source IDs")

            retrieval = (
                await self.evidence.acall(
                    query=item.profile.perspective.position,
                    question=question,
                    investigation_id=investigation_id,
                    corpus_id=corpus_id,
                    source_ids=item.source_ids,
                )
            ).result
            observations = list(retrieval.observations)
            new_observations = retrieval.new_observations
            snippet_ids = retrieval.snippet_ids
            observation_snippets = retrieval.observation_snippets

        observations = limit_observations(observations)

        if not observations:
            raise ValueError("Proposal generation requires Observations to cite")

        catalogue = observation_catalogue(observations)

        prediction = await self.write_proposal.acall(
            question=question,
            perspective=perspective_text(item.profile, include_facets=True),
            peer_foci=peers or [],
            observations=catalogue,
        )

        claim_text = prose(prediction.claim)
        reasoning = cited_prose(prediction.reasoning, len(observations))

        if not claim_text:
            raise ValueError("The Proposal requires a claim")

        if not reasoning:
            raise ValueError("The Proposal requires reasoning")

        for citation in prediction.evidence:
            if not 1 <= citation.observation <= len(observations):
                raise ValueError(
                    "The Proposal cites an Observation outside the catalogue: "
                    f"{citation.observation}"
                )

        evidence = evidence_links(
            [
                Evidence(
                    observation_id=observations[citation.observation - 1].id,
                    relation=citation.relation,
                )
                for citation in prediction.evidence
            ],
            observations,
        )

        reasoning = renumber_to_evidence(reasoning, observations, evidence)
        claim = Claim(
            id=f"{item.proposal_id}:v1:claim",
            text=claim_text,
        )
        argument = Argument(
            id=f"{item.proposal_id}:v1:argument",
            claim_id=claim.id,
            reasoning=reasoning,
            evidence=evidence,
        )
        proposal = Proposal(
            id=item.proposal_id,
            version=1,
            perspective_id=item.perspective_id,
            perspective_version=item.perspective_version,
            claim=claim,
            argument=argument,
        )
        result = ProposalResult(
            proposal=proposal,
            observations=observations,
            new_observations=new_observations,
            snippet_ids=snippet_ids,
            observation_snippets=observation_snippets,
        )

        return dspy.Prediction(result=result)
