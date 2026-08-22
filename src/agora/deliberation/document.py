import re
from collections.abc import Sequence
from datetime import datetime

import dspy
from pydantic import BaseModel

from agora.deliberation.thread import SuggestThread, perspective_catalogue
from agora.research.evidence import (
    MARKER,
    cited_prose,
    collapse_repeats,
    observation_catalogue,
    strip_citations,
)
from agora.schemas.panel import Observation
from agora.schemas.deliberation import (
    DocumentSection,
    Objective,
    Refinement,
    Revision,
    Suggestion,
    Thread,
    WorkingDocument,
)


class ObjectiveDraft(BaseModel):
    text: str
    proposals: list[int]


class DefineObjectives(dspy.Signature):
    """
    You are defining the objectives that should organize the panel's
    shared investigation from the refined directions the researcher
    selected.

    State the smallest set of pairwise distinct objectives that preserves
    the selected directions and unresolved questions; combine objectives
    that share their question. Link each objective to the proposals that
    support it, by the number in each [n] marker. Do not present a selected
    proposal as an established conclusion.
    """

    question: str = dspy.InputField()
    refinements: list[str] = dspy.InputField()

    objectives: list[ObjectiveDraft] = dspy.OutputField()


class DocumentCreation(dspy.Module):
    def __init__(self):
        super().__init__()

        self.define_objectives = dspy.Predict(DefineObjectives)
        self.suggest_threads = dspy.Predict(SuggestThread)

    async def aforward(
        self,
        *,
        document_id: str,
        thread_ids: Sequence[str],
        investigation_id: str,
        title: str,
        question: str,
        refinements: list[Refinement],
        created_by: str,
        created_at: datetime,
        n: int,
    ):
        if not refinements:
            raise ValueError(
                "Document initialization requires selected Refinements"
            )

        if n < 1:
            raise ValueError("n must be positive")

        refinement_entries = [
            (
                f"[{position}] {refinement.proposal.claim.text} | "
                f"reason: {refinement.reason} | "
                f"open question: {refinement.open_question or 'none'}"
            )
            for position, refinement in enumerate(refinements, start=1)
        ]
        prediction = await self.define_objectives.acall(
            question=question,
            refinements=refinement_entries,
        )
        objectives: list[Objective] = []

        for i, draft in enumerate(prediction.objectives, start=1):
            text = " ".join(draft.text.split())
            positions = list(dict.fromkeys(draft.proposals))

            if not text:
                continue

            if not positions or any(
                not 1 <= position <= len(refinements)
                for position in positions
            ):
                raise ValueError("An Objective refers to unknown Proposals")

            objectives.append(
                Objective(
                    id=f"{document_id}:objective:{i}",
                    text=text,
                    proposal_ids=[
                        refinements[position - 1].proposal.id
                        for position in positions
                    ],
                )
            )

        if not objectives:
            raise ValueError(
                "Document initialization requires at least one Objective"
            )

        prediction = await self.suggest_threads.acall(
            research_question=question,
            objectives=[objective.text for objective in objectives],
            perspectives=perspective_catalogue(
                [refinement.profile for refinement in refinements]
            ),
            open_questions=[
                refinement.open_question
                for refinement in refinements
                if refinement.open_question
            ],
            existing_questions=[],
            resolution="none",
            unused_observations=[],
            n=n,
        )
        drafts = []
        seen: set[str] = set()

        for draft in prediction.threads[:n]:
            thread_title = " ".join(draft.title.split())
            thread_question = " ".join(draft.question.split())
            context = " ".join(draft.context.split())
            key = thread_question.casefold()

            if (
                not thread_title
                or not thread_question
                or not context
                or key in seen
            ):
                continue

            seen.add(key)
            drafts.append((thread_title, thread_question, context))

        if not drafts or len(thread_ids) < len(drafts):
            raise ValueError(
                "Document initialization requires Thread suggestions and IDs"
            )

        section = DocumentSection(
            id=f"{document_id}:section:1",
            version=1,
            title=drafts[0][0],
        )
        document = WorkingDocument(
            id=document_id,
            version=1,
            investigation_id=investigation_id,
            title=title,
            objectives=objectives,
            sections=[section],
        )
        threads = [
            Thread(
                id=thread_ids[i],
                version=1,
                status="open" if i == 0 else "suggested",
                title=thread_title,
                question=thread_question,
                context=context,
                origin_ids=[objective.id for objective in objectives],
                section_id=section.id if i == 0 else None,
                created_by=created_by,
                created_at=created_at,
            )
            for i, (thread_title, thread_question, context) in enumerate(
                drafts
            )
        ]

        return dspy.Prediction(
            document=document,
            threads=threads,
        )


