import re
from collections.abc import Mapping, Sequence
from datetime import datetime

import dspy
from pydantic import BaseModel

from agora.deliberation.contract import DIALOGUE_CONTRACT
from agora.panel.perspective import perspective_text
from agora.research.evidence import (
    MARKER,
    cited_observations,
    cited_prose,
    collapse_repeats,
    observation_catalogue,
    prose,
    text_citations,
)
from agora.schemas.deliberation import (
    Contribution,
    EvidenceRequest,
    Thread,
    ThreadAssignment,
)
from agora.schemas.panel import Observation, ResearcherProfile


TURN_CONTRACT = """
Use the current discussion to identify what is already established. Add only
a substantive point that extends, qualifies, or changes that state. Do not
repeat an established point merely to signal agreement.

When the available evidence cannot distinguish competing explanations,
identify the comparison, measurement, or intervention that could distinguish
them. If the supplied material adds nothing, say so in one sentence. Use the
smallest sufficient set of Observations, usually two or three.
"""


class ThreadDraft(BaseModel):
    title: str
    question: str
    context: str


class SuggestThread(dspy.Signature):
    """
    You are proposing focused questions for the next part of a scientific
    discussion.

    Use the research question, objectives, Perspectives, open questions,
    latest Resolution, unused Observations, and existing Threads to identify
    issues that would advance the investigation. Each proposed Thread should
    address one distinct difference in explanation, measurement problem,
    boundary condition, or evidence gap.

    When a Resolution is available, favor a question that could distinguish
    the competing interpretations or answer its open question. Otherwise,
    favor a question supported by unused Observations that no existing Thread
    addresses.

    Give each Thread a concise title of two to six words, a neutral question,
    and brief context stating what the question would clarify. Do not repeat
    the main research question or overlap an existing Thread. Return fewer
    Threads when no additional distinct question is warranted.
    """

    research_question: str = dspy.InputField()
    objectives: list[str] = dspy.InputField()
    perspectives: list[str] = dspy.InputField()
    open_questions: list[str] = dspy.InputField()
    existing_questions: list[str] = dspy.InputField()
    resolution: str = dspy.InputField()
    unused_observations: list[str] = dspy.InputField()
    n: int = dspy.InputField()

    threads: list[ThreadDraft] = dspy.OutputField()


class AssignQuestions(dspy.Signature):
    """
    You are preparing one entry question for each Perspective assigned to a
    scientific Thread.

    Use each Perspective's Focus, Framing, and Position to identify the part
    of the Thread it is best placed to examine. Write one neutral question per
    Perspective in catalogue order.

    The questions should remain within the shared Thread, differ
    substantively from one another, and not assume that a disputed
    interpretation is correct.
    """

    thread: str = dspy.InputField()
    perspectives: list[str] = dspy.InputField()

    questions: list[str] = dspy.OutputField()


class AnswerThread(dspy.Signature):
    __doc__ = """
    You are contributing an answer to one assigned question in a scientific
    discussion.

    Answer from the supplied Perspective using the available Observations.
    When the discussion already contains relevant points, begin with what your
    answer adds, qualifies, or changes. State what the available material
    supports and what it does not establish. Write two to four sentences.

    Request additional evidence only when a specific missing comparison,
    measurement, or intervention could change the answer. Otherwise, return
    no EvidenceRequest.
    """ + DIALOGUE_CONTRACT + TURN_CONTRACT

    research_question: str = dspy.InputField()
    thread: str = dspy.InputField()
    assigned_question: str = dspy.InputField()
    perspective: str = dspy.InputField()
    discussion: list[str] = dspy.InputField()
    observations: list[str] = dspy.InputField()

    response: str = dspy.OutputField()
    citations: list[int] = dspy.OutputField()
    evidence_requests: list[EvidenceRequest] = dspy.OutputField()


class ReplyToThread(dspy.Signature):
    __doc__ = """
    You are responding to a message about your earlier contribution to a
    scientific discussion.

    Answer the message in the first sentence. Explain whether the message
    changes, narrows, qualifies, or leaves your earlier point intact, and give
    the scientific reason. Use first person only when describing your own
    interpretation or revision.

    If the message asks whether two interpretations can be distinguished,
    identify the Observations that distinguish them. When the available
    Observations do not distinguish them, state that directly and identify
    the comparison, measurement, or intervention that would be informative.
    Write two to four sentences.

    Request additional evidence only when a specific missing result could
    change the response. Otherwise, return no EvidenceRequest.
    """ + DIALOGUE_CONTRACT + TURN_CONTRACT

    thread_question: str = dspy.InputField()
    perspective: str = dspy.InputField()
    target: str = dspy.InputField()
    message: str = dspy.InputField()
    observations: list[str] = dspy.InputField()

    response: str = dspy.OutputField()
    citations: list[int] = dspy.OutputField()
    evidence_requests: list[EvidenceRequest] = dspy.OutputField()


