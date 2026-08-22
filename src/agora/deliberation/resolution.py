import re
from collections.abc import Mapping, Sequence

import dspy

from agora.deliberation.thread import (
    contribution_lines,
    optional_text,
    thread_text,
)
from agora.research.evidence import (
    cited_prose,
    invert_announcements,
    strip_citations,
    text_citations,
    cited_observations,
    observation_catalogue,
    prose,
)
from agora.schemas.deliberation import (
    Contribution,
    DocumentSection,
    Resolution,
    Suggestion,
    Thread,
)
from agora.schemas.panel import Observation


SINGULAR_APPARATUS = re.compile(r"\b([Tt])he (?:available )?evidence\b")
PLURAL_APPARATUS = re.compile(
    r"\b([Tt])he (?:available )?(?:observations?|contributions?)\b"
)


class SummarizeThread(dspy.Signature):
    """
    You are recording where one scientific Thread ended.

    First write a brief internal summary of how the contributions relate.
    State as the consensus the narrowest conclusion about the phenomenon
    that no participant challenged; a challenged statement enters the
    consensus only when the challenge was answered with supporting
    findings, and when the dispute concerns whether a measured quantity
    reflects the underlying construct, state the consensus at the level
    of what was measured. State the substantive interpretation that
    remains disputed without choosing a side, attributing each position
    to the specific findings it rests on, and one open question
    naming the comparison or measurement that would resolve it. Phrase
    the consensus, the disagreement, and the open question as direct
    statements about the phenomenon. When the cited findings cannot
    separate the alternatives, state the missing comparison or
    measurement rather than describing what has been examined. Preserve
    the supplied uncertainty and do not infer causation from
    association. Write the consensus in at most thirty words, the
    disagreement in at most forty words, and the open question as one
    question of at most twenty five words. Name the specific findings a
    position rests on; do not use the words evidence, observations, or
    contributions in these three fields. Write exactly "none" when a field has no
    substantive content, and list the supporting [n] numbers in the
    citations field.
    """

    thread: str = dspy.InputField()
    contributions: list[str] = dspy.InputField()
    observations: list[str] = dspy.InputField()

    summary: str = dspy.OutputField()
    consensus: str = dspy.OutputField()
    disagreement: str = dspy.OutputField()
    open_question: str = dspy.OutputField()
    citations: list[int] = dspy.OutputField()


class SuggestDocumentChange(dspy.Signature):
    """
    You are updating one section of the shared Working Document from an
    accepted Thread Resolution.

    Write the section as direct scientific prose about the phenomenon;
    the panel, the discussion, the Resolution, and the observations
    never appear as the subject of a sentence. State
    what is now established and, only when one genuinely exists, the
    missing comparison or measurement that would settle what is not,
    each stated once, with [n] markers after the statements they support
    and the numbers listed in the citations field. Do not state any relationship
    more strongly than the Resolution does. Preserve current text that
    remains accurate; if no change is needed, leave the proposed text and
    reason empty.
    """

    research_question: str = dspy.InputField()
    current_text: str = dspy.InputField()
    thread_question: str = dspy.InputField()
    resolution: str = dspy.InputField()
    observations: list[str] = dspy.InputField()

    proposed_text: str = dspy.OutputField()
    reason: str = dspy.OutputField()
    citations: list[int] = dspy.OutputField()


def resolution_text(resolution: Resolution) -> str:
    return "\n".join(
        (
            f"Consensus: {resolution.consensus or 'none'}",
            f"Disagreement: {resolution.disagreement or 'none'}",
            f"Open question: {resolution.open_question or 'none'}",
        )
    )


def affected_perspectives(
    contributions: Sequence[Contribution],
    *,
    extra: Sequence[str] = (),
) -> list[str]:
    by_id = {contribution.id: contribution for contribution in contributions}
    affected = [
        by_id[contribution.reply_to].author_id
        for contribution in contributions
        if contribution.kind == "challenge"
        and contribution.reply_to in by_id
    ]

    return list(dict.fromkeys([*affected, *extra]))