def open_thread(
    document: WorkingDocument,
    thread: Thread,
) -> tuple[WorkingDocument, Thread]:
    if thread.status != "suggested":
        raise ValueError("Only a suggested Thread can be opened")

    section = DocumentSection(
        id=f"{document.id}:section:{len(document.sections) + 1}",
        version=1,
        title=thread.title,
    )

    return (
        document.model_copy(
            update={
                "version": document.version + 1,
                "sections": [*document.sections, section],
            }
        ),
        thread.model_copy(
            update={
                "version": thread.version + 1,
                "status": "open",
                "section_id": section.id,
            }
        ),
    )


def apply_suggestion(
    document: WorkingDocument,
    suggestion: Suggestion,
    *,
    action: str,
    decision_id: str,
    revision_id: str,
    created_at: datetime,
    text: str | None = None,
) -> tuple[WorkingDocument, Suggestion, Revision | None]:
    sections = {section.id: section for section in document.sections}
    section = sections.get(suggestion.section_id)

    if section is None or section.version != suggestion.section_version:
        raise ValueError(
            "Suggestion refers to another DocumentSection version"
        )

    if action == "reject":
        return (
            document,
            suggestion.model_copy(update={"status": "rejected"}),
            None,
        )

    if action not in {"accept", "edit"}:
        raise ValueError("action must be accept, edit, or reject")

    accepted_text = (
        suggestion.proposed_text
        if action == "accept"
        else " ".join((text or "").split())
    )

    if not accepted_text:
        raise ValueError("An edited Suggestion requires replacement text")

    revised_section = section.model_copy(
        update={
            "version": section.version + 1,
            "text": accepted_text,
        }
    )
    revised_document = document.model_copy(
        update={
            "version": document.version + 1,
            "sections": [
                revised_section if item.id == section.id else item
                for item in document.sections
            ],
        }
    )
    revised_suggestion = suggestion.model_copy(
        update={
            "status": "accepted" if action == "accept" else "edited",
        }
    )

    return (
        revised_document,
        revised_suggestion,
        Revision(
            id=revision_id,
            document_id=document.id,
            previous_document_version=document.version,
            document_version=revised_document.version,
            section_id=section.id,
            previous_text=section.text,
            proposed_text=suggestion.proposed_text,
            accepted_text=accepted_text,
            suggestion_id=suggestion.id,
            decision_id=decision_id,
            created_at=created_at,
        ),
    )

class DraftSection(dspy.Signature):
    """
    You are keeping one section of the shared Working Document current
    with its discussion.

    Rewrite the section as two to five sentences of direct scientific
    prose about the phenomenon; the discussion, its contributions, and
    the observations never appear as the subject of a sentence. State what has been
    established about the section's question so far. When a
    genuine open point exists, state it as the missing comparison or
    measurement; otherwise write no such sentence. Preserve current text
    that remains accurate, and do not state any relationship more
    strongly than the contributions do. Support every statement by
    writing its [n] markers directly after it, and list the cited
    numbers in the citations field.
    """

    research_question: str = dspy.InputField()
    thread_question: str = dspy.InputField()
    current_text: str = dspy.InputField()
    discussion: list[str] = dspy.InputField()
    observations: list[str] = dspy.InputField()

    text: str = dspy.OutputField()
    citations: list[int] = dspy.OutputField()


async def draft_section(
    predict: dspy.Module,
    *,
    question: str,
    thread: Thread,
    section: DocumentSection,
    discussion: list[str],
    observations: list[Observation],
) -> str:
    prediction = await predict.acall(
        research_question=question,
        thread_question=thread.question,
        current_text=strip_citations(section.text),
        discussion=discussion,
        observations=observation_catalogue(observations),
    )

    return cited_prose(prediction.text, len(observations)).strip('"')


def renumber_markers(
    text: str,
    observations: Sequence[Observation],
    references: Sequence[str],
) -> tuple[str, list[str]]:
    updated = list(references)

    def rewrite(match: re.Match) -> str:
        rewritten = []

        for part in match.group(1).split(","):
            position = int(part)

            if not 1 <= position <= len(observations):
                continue

            source_id = observations[position - 1].source_id

            if source_id not in updated:
                updated.append(source_id)

            rewritten.append(f"[{updated.index(source_id) + 1}]")

        return "".join(dict.fromkeys(rewritten))

    renumbered = collapse_repeats(MARKER.sub(rewrite, text))
    renumbered = re.sub(r"\s+([.,;:])", r"\1", renumbered)
    return (" ".join(renumbered.split()), updated)


def apply_draft(
    document: WorkingDocument,
    section_id: str,
    text: str,
    references: Sequence[str] | None = None,
) -> WorkingDocument:
    sections = [
        (
            section.model_copy(
                update={
                    "version": section.version + 1,
                    "text": text,
                }
            )
            if section.id == section_id
            else section
        )
        for section in document.sections
    ]

    update: dict = {
        "version": document.version + 1,
        "sections": sections,
    }

    if references is not None:
        update["references"] = list(references)

    return document.model_copy(update=update)