class UpdateThreadResponse(dspy.Signature):
    __doc__ = """
    You are revising an earlier discussion response after new evidence has
    been retrieved.

    State only what the new Observations add, qualify, contradict, or leave
    unsupported. Do not repeat conclusions that the discussion already
    established. Use first person only when stating how your interpretation
    has changed.

    If the new Observations do not answer the question that prompted
    retrieval, state that in one sentence. Write one to three sentences.

    Request additional evidence only when a specific missing comparison,
    measurement, or intervention could still change the response. Otherwise,
    return no EvidenceRequest.
    """ + DIALOGUE_CONTRACT + TURN_CONTRACT

    thread_question: str = dspy.InputField()
    perspective: str = dspy.InputField()
    previous_response: str = dspy.InputField()
    question: str = dspy.InputField()
    discussion: list[str] = dspy.InputField()
    observations: list[str] = dspy.InputField()

    response: str = dspy.OutputField()
    citations: list[int] = dspy.OutputField()
    evidence_requests: list[EvidenceRequest] = dspy.OutputField()


class PolishUtterance(dspy.Signature):
    """
    You are editing one scientific discussion turn for clarity.

    Rewrite the draft as concise, natural speech from a researcher addressing
    colleagues. Use no more than four sentences. Use first person only when
    the speaker refers to their own interpretation, response, or revision.

    Preserve every factual statement, qualification, uncertainty, and [n]
    citation. Remove repetition, praise, introductory filler, and narration
    about the evidence or discussion. State the scientific point directly. If
    the draft already meets these requirements, return it unchanged.
    """

    perspective: str = dspy.InputField()
    draft: str = dspy.InputField()

    utterance: str = dspy.OutputField()


def optional_text(value: str | None) -> str | None:
    text = prose(value).strip('"')
    if text.casefold() == "none":
        return None
    return text or None


def thread_text(thread: Thread) -> str:
    return "\n".join(
        (
            f"Question: {thread.question}",
            f"Context: {thread.context}",
        )
    )


def contribution_lines(
    contributions: Sequence[Contribution],
    names: Mapping[str, str] | None = None,
) -> list[str]:
    names = names or {}
    return [
        (
            f"{names.get(contribution.author_id, contribution.author_id)} "
            f"({contribution.kind}): {contribution.text}"
        )
        for contribution in contributions
    ]


def perspective_catalogue(
    profiles: Sequence[ResearcherProfile],
) -> list[str]:
    return [
        (
            f"[{position}] {profile.focus} | "
            f"framing: {profile.perspective.framing} | "
            f"position: {profile.perspective.position}"
        )
        for position, profile in enumerate(profiles, start=1)
    ]


def assign_thread(
    thread: Thread,
    perspective_ids: Sequence[str],
    questions: Sequence[str] | None = None,
) -> Thread:
    ordered_ids = list(dict.fromkeys(perspective_ids))

    if questions is not None and len(questions) != len(ordered_ids):
        raise ValueError(
            "Thread assignment requires one question per Perspective"
        )

    assignments = [
        ThreadAssignment(
            perspective_id=perspective_id,
            question=(
                " ".join(questions[i].split())
                if questions is not None and questions[i].strip()
                else thread.question
            ),
        )
        for i, perspective_id in enumerate(ordered_ids)
    ]

    if not assignments:
        raise ValueError("A Thread requires at least one Perspective")

    return thread.model_copy(
        update={
            "version": thread.version + 1,
            "assignments": assignments,
        }
    )


def unique_threads(
    drafts: Sequence[ThreadDraft],
    existing_questions: Sequence[str],
    existing_titles: Sequence[str] = (),
) -> list[ThreadDraft]:
    seen = {
        " ".join(question.casefold().split())
        for question in existing_questions
    }
    seen_titles = {
        " ".join(title.casefold().split())
        for title in existing_titles
    }
    selected: list[ThreadDraft] = []

    for draft in drafts:
        key = " ".join(draft.question.casefold().split())
        title_key = " ".join(draft.title.casefold().split())

        if not key or key in seen or title_key in seen_titles:
            continue

        seen.add(key)
        seen_titles.add(title_key)
        selected.append(draft)

    return selected


def evidence_request_fields(
    requests: Sequence[EvidenceRequest],
) -> list[EvidenceRequest]:
    normalized: list[EvidenceRequest] = []

    for request in requests:
        need = optional_text(request.need)
        query = optional_text(request.query)

        if need is None or query is None:
            continue

        normalized.append(EvidenceRequest(need=need, query=query))

    return normalized[:1]