async def summarize_thread(
    predict: dspy.Module,
    *,
    resolution_id: str,
    thread: Thread,
    contributions: list[Contribution],
    observations: list[Observation],
    names: Mapping[str, str] | None = None,
) -> Resolution:
    prediction = await predict.acall(
        thread=thread_text(thread),
        contributions=contribution_lines(contributions, names),
        observations=observation_catalogue(observations),
    )
    consensus, disagreement, open_question = (
        invert_announcements(
            PLURAL_APPARATUS.sub(
                r"\1he cited findings",
                SINGULAR_APPARATUS.sub(r"\1he cited literature", text),
            )
        )
        if text
        else None
        for text in (
            optional_text(prediction.consensus),
            optional_text(prediction.disagreement),
            optional_text(prediction.open_question),
        )
    )
    cited = cited_observations(prediction.citations, observations)

    if consensus is None and disagreement is None and open_question is None:
        raise ValueError(
            "A Resolution requires a consensus, disagreement, or open "
            "question"
        )

    return Resolution(
        id=resolution_id,
        version=1,
        status="pending",
        thread_id=thread.id,
        consensus=consensus,
        disagreement=disagreement,
        open_question=open_question,
        contribution_ids=[
            contribution.id
            for contribution in contributions
            if contribution.thread_id == thread.id
        ],
        observation_ids=[observation.id for observation in cited],
    )


def decide_resolution(
    thread: Thread,
    resolution: Resolution,
    *,
    action: str,
    consensus: str | None = None,
    disagreement: str | None = None,
    open_question: str | None = None,
) -> tuple[Thread, Resolution]:
    if resolution.thread_id != thread.id:
        raise ValueError("Resolution refers to another Thread")

    if action == "reopen":
        if thread.status != "closed":
            raise ValueError("Only a closed Thread can be reopened")

        return (
            thread.model_copy(
                update={
                    "version": thread.version + 1,
                    "status": "open",
                }
            ),
            resolution,
        )

    if resolution.status != "pending":
        raise ValueError("Resolution has already been decided")

    if action in {"close", "edit_close"}:
        accepted = resolution

        if action == "edit_close":
            edits = {
                field: " ".join(value.split()) or None
                for field, value in (
                    ("consensus", consensus),
                    ("disagreement", disagreement),
                    ("open_question", open_question),
                )
                if value is not None
            }

            if not edits:
                raise ValueError(
                    "An edited Resolution requires replacement text"
                )

            accepted = resolution.model_copy(
                update={
                    "version": resolution.version + 1,
                    **edits,
                }
            )

        accepted = accepted.model_copy(update={"status": "accepted"})

        return (
            thread.model_copy(
                update={
                    "version": thread.version + 1,
                    "status": "closed",
                    "resolution_id": resolution.id,
                }
            ),
            accepted,
        )

    if action in {"keep_open", "request_evidence"}:
        return (
            thread,
            resolution.model_copy(update={"status": "rejected"}),
        )

    raise ValueError("Unknown Thread decision")


async def suggest_document_change(
    predict: dspy.Module,
    *,
    suggestion_id: str,
    author_id: str,
    question: str,
    section: DocumentSection,
    thread: Thread,
    resolution: Resolution,
    observations: list[Observation],
) -> Suggestion | None:
    if thread.status != "closed" or resolution.status != "accepted":
        raise ValueError(
            "A document Suggestion requires a closed Thread and accepted "
            "Resolution"
        )

    prediction = await predict.acall(
        research_question=question,
        current_text=strip_citations(section.text),
        thread_question=thread.question,
        resolution=resolution_text(resolution),
        observations=observation_catalogue(observations),
    )
    proposed_text = cited_prose(
        prediction.proposed_text,
        len(observations),
    ).strip('"')
    reason = prose(prediction.reason)

    if not proposed_text:
        return None

    positions = list(
        dict.fromkeys(
            [*prediction.citations, *text_citations(proposed_text)]
        )
    )
    cited = cited_observations(positions, observations)

    if not reason or not cited:
        raise ValueError(
            "A Suggestion requires a reason and known Observations"
        )

    return Suggestion(
        id=suggestion_id,
        version=1,
        status="pending",
        author_id=author_id,
        thread_id=thread.id,
        resolution_id=resolution.id,
        section_id=section.id,
        section_version=section.version,
        current_text=section.text,
        proposed_text=proposed_text,
        reason=reason,
        observation_ids=[observation.id for observation in cited],
    )