def contribution_fields(
    *,
    response: str,
    citations: Sequence[int],
    evidence_requests: Sequence[EvidenceRequest],
    observations: Sequence[Observation],
) -> tuple[str, list[str], list[EvidenceRequest]]:
    text = cited_prose(response, len(observations))
    structured = cited_observations(citations, observations)
    text_order = list(dict.fromkeys(text_citations(text)))
    ordered: dict[str, None] = {}
    position_to_marker: dict[int, int] = {}

    for position in text_order:
        observation = observations[position - 1]
        ordered.setdefault(observation.id, None)
        position_to_marker[position] = (
            list(ordered).index(observation.id) + 1
        )

    def rewrite(match: re.Match) -> str:
        rewritten = [
            f"[{position_to_marker[int(part)]}]"
            for part in match.group(1).split(",")
            if int(part) in position_to_marker
        ]
        return "".join(dict.fromkeys(rewritten))

    text = collapse_repeats(MARKER.sub(rewrite, text))
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    text = " ".join(text.split())

    for observation in structured:
        ordered.setdefault(observation.id, None)

    observation_ids = list(ordered)
    requests = evidence_request_fields(evidence_requests)

    if not text:
        raise ValueError("A Contribution requires text")

    if not observation_ids and not requests:
        raise ValueError(
            "A Contribution requires an Observation or evidence request"
        )

    return (text, observation_ids, requests)


async def polish_response(
    polish: dspy.Module | None,
    *,
    profile: ResearcherProfile,
    response: str,
    catalogue_size: int,
) -> str:
    if polish is None:
        return response

    polished = cited_prose(
        (
            await polish.acall(
                perspective=perspective_text(profile),
                draft=response,
            )
        ).utterance,
        catalogue_size,
    )
    draft = cited_prose(response, catalogue_size)

    if not polished:
        return response

    if sorted(text_citations(polished)) != sorted(text_citations(draft)):
        return response

    return polished


async def answer_thread(
    predict: dspy.Module,
    *,
    contribution_id: str,
    created_at: datetime,
    question: str,
    thread: Thread,
    assignment: ThreadAssignment,
    profile: ResearcherProfile,
    observations: list[Observation],
    discussion: list[str] | None = None,
    polish: dspy.Module | None = None,
) -> Contribution:
    prediction = await predict.acall(
        research_question=question,
        thread=thread_text(thread),
        assigned_question=assignment.question,
        perspective=perspective_text(profile),
        discussion=discussion or [],
        observations=observation_catalogue(observations),
    )
    response = await polish_response(
        polish,
        profile=profile,
        response=prediction.response,
        catalogue_size=len(observations),
    )
    text, observation_ids, requests = contribution_fields(
        response=response,
        citations=prediction.citations,
        evidence_requests=prediction.evidence_requests,
        observations=observations,
    )

    return Contribution(
        id=contribution_id,
        thread_id=thread.id,
        author_id=assignment.perspective_id,
        kind="answer",
        text=text,
        observation_ids=observation_ids,
        evidence_requests=requests,
        created_at=created_at,
    )


async def update_thread_response(
    predict: dspy.Module,
    *,
    contribution_id: str,
    perspective_id: str,
    created_at: datetime,
    thread: Thread,
    previous: Contribution,
    prompted_by: str,
    profile: ResearcherProfile,
    observations: list[Observation],
    discussion: list[str] | None = None,
    polish: dspy.Module | None = None,
) -> Contribution:
    prediction = await predict.acall(
        thread_question=thread.question,
        perspective=perspective_text(profile),
        previous_response=previous.text,
        question=prompted_by,
        discussion=discussion or [],
        observations=observation_catalogue(observations),
    )
    response = await polish_response(
        polish,
        profile=profile,
        response=prediction.response,
        catalogue_size=len(observations),
    )
    text, observation_ids, requests = contribution_fields(
        response=response,
        citations=prediction.citations,
        evidence_requests=prediction.evidence_requests,
        observations=observations,
    )

    return Contribution(
        id=contribution_id,
        thread_id=thread.id,
        author_id=perspective_id,
        kind="reply",
        text=text,
        observation_ids=observation_ids,
        evidence_requests=requests,
        reply_to=previous.id,
        created_at=created_at,
    )


async def reply_to_thread(
    predict: dspy.Module,
    *,
    contribution_id: str,
    perspective_id: str,
    created_at: datetime,
    thread: Thread,
    target: Contribution,
    message: str,
    reply_to: str,
    profile: ResearcherProfile,
    observations: list[Observation],
    polish: dspy.Module | None = None,
) -> Contribution:
    prediction = await predict.acall(
        thread_question=thread.question,
        perspective=perspective_text(profile),
        target=target.text,
        message=message,
        observations=observation_catalogue(observations),
    )
    response = await polish_response(
        polish,
        profile=profile,
        response=prediction.response,
        catalogue_size=len(observations),
    )
    text, observation_ids, requests = contribution_fields(
        response=response,
        citations=prediction.citations,
        evidence_requests=prediction.evidence_requests,
        observations=observations,
    )

    return Contribution(
        id=contribution_id,
        thread_id=thread.id,
        author_id=perspective_id,
        kind="reply",
        text=text,
        observation_ids=observation_ids,
        evidence_requests=requests,
        reply_to=reply_to,
        created_at=created_at,
    )


def thread_ready(
    thread: Thread,
    contributions: Sequence[Contribution],
) -> bool:
    assigned_ids = {
        assignment.perspective_id
        for assignment in thread.assignments
    }
    answered_ids = {
        contribution.author_id
        for contribution in contributions
        if contribution.thread_id == thread.id
        and contribution.kind == "answer"
    }

    return bool(assigned_ids) and assigned_ids <= answered_ids
