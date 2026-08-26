"""Focused-process host for the canonical deliberation engine.

This module wires Kat's deliberation framework (``agora.deliberation``,
``agora.schemas.deliberation``) into the focused product without importing
the poisoned legacy paths (``agora.workflow.run``, ``agora.api.router``,
``agora.research.model``). State lives on ``SessionState.dialogue`` as
canonical objects; every researcher command runs its bounded cascade
inline and reports progress through a small reporter protocol.

Import discipline: this module imports dspy and therefore must only be
imported lazily (inside service methods) so the focused app's cold-start
closure stays light and hermetic tests never load dspy.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

# isort: off
# dspy installs a lazy numpy alias; importing numpy first avoids a circular
# import when numpy.typing loads later through agora.db.vector.
import numpy as _numpy  # noqa: F401
import dspy
# isort: on

from agora.config.settings import PhaseModel
from agora.deliberation.document import (
    DocumentCreation,
    DraftSection,
    apply_draft,
    apply_suggestion,
    draft_section,
    open_thread,
    renumber_markers,
)
from agora.deliberation.proposal import ProposalGenerator
from agora.deliberation.resolution import (
    SuggestDocumentChange,
    SummarizeThread,
    affected_perspectives,
    decide_resolution,
    resolution_text,
    suggest_document_change,
    summarize_thread,
)
from agora.deliberation.review import review_panel
from agora.deliberation.revision import refine_panel, reflect_perspectives
from agora.deliberation.thread import (
    AnswerThread,
    AssignQuestions,
    PolishUtterance,
    ReplyToThread,
    SuggestThread,
    ThreadDraft,
    UpdateThreadResponse,
    answer_thread,
    assign_thread,
    perspective_catalogue,
    reply_to_thread,
    unique_threads,
    update_thread_response,
)
from agora.focused.models import (
    DialogueState,
    SessionState,
)
from agora.focused.models import (
    Perspective as FocusedPerspective,
)
from agora.schemas.deliberation import (
    Contribution,
    DocumentSection,
    PerspectiveState,
    Proposal,
    ProposalInput,
    Refinement,
    Reflection,
    Resolution,
    Suggestion,
    Thread,
    WorkingDocument,
)
from agora.schemas.panel import (
    Observation,
    PerspectiveFacets,
    ResearcherProfile,
)
from agora.schemas.panel import (
    Perspective as CanonPerspective,
)


class DialogueError(Exception):
    """A researcher command hit an invalid dialogue state."""


class DialogueReporter(Protocol):
    def stage(self, stage: str, message: str) -> None: ...

    def turn(self, author: str, text: str) -> None: ...


class _NullReporter:
    def stage(self, stage: str, message: str) -> None:
        return None

    def turn(self, author: str, text: str) -> None:
        return None


NULL_REPORTER = _NullReporter()

MAX_OBSERVATION_SENTENCES_PER_PAPER = 4
SUGGESTED_THREADS_ON_CLOSE = 2
INITIAL_THREADS = 3


def utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Bridges: focused corpus/Perspectives → canonical Observations/profiles
# ---------------------------------------------------------------------------


def _observation_id(source_id: str, location: str, text: str) -> str:
    digest = hashlib.sha256(f"{source_id}:{location}:{text}".encode())
    return f"obs-{digest.hexdigest()[:16]}"


def corpus_observations(state: SessionState) -> list[Observation]:
    """One Observation per leading abstract sentence, provenance intact."""
    observations: list[Observation] = []
    for paper in state.papers:
        sentences = paper.abstract_sentences or []
        for index, sentence in enumerate(
            sentences[:MAX_OBSERVATION_SENTENCES_PER_PAPER]
        ):
            text = " ".join(sentence.split())
            if len(text) < 20:
                continue
            location = f"s{index}"
            observations.append(
                Observation(
                    id=_observation_id(paper.id, location, text),
                    text=text,
                    source_id=paper.id,
                    location=location,
                )
            )
    return observations


def researcher_profile(perspective: FocusedPerspective) -> ResearcherProfile:
    framing = perspective.framing
    facets = perspective.facets
    return ResearcherProfile(
        name=perspective.name,
        focus=perspective.name,
        facets=PerspectiveFacets(
            scope=(facets.get("scope").text if facets.get("scope") else None),
            explanation=(
                facets.get("explanation").text if facets.get("explanation") else None
            ),
            approach=(facets.get("approach").text if facets.get("approach") else None),
            significance=(
                facets.get("significance").text if facets.get("significance") else None
            ),
        ),
        perspective=CanonPerspective(
            framing=(
                framing.framing
                if framing is not None
                else f"{perspective.name} frames the problem through its "
                "literature cluster."
            ),
            position=(
                framing.position
                if framing is not None
                else perspective.summary
                or f"{perspective.name} argues from its clustered findings."
            ),
        ),
    )


def perspective_states(
    state: SessionState,
    observations: Sequence[Observation],
) -> list[PerspectiveState]:
    by_source: dict[str, list[Observation]] = {}
    for observation in observations:
        by_source.setdefault(observation.source_id, []).append(observation)
    states: list[PerspectiveState] = []
    for perspective in state.perspectives:
        own = [
            observation
            for source in perspective.sources
            for observation in by_source.get(source, [])
        ]
        states.append(
            PerspectiveState(
                id=perspective.id,
                version=1,
                profile=researcher_profile(perspective),
                observations=own,
                source_ids=list(perspective.sources),
                label=perspective.name,
            )
        )
    return states


def _states_by_id(dialogue: DialogueState) -> dict[str, PerspectiveState]:
    return {state.id: state for state in dialogue.perspective_states}


def _replace_perspective_state(
    dialogue: DialogueState, updated: PerspectiveState
) -> None:
    dialogue.perspective_states = [
        updated if state.id == updated.id else state
        for state in dialogue.perspective_states
    ]


def _latest_proposals(dialogue: DialogueState) -> list[Proposal]:
    latest: dict[str, Proposal] = {}
    for proposal in dialogue.proposals:
        current = latest.get(proposal.id)
        if current is None or proposal.version >= current.version:
            latest[proposal.id] = proposal
    return list(latest.values())


def _latest_refinements(dialogue: DialogueState) -> list[Refinement]:
    latest: dict[str, Refinement] = {}
    for refinement in dialogue.refinements:
        latest[refinement.proposal_id] = refinement
    return list(latest.values())


def _thread_contributions(
    dialogue: DialogueState, thread_id: str
) -> list[Contribution]:
    return [
        contribution
        for contribution in dialogue.contributions
        if contribution.thread_id == thread_id
    ]


def _observations_by_id(
    dialogue: DialogueState, ids: Sequence[str]
) -> list[Observation]:
    known = {observation.id: observation for observation in dialogue.observations}
    return [known[item] for item in dict.fromkeys(ids) if item in known]


def _grounded_observations(
    dialogue: DialogueState,
    perspective_state: PerspectiveState,
    *,
    cap: int = 12,
) -> list[Observation]:
    """The speaker's cited-proposal observations first, then its own corpus."""
    cited: list[str] = []
    for proposal in _latest_proposals(dialogue):
        if proposal.perspective_id == perspective_state.id:
            cited.extend(
                evidence.observation_id for evidence in proposal.argument.evidence
            )
    ranked = _observations_by_id(dialogue, cited)
    seen = {observation.id for observation in ranked}
    for observation in perspective_state.observations:
        if observation.id not in seen:
            ranked.append(observation)
            seen.add(observation.id)
        if len(ranked) >= cap:
            break
    return ranked[:cap]


def _unused_observations(dialogue: DialogueState, *, cap: int = 8) -> list[Observation]:
    used: set[str] = set()
    for proposal in dialogue.proposals:
        used.update(evidence.observation_id for evidence in proposal.argument.evidence)
    for contribution in dialogue.contributions:
        used.update(contribution.observation_ids)
    for resolution in dialogue.resolutions:
        used.update(resolution.observation_ids)
    return [
        observation
        for observation in dialogue.observations
        if observation.id not in used
    ][:cap]


def _keyword_rank(
    query: str, observations: Sequence[Observation], *, cap: int = 6
) -> list[Observation]:
    terms = {term for term in re.findall(r"[a-z][a-z-]{3,}", query.lower())}
    scored = sorted(
        observations,
        key=lambda observation: (
            -len(terms & set(re.findall(r"[a-z][a-z-]{3,}", observation.text.lower())))
        ),
    )
    return list(scored[:cap])


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------


class LiveDialogueEngine:
    """Runs the canonical dspy modules under the deliberation phase LM."""

    def __init__(self, *, panel: PhaseModel, deliberation: PhaseModel) -> None:
        self._panel_lm = dspy.LM(
            panel.model,
            temperature=panel.temperature,
            max_tokens=panel.max_tokens,
        )
        self._lm = dspy.LM(
            deliberation.model,
            temperature=deliberation.temperature,
            max_tokens=deliberation.max_tokens,
        )
        self._proposals = ProposalGenerator(evidence=None)
        self._suggest_threads = dspy.Predict(SuggestThread)
        self._assign = dspy.Predict(AssignQuestions)
        self._answer = dspy.Predict(AnswerThread)
        self._reply = dspy.Predict(ReplyToThread)
        self._update = dspy.Predict(UpdateThreadResponse)
        self._polish = dspy.Predict(PolishUtterance)
        self._summarize = dspy.Predict(SummarizeThread)
        self._suggest_change = dspy.Predict(SuggestDocumentChange)
        self._draft = dspy.Predict(DraftSection)
        self._document = DocumentCreation()

    async def propose(
        self,
        *,
        dialogue: DialogueState,
        question: str,
        items: list[ProposalInput],
    ) -> list[Proposal]:
        semaphore = asyncio.Semaphore(3)

        async def one(item: ProposalInput) -> Proposal:
            peers = [
                other.profile.focus
                for other in items
                if other.perspective_id != item.perspective_id
            ]
            async with semaphore:
                with dspy.context(lm=self._lm):
                    prediction = await self._proposals.acall(
                        investigation_id=dialogue.id,
                        corpus_id=dialogue.id,
                        question=question,
                        item=item,
                        peers=peers,
                    )
            return prediction.result.proposal

        return list(await asyncio.gather(*[one(item) for item in items]))

    async def review(
        self,
        *,
        question: str,
        proposals: list[Proposal],
        perspectives: dict[str, PerspectiveState],
    ):
        with dspy.context(lm=self._lm):
            return await review_panel(
                question=question,
                proposals=proposals,
                perspectives=perspectives,
            )

    async def refine(
        self,
        *,
        question: str,
        proposals: list[Proposal],
        reviews,
        perspectives: dict[str, PerspectiveState],
    ) -> list[Refinement]:
        with dspy.context(lm=self._lm):
            return await refine_panel(
                question=question,
                proposals=proposals,
                reviews=reviews,
                perspectives=perspectives,
            )

    async def create_document(
        self,
        *,
        dialogue: DialogueState,
        title: str,
        question: str,
        refinements: list[Refinement],
    ) -> tuple[WorkingDocument, list[Thread]]:
        thread_ids = [
            f"{dialogue.id}:thread:{n}" for n in range(1, INITIAL_THREADS + 1)
        ]
        with dspy.context(lm=self._lm):
            prediction = await self._document.aforward(
                document_id=f"{dialogue.id}:document",
                thread_ids=thread_ids,
                investigation_id=dialogue.id,
                title=title,
                question=question,
                refinements=refinements,
                created_by="moderator",
                created_at=utcnow(),
                n=INITIAL_THREADS,
            )
        return prediction.document, list(prediction.threads)

    async def assign(
        self,
        *,
        thread: Thread,
        profiles: list[ResearcherProfile],
        perspective_ids: list[str],
    ) -> Thread:
        from agora.deliberation.thread import thread_text

        with dspy.context(lm=self._lm):
            prediction = await self._assign.acall(
                thread=thread_text(thread),
                perspectives=perspective_catalogue(profiles),
            )
        return assign_thread(thread, perspective_ids, prediction.questions)

    async def answer(self, **kwargs) -> Contribution:
        with dspy.context(lm=self._lm):
            return await answer_thread(self._answer, polish=self._polish, **kwargs)

    async def reply(self, **kwargs) -> Contribution:
        with dspy.context(lm=self._lm):
            return await reply_to_thread(self._reply, polish=self._polish, **kwargs)

    async def update_response(self, **kwargs) -> Contribution:
        with dspy.context(lm=self._lm):
            return await update_thread_response(
                self._update, polish=self._polish, **kwargs
            )

    async def summarize(self, **kwargs) -> Resolution:
        with dspy.context(lm=self._lm):
            return await summarize_thread(self._summarize, **kwargs)

    async def suggest_change(self, **kwargs) -> Suggestion | None:
        with dspy.context(lm=self._lm):
            return await suggest_document_change(self._suggest_change, **kwargs)

    async def reflect(self, **kwargs) -> list[Reflection]:
        with dspy.context(lm=self._lm):
            return await reflect_perspectives(**kwargs)

    async def draft(self, **kwargs) -> str:
        with dspy.context(lm=self._lm):
            return await draft_section(self._draft, **kwargs)

    async def suggest_threads(
        self,
        *,
        question: str,
        objectives: list[str],
        profiles: list[ResearcherProfile],
        open_questions: list[str],
        existing_questions: list[str],
        resolution: str,
        unused_observations: list[str],
        n: int,
    ) -> list[ThreadDraft]:
        with dspy.context(lm=self._lm):
            prediction = await self._suggest_threads.acall(
                research_question=question,
                objectives=objectives,
                perspectives=perspective_catalogue(profiles),
                open_questions=open_questions,
                existing_questions=existing_questions,
                resolution=resolution,
                unused_observations=unused_observations,
                n=n,
            )
        return list(prediction.threads[:n])


# ---------------------------------------------------------------------------
# Demo engine — deterministic, same cascade shapes, zero LLM calls
# ---------------------------------------------------------------------------


def _clip(text: str, limit: int) -> str:
    words = text.split()
    clipped = " ".join(words[: limit - 1]) if len(words) >= limit else text
    return clipped.rstrip(".,;:") or text


def _facet(profile: ResearcherProfile, name: str, fallback: str) -> str:
    """A facet's abstract-grounded sentence, or a stated fallback."""
    value = getattr(profile.facets, name, None)
    text = " ".join((value or "").split())
    return text or fallback


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _question_core(question: str) -> str:
    core = " ".join(question.split()).strip().rstrip("?.!")
    return _lower_first(core) if core else "the question"


def _sentence(text: str) -> str:
    body = " ".join((text or "").split())
    if not body:
        return ""
    body = body[0].upper() + body[1:]
    return body if body.endswith((".", "?", "!")) else f"{body}."


class DemoDialogueEngine:
    """Deterministic engine mirroring every LiveDialogueEngine entry point."""

    async def propose(
        self,
        *,
        dialogue: DialogueState,
        question: str,
        items: list[ProposalInput],
    ) -> list[Proposal]:
        from agora.schemas.deliberation import Argument, Claim, Evidence

        proposals: list[Proposal] = []
        for item in items:
            evidence = [
                Evidence(
                    observation_id=observation.id,
                    relation="support" if index == 0 else "qualify",
                )
                for index, observation in enumerate(item.observations[:2])
            ]
            markers = " ".join(f"[{index + 1}]" for index in range(len(evidence)))
            focus = item.profile.focus
            explanation = _facet(
                item.profile,
                "explanation",
                f"{focus} best explains the observed trade-off.",
            )
            approach = _facet(
                item.profile,
                "approach",
                f"The {focus} literature ties the mechanism to the question.",
            )
            claim = Claim(
                id=f"{item.proposal_id}:v1:claim",
                text=_clip(explanation, 30),
            )
            proposals.append(
                Proposal(
                    id=item.proposal_id,
                    version=1,
                    perspective_id=item.perspective_id,
                    perspective_version=item.perspective_version,
                    claim=claim,
                    argument=Argument(
                        id=f"{item.proposal_id}:v1:argument",
                        claim_id=claim.id,
                        reasoning=(
                            f"{approach.rstrip('.')} {markers}.".strip()
                            if markers
                            else approach
                        ),
                        evidence=evidence,
                    ),
                )
            )
        return proposals

    async def review(
        self,
        *,
        question: str,
        proposals: list[Proposal],
        perspectives: dict[str, PerspectiveState],
    ):
        from agora.deliberation.review import review_assignments
        from agora.schemas.deliberation import PanelReview

        reviews: list[PanelReview] = []
        for assignment in review_assignments(proposals):
            reviewer = perspectives[assignment.reviewer_id]
            observations = reviewer.observations[:1]
            reviews.append(
                PanelReview(
                    id=(f"{assignment.proposal_id}:review:{assignment.reviewer_id}:v1"),
                    proposal_id=assignment.proposal_id,
                    proposal_version=1,
                    reviewer_id=assignment.reviewer_id,
                    response=(
                        f"{_facet(reviewer.profile, 'scope', 'The claim needs narrower conditions.')} "
                        f"[1] From the {reviewer.profile.focus} side, that "
                        "narrows where this claim can hold."
                    ),
                    question=("Which boundary condition would falsify it first?"),
                    observation_ids=[observation.id for observation in observations],
                )
            )
        return reviews

    async def refine(
        self,
        *,
        question: str,
        proposals: list[Proposal],
        reviews,
        perspectives: dict[str, PerspectiveState],
    ) -> list[Refinement]:
        return [
            Refinement(
                id=f"{proposal.id}:refinement:v{proposal.version}",
                proposal_id=proposal.id,
                from_version=proposal.version,
                origin_ids=[
                    review.id for review in reviews if review.proposal_id == proposal.id
                ],
                decision="unchanged",
                reason=(
                    "The peer challenge names a boundary condition without "
                    "overturning the supporting evidence."
                ),
                open_question=(
                    f"Where does the "
                    f"{perspectives[proposal.perspective_id].profile.focus.lower()} "
                    "account stop holding?"
                ),
                facet_revisions=[],
                profile=perspectives[proposal.perspective_id].profile,
                proposal=proposal,
            )
            for proposal in proposals
        ]

    async def create_document(
        self,
        *,
        dialogue: DialogueState,
        title: str,
        question: str,
        refinements: list[Refinement],
    ) -> tuple[WorkingDocument, list[Thread]]:
        from agora.schemas.deliberation import (
            DocumentSection,
            Objective,
        )

        objectives = [
            Objective(
                id=f"{dialogue.id}:objective:{index + 1}",
                text=_clip(
                    "Test whether "
                    f"{_lower_first(refinement.proposal.claim.text.rstrip('.'))}",
                    28,
                ),
                proposal_ids=[refinement.proposal_id],
            )
            for index, refinement in enumerate(refinements)
        ]
        document = WorkingDocument(
            id=f"{dialogue.id}:document",
            version=1,
            investigation_id=dialogue.id,
            title=_clip(title, 20),
            objectives=objectives,
            sections=[
                DocumentSection(
                    id=f"{dialogue.id}:document:section:1",
                    version=1,
                    title="Shared investigation",
                    text="The panel investigates the selected directions.",
                )
            ],
            references=[],
        )
        seeds = [
            (
                "Boundary conditions",
                "Which population boundary governs the claim?",
                "The Perspectives disagree on where the effect holds.",
            ),
            (
                "Mechanism versus outcome",
                "Does the proposed mechanism drive the observed outcome?",
                "Cited evidence supports different causal links.",
            ),
            (
                "Measurement validity",
                "Can the effect be measured independently of its trigger?",
                "Open question raised during refinement.",
            ),
        ]
        threads = [
            Thread(
                id=f"{dialogue.id}:thread:{index + 1}",
                version=1,
                status="suggested",
                title=seed[0],
                question=seed[1],
                context=seed[2],
                origin_ids=[objective.id for objective in objectives[:1]],
                created_by="moderator",
                created_at=utcnow(),
            )
            for index, seed in enumerate(seeds)
        ]
        return document, threads

    async def assign(
        self,
        *,
        thread: Thread,
        profiles: list[ResearcherProfile],
        perspective_ids: list[str],
    ) -> Thread:
        questions = [
            f"How does {profile.focus.lower()} answer: {_clip(thread.question, 16)}?"
            for profile in profiles
        ]
        return assign_thread(thread, perspective_ids, questions)

    async def answer(self, **kwargs) -> Contribution:
        thread: Thread = kwargs["thread"]
        assignment = kwargs["assignment"]
        profile: ResearcherProfile = kwargs["profile"]
        observations: list[Observation] = kwargs["observations"]
        cited = observations[:1]
        marker = " [1]" if cited else ""
        return Contribution(
            id=kwargs["contribution_id"],
            thread_id=thread.id,
            author_id=assignment.perspective_id,
            kind="answer",
            text=(
                f"{_facet(profile, 'explanation', f'The {profile.focus} evidence is direct.').rstrip('.')}"
                f"{marker}. On {_question_core(thread.question)}, that is "
                f"the condition {profile.focus} expects to govern."
            ),
            observation_ids=[observation.id for observation in cited],
            evidence_requests=[],
            created_at=kwargs["created_at"],
        )

    async def reply(self, **kwargs) -> Contribution:
        thread: Thread = kwargs["thread"]
        profile: ResearcherProfile = kwargs["profile"]
        observations: list[Observation] = kwargs["observations"]
        cited = observations[:1]
        marker = " [1]" if cited else ""
        return Contribution(
            id=kwargs["contribution_id"],
            thread_id=thread.id,
            author_id=kwargs["perspective_id"],
            kind="reply",
            text=(
                f"Because "
                f"{_lower_first(_facet(profile, 'approach', f'the {profile.focus} evidence points the other way.')).rstrip('.')}"
                f"{marker}. What separates us on "
                f"{_question_core(thread.question)} is scope: "
                f"{_lower_first(_facet(profile, 'scope', 'our clusters cover different populations.'))}"
            ),
            observation_ids=[observation.id for observation in cited],
            evidence_requests=[],
            reply_to=kwargs["reply_to"],
            created_at=kwargs["created_at"],
        )

    async def update_response(self, **kwargs) -> Contribution:
        thread: Thread = kwargs["thread"]
        previous: Contribution = kwargs["previous"]
        profile: ResearcherProfile = kwargs["profile"]
        return Contribution(
            id=kwargs["contribution_id"],
            thread_id=thread.id,
            author_id=kwargs["perspective_id"],
            kind="reply",
            text=(
                f"Narrowing my earlier point: "
                f"{_lower_first(_facet(profile, 'scope', f'the {profile.focus} account holds under tighter conditions.'))}"
            ),
            observation_ids=list(previous.observation_ids),
            evidence_requests=[],
            reply_to=previous.id,
            created_at=kwargs["created_at"],
        )

    async def summarize(self, **kwargs) -> Resolution:
        thread: Thread = kwargs["thread"]
        contributions: list[Contribution] = kwargs["contributions"]
        resolution_id: str = kwargs["resolution_id"]
        cited = list(
            dict.fromkeys(
                observation_id
                for contribution in contributions
                for observation_id in contribution.observation_ids
            )
        )
        return Resolution(
            id=resolution_id,
            version=1,
            status="pending",
            thread_id=thread.id,
            consensus=(
                f"On {_question_core(thread.question)}, the panel converged "
                "on the narrower conditions the challengers named."
            ),
            disagreement=None,
            open_question=(
                f"What evidence would extend {thread.title.lower()} beyond "
                "those conditions?"
            ),
            contribution_ids=[contribution.id for contribution in contributions],
            observation_ids=cited,
        )

    async def suggest_change(self, **kwargs) -> Suggestion | None:
        thread: Thread = kwargs["thread"]
        resolution: Resolution = kwargs["resolution"]
        section = kwargs["section"]
        return Suggestion(
            id=kwargs["suggestion_id"],
            version=1,
            status="pending",
            author_id="moderator",
            thread_id=thread.id,
            resolution_id=resolution.id,
            section_id=section.id,
            section_version=section.version,
            current_text=section.text,
            proposed_text=(
                f"{section.text} The effect holds under the narrower "
                f"conditions established for {thread.title.lower()}."
            ).strip(),
            reason="Fold the resolved Thread into the shared section.",
            observation_ids=list(resolution.observation_ids),
        )

    async def reflect(self, **kwargs) -> list[Reflection]:
        from agora.schemas.deliberation import FacetRevision

        thread: Thread = kwargs["thread"]
        perspective_ids = kwargs["perspective_ids"]
        perspectives = kwargs["perspectives"]
        marker = "narrowed to the conditions"
        # One participant carries each Thread's narrowing into its own
        # scope, and each Perspective narrows at most once, so
        # Perspectives visibly evolve as Threads resolve without the text
        # growing on every close.
        revising = next(
            (
                perspective_id
                for perspective_id in perspective_ids
                if marker
                not in _facet(perspectives[perspective_id].profile, "scope", "")
            ),
            None,
        )
        reflections: list[Reflection] = []
        for perspective_id in perspective_ids:
            state = perspectives[perspective_id]
            profile = state.profile
            if perspective_id != revising:
                reflections.append(
                    Reflection(
                        id=f"{perspective_id}:reflect:{thread.id}",
                        thread_id=thread.id,
                        perspective_id=perspective_id,
                        from_version=state.version,
                        perspective_version=state.version,
                        decision="unchanged",
                        reason=(
                            f"The resolution matches the {profile.focus} "
                            "account; no facet changes."
                        ),
                        open_question=None,
                        facet_revisions=[],
                        profile=profile,
                    )
                )
                continue
            base = _facet(
                profile, "scope", "The account holds under stated conditions."
            )
            narrowed = f"{base.rstrip('.')}, {marker} {thread.title.lower()} settled."
            revised = profile.model_copy(
                update={"facets": profile.facets.model_copy(update={"scope": narrowed})}
            )
            reflections.append(
                Reflection(
                    id=f"{perspective_id}:reflect:{thread.id}",
                    thread_id=thread.id,
                    perspective_id=perspective_id,
                    from_version=state.version,
                    perspective_version=state.version + 1,
                    decision="revise",
                    reason=(
                        f"The resolution narrows where the {profile.focus} "
                        "account applies."
                    ),
                    open_question=None,
                    facet_revisions=[FacetRevision(facet="scope", text=narrowed)],
                    profile=revised,
                )
            )
        return reflections

    async def draft(self, **kwargs) -> str:
        thread: Thread = kwargs["thread"]
        observations: list[Observation] = kwargs["observations"]
        cited = observations[:2]
        if not cited:
            # No cited evidence yet: leave the section as it stands rather
            # than writing prose the record cannot support.
            return ""
        # Canonical DraftSection rule: write about the phenomenon; the
        # discussion never becomes the subject of a sentence.
        body = " ".join(
            f"{_sentence(observation.text).rstrip('.')} [{index + 1}]."
            for index, observation in enumerate(cited)
        )
        return (
            f"{body} What remains open is how far this holds beyond "
            f"{thread.title.lower()}."
        )

    async def suggest_threads(
        self,
        *,
        question: str,
        objectives: list[str],
        profiles: list[ResearcherProfile],
        open_questions: list[str],
        existing_questions: list[str],
        resolution: str,
        unused_observations: list[str],
        n: int,
    ) -> list[ThreadDraft]:
        # The demo panel converges: past five Threads total, no additional
        # distinct question is warranted (the canonical prompt's own rule),
        # so the investigation can actually reach the all-resolved state.
        remaining = max(0, 5 - len(existing_questions))
        if remaining == 0:
            return []
        drafts = [
            ThreadDraft(
                title=_clip(open_question.rstrip("?"), 6),
                question=open_question,
                context="Raised as an open question by the resolved Thread.",
            )
            for open_question in open_questions
            if open_question not in existing_questions
        ]
        return drafts[: min(n, remaining)]


# ---------------------------------------------------------------------------
# Orchestrator — researcher commands over SessionState.dialogue
# ---------------------------------------------------------------------------

MAX_DIALOGUE_EXCHANGES = 2
PROPOSAL_OBSERVATION_CAP = 8


def _require_dialogue(state: SessionState) -> DialogueState:
    if state.dialogue is None:
        raise DialogueError("The deliberation has not started yet.")
    return state.dialogue


def _profiles_in_order(
    dialogue: DialogueState,
) -> tuple[list[str], list[ResearcherProfile]]:
    ids = [state.id for state in dialogue.perspective_states]
    profiles = [state.profile for state in dialogue.perspective_states]
    return ids, profiles


def _display_names(dialogue: DialogueState) -> dict[str, str]:
    names = {
        state.id: state.label or state.profile.focus
        for state in dialogue.perspective_states
    }
    names["researcher"] = "Researcher"
    names["moderator"] = "Moderator"
    return names


def _discussion_lines(dialogue: DialogueState, thread_id: str) -> list[str]:
    from agora.deliberation.thread import contribution_lines

    return contribution_lines(
        _thread_contributions(dialogue, thread_id),
        _display_names(dialogue),
    )


def _section_for(dialogue: DialogueState, thread: Thread) -> DocumentSection:
    document = dialogue.document
    if document is None or thread.section_id is None:
        raise DialogueError("The Thread has no Document section yet.")
    for section in document.sections:
        if section.id == thread.section_id:
            return section
    raise DialogueError("The Thread's Document section is missing.")


async def start_dialogue(
    state: SessionState,
    *,
    engine,
    reporter: DialogueReporter = NULL_REPORTER,
) -> None:
    if len(state.perspectives) < 2:
        raise DialogueError("Deliberation requires at least two Perspectives.")
    if not state.papers:
        raise DialogueError("Deliberation requires a searched corpus.")

    reporter.stage("observations", "Grounding Perspectives in the corpus.")
    observations = corpus_observations(state)
    states = perspective_states(state, observations)
    empty = [item.label for item in states if not item.observations]
    if empty:
        raise DialogueError(
            "Every Perspective needs at least one grounded abstract "
            f"sentence; missing: {', '.join(empty)}."
        )
    dialogue = DialogueState(
        id=state.id,
        observations=observations,
        perspective_states=states,
    )

    reporter.stage("proposals", "Each Perspective drafts its proposal.")
    items = [
        ProposalInput(
            proposal_id=f"{item.id}:proposal",
            perspective_id=item.id,
            perspective_version=item.version,
            profile=item.profile,
            observations=item.observations[:PROPOSAL_OBSERVATION_CAP],
            source_ids=item.source_ids,
        )
        for item in states
    ]
    proposals = await engine.propose(
        dialogue=dialogue, question=state.problem, items=items
    )
    dialogue.proposals = proposals
    names = _display_names(dialogue)
    for proposal in proposals:
        reporter.turn(
            names.get(proposal.perspective_id, proposal.perspective_id),
            proposal.claim.text,
        )

    reporter.stage("review", "Peers review each proposal.")
    reviews = await engine.review(
        question=state.problem,
        proposals=proposals,
        perspectives=_states_by_id(dialogue),
    )
    dialogue.reviews = list(reviews)

    reporter.stage("refinement", "Perspectives refine their proposals.")
    refinements = await engine.refine(
        question=state.problem,
        proposals=proposals,
        reviews=reviews,
        perspectives=_states_by_id(dialogue),
    )
    dialogue.refinements = list(refinements)
    for refinement in refinements:
        if refinement.proposal is not None:
            dialogue.proposals.append(refinement.proposal)
        updated = _states_by_id(dialogue)[
            refinement.proposal.perspective_id
        ].model_copy(update={"profile": refinement.profile})
        _replace_perspective_state(dialogue, updated)

    dialogue.stage = "selection"
    dialogue.waiting_for = "proposal_selection"
    state.dialogue = dialogue


async def select_directions(
    state: SessionState,
    *,
    engine,
    reporter: DialogueReporter = NULL_REPORTER,
    proposal_ids: list[str],
) -> None:
    dialogue = _require_dialogue(state)
    if dialogue.stage != "selection":
        raise DialogueError("Direction selection is not open.")
    chosen = [
        refinement
        for refinement in _latest_refinements(dialogue)
        if refinement.proposal_id in set(proposal_ids)
    ]
    if not chosen:
        raise DialogueError("Select at least one refined proposal.")

    reporter.stage("document", "The moderator drafts the Working Document.")
    document, threads = await engine.create_document(
        dialogue=dialogue,
        title=state.problem,
        question=state.problem,
        refinements=chosen,
    )
    dialogue.document = document
    dialogue.threads.extend(threads)
    dialogue.selected_proposal_ids = list(dict.fromkeys(proposal_ids))
    dialogue.stage = "deliberation"
    dialogue.waiting_for = None


async def open_dialogue_thread(
    state: SessionState,
    *,
    engine,
    reporter: DialogueReporter = NULL_REPORTER,
    thread_id: str,
) -> None:
    dialogue = _require_dialogue(state)
    if dialogue.stage != "deliberation" or dialogue.document is None:
        raise DialogueError("The Working Document has not been created.")
    if dialogue.waiting_for == "resolution_decision":
        raise DialogueError(
            "Review the pending Resolution before opening another Thread."
        )
    if any(thread.status == "open" for thread in dialogue.current_threads()):
        raise DialogueError("Close the open Thread first.")
    thread = dialogue.latest_thread(thread_id)
    if thread is None or thread.status != "suggested":
        raise DialogueError("Only a suggested Thread can be opened.")

    reporter.stage("thread", f"Opening Thread: {thread.title}")
    document, opened = open_thread(dialogue.document, thread)
    dialogue.document = document

    ids, profiles = _profiles_in_order(dialogue)
    opened = await engine.assign(thread=opened, profiles=profiles, perspective_ids=ids)
    dialogue.threads.append(opened)
    dialogue.active_thread_id = opened.id

    names = _display_names(dialogue)
    states = _states_by_id(dialogue)
    now = utcnow()
    counter = len(dialogue.contributions)

    reporter.stage("answers", "Each Perspective answers its entry question.")
    for assignment in opened.assignments:
        counter += 1
        speaker = states[assignment.perspective_id]
        contribution = await engine.answer(
            contribution_id=f"{opened.id}:c{counter}",
            created_at=now,
            question=state.problem,
            thread=opened,
            assignment=assignment,
            profile=speaker.profile,
            observations=_grounded_observations(dialogue, speaker),
            discussion=_discussion_lines(dialogue, opened.id),
        )
        dialogue.contributions.append(contribution)
        reporter.turn(names[contribution.author_id], contribution.text)

    reporter.stage("exchange", "The panel challenges and replies.")
    for _ in range(MAX_DIALOGUE_EXCHANGES):
        thread_turns = _thread_contributions(dialogue, opened.id)
        newest = thread_turns[-1]
        last_spoken: dict[str, int] = {}
        for index, contribution in enumerate(thread_turns):
            last_spoken[contribution.author_id] = index
        candidates = [
            perspective_id
            for perspective_id in ids
            if perspective_id != newest.author_id
        ]
        if not candidates:
            break
        responder_id = min(candidates, key=lambda item: last_spoken.get(item, -1))
        responder = states[responder_id]
        counter += 1
        contribution = await engine.reply(
            contribution_id=f"{opened.id}:c{counter}",
            perspective_id=responder_id,
            created_at=now,
            thread=opened,
            target=newest,
            message=(
                "Did you claim that because of your framing? Name the "
                "assumption and why it should hold here."
            ),
            reply_to=newest.id,
            profile=responder.profile,
            observations=_grounded_observations(dialogue, responder),
        )
        dialogue.contributions.append(contribution)
        reporter.turn(names[contribution.author_id], contribution.text)

    await _redraft_section(state, engine=engine, thread=opened)

    reporter.stage("resolution", "The moderator records where this ended.")
    await _summarize_thread(state, engine=engine, thread=opened)


async def _redraft_section(state: SessionState, *, engine, thread: Thread) -> None:
    dialogue = _require_dialogue(state)
    section = _section_for(dialogue, thread)
    cited = _observations_by_id(
        dialogue,
        [
            observation_id
            for contribution in _thread_contributions(dialogue, thread.id)
            for observation_id in contribution.observation_ids
        ],
    )
    text = await engine.draft(
        question=state.problem,
        thread=thread,
        section=section,
        discussion=_discussion_lines(dialogue, thread.id),
        observations=cited,
    )
    if not text:
        return
    renumbered, references = renumber_markers(text, cited, dialogue.document.references)
    dialogue.document = apply_draft(
        dialogue.document, section.id, renumbered, references
    )


async def _summarize_thread(state: SessionState, *, engine, thread: Thread) -> None:
    dialogue = _require_dialogue(state)
    contributions = _thread_contributions(dialogue, thread.id)
    cited = _observations_by_id(
        dialogue,
        [
            observation_id
            for contribution in contributions
            for observation_id in contribution.observation_ids
        ],
    )
    ids = {
        resolution.id
        for resolution in dialogue.resolutions
        if resolution.thread_id == thread.id
    }
    for resolution_id in ids:
        latest = dialogue.latest_resolution(resolution_id)
        if latest is not None and latest.status == "pending":
            dialogue.resolutions.append(
                latest.model_copy(update={"status": "rejected"})
            )
    count = len(ids)
    resolution = await engine.summarize(
        resolution_id=f"{thread.id}:resolution:{count + 1}",
        thread=thread,
        contributions=contributions,
        observations=cited,
        names=_display_names(dialogue),
    )
    dialogue.resolutions.append(resolution)
    dialogue.waiting_for = "resolution_decision"
    dialogue.active_thread_id = thread.id


async def message_thread(
    state: SessionState,
    *,
    engine,
    reporter: DialogueReporter = NULL_REPORTER,
    thread_id: str,
    message: str,
    reply_to: str | None = None,
) -> None:
    dialogue = _require_dialogue(state)
    thread = dialogue.latest_thread(thread_id)
    if thread is None or thread.status != "open":
        raise DialogueError("Only an open Thread accepts messages.")
    text = " ".join(message.split())
    if not text:
        raise DialogueError("A message requires text.")

    turns = _thread_contributions(dialogue, thread.id)
    by_id = {contribution.id: contribution for contribution in turns}
    target = by_id.get(reply_to) if reply_to else None
    if target is None:
        target = next(
            (
                contribution
                for contribution in reversed(turns)
                if contribution.author_id != "researcher"
            ),
            None,
        )
    if target is None:
        raise DialogueError("There is no contribution to address yet.")

    now = utcnow()
    counter = len(dialogue.contributions) + 1
    challenge = Contribution(
        id=f"{thread.id}:c{counter}",
        thread_id=thread.id,
        author_id="researcher",
        kind="challenge",
        text=text,
        observation_ids=[],
        evidence_requests=[],
        reply_to=target.id,
        created_at=now,
    )
    dialogue.contributions.append(challenge)
    reporter.turn("Researcher", text)

    states = _states_by_id(dialogue)
    responder = states.get(target.author_id)
    if responder is not None:
        names = _display_names(dialogue)
        contribution = await engine.reply(
            contribution_id=f"{thread.id}:c{counter + 1}",
            perspective_id=responder.id,
            created_at=now,
            thread=thread,
            target=target,
            message=text,
            reply_to=challenge.id,
            profile=responder.profile,
            observations=_grounded_observations(dialogue, responder),
        )
        dialogue.contributions.append(contribution)
        reporter.turn(names[contribution.author_id], contribution.text)

    await _redraft_section(state, engine=engine, thread=thread)
    reporter.stage("resolution", "Updating the pending Resolution.")
    await _summarize_thread(state, engine=engine, thread=thread)


async def decide_dialogue_thread(
    state: SessionState,
    *,
    engine,
    reporter: DialogueReporter = NULL_REPORTER,
    resolution_id: str,
    action: str,
    consensus: str | None = None,
    disagreement: str | None = None,
    open_question: str | None = None,
) -> None:
    dialogue = _require_dialogue(state)
    resolution = dialogue.latest_resolution(resolution_id)
    if resolution is None:
        raise DialogueError("Unknown Resolution.")
    thread = dialogue.latest_thread(resolution.thread_id)
    if thread is None:
        raise DialogueError("The Resolution's Thread is missing.")
    if action not in {"close", "edit_close", "keep_open", "request_evidence"}:
        raise DialogueError("Unknown Thread decision.")

    decided_thread, decided_resolution = decide_resolution(
        thread,
        resolution,
        action=action,
        consensus=consensus,
        disagreement=disagreement,
        open_question=open_question,
    )
    dialogue.threads.append(decided_thread)
    dialogue.resolutions.append(decided_resolution)
    dialogue.waiting_for = None

    if decided_thread.status != "closed":
        reporter.stage("thread", "The Thread stays open for more discussion.")
        return

    dialogue.active_thread_id = None
    reporter.stage("document", "Folding the Resolution into the Document.")
    await _apply_resolution_to_document(
        state,
        engine=engine,
        thread=decided_thread,
        resolution=decided_resolution,
    )

    reporter.stage("reflection", "Affected Perspectives reflect.")
    await _reflect_on_close(
        state,
        engine=engine,
        thread=decided_thread,
        resolution=decided_resolution,
    )

    reporter.stage("threads", "Suggesting the next Threads.")
    await _suggest_next_threads(
        state,
        engine=engine,
        resolution=decided_resolution,
    )


async def _apply_resolution_to_document(
    state: SessionState,
    *,
    engine,
    thread: Thread,
    resolution: Resolution,
) -> None:
    dialogue = _require_dialogue(state)
    section = _section_for(dialogue, thread)
    observations = _observations_by_id(dialogue, resolution.observation_ids)
    suggestion = await engine.suggest_change(
        suggestion_id=f"{thread.id}:suggestion:{section.version}",
        author_id="moderator",
        question=state.problem,
        section=section,
        thread=thread,
        resolution=resolution,
        observations=observations,
    )
    if suggestion is None:
        return
    renumbered, references = renumber_markers(
        suggestion.proposed_text, observations, dialogue.document.references
    )
    suggestion = suggestion.model_copy(
        update={"proposed_text": renumbered or suggestion.proposed_text}
    )
    document, decided, revision = apply_suggestion(
        dialogue.document,
        suggestion,
        action="accept",
        decision_id=f"{resolution.id}:decision",
        revision_id=f"{suggestion.id}:revision",
        created_at=utcnow(),
    )
    if references:
        document = document.model_copy(update={"references": references})
    dialogue.document = document
    dialogue.suggestions.append(decided)
    if revision is not None:
        dialogue.revisions.append(revision)


async def _reflect_on_close(
    state: SessionState,
    *,
    engine,
    thread: Thread,
    resolution: Resolution,
) -> None:
    dialogue = _require_dialogue(state)
    states = _states_by_id(dialogue)
    affected = [
        perspective_id
        for perspective_id in affected_perspectives(
            _thread_contributions(dialogue, thread.id),
            extra=[assignment.perspective_id for assignment in thread.assignments],
        )
        if perspective_id in states
    ]
    if not affected:
        return
    reflections = await engine.reflect(
        question=state.problem,
        thread=thread,
        resolution=resolution,
        perspective_ids=affected,
        perspectives=states,
    )
    dialogue.reflections.extend(reflections)
    for reflection in reflections:
        current = states[reflection.perspective_id]
        _replace_perspective_state(
            dialogue,
            current.model_copy(
                update={
                    "version": reflection.perspective_version,
                    "profile": reflection.profile,
                }
            ),
        )
        if reflection.facet_revisions:
            _mirror_facets_to_focused(state, reflection)


def _mirror_facets_to_focused(state: SessionState, reflection) -> None:
    for perspective in state.perspectives:
        if perspective.id != reflection.perspective_id:
            continue
        for revision in reflection.facet_revisions:
            evidence = perspective.facets.get(revision.facet)
            if evidence is not None:
                evidence.text = revision.text
                evidence.edited = True
    for agent in state.agents:
        if agent.perspective_id == reflection.perspective_id:
            agent.facet_version += 1


async def _suggest_next_threads(
    state: SessionState,
    *,
    engine,
    resolution: Resolution,
) -> None:
    dialogue = _require_dialogue(state)
    current = dialogue.current_threads()
    existing_questions = [thread.question for thread in current]
    existing_titles = [thread.title for thread in current]
    open_questions = [
        text
        for text in (
            resolution.open_question,
            *[refinement.open_question for refinement in _latest_refinements(dialogue)],
        )
        if text
    ]
    _, profiles = _profiles_in_order(dialogue)
    drafts = await engine.suggest_threads(
        question=state.problem,
        objectives=[objective.text for objective in dialogue.document.objectives],
        profiles=profiles,
        open_questions=open_questions,
        existing_questions=existing_questions,
        resolution=resolution_text(resolution),
        unused_observations=[
            observation.text for observation in _unused_observations(dialogue)
        ],
        n=SUGGESTED_THREADS_ON_CLOSE,
    )
    accepted = unique_threads(drafts, existing_questions, existing_titles)
    start = len({thread.id for thread in dialogue.threads})
    for index, draft in enumerate(accepted, start=1):
        dialogue.threads.append(
            Thread(
                id=f"{dialogue.id}:thread:{start + index}",
                version=1,
                status="suggested",
                title=draft.title,
                question=draft.question,
                context=draft.context,
                origin_ids=[resolution.id],
                created_by="moderator",
                created_at=utcnow(),
            )
        )


def continue_from_open_question(
    state: SessionState,
    *,
    resolution_id: str,
) -> None:
    """Turn one uncontinued accepted open question into a suggested Thread."""

    dialogue = _require_dialogue(state)
    if dialogue.stage != "deliberation" or dialogue.document is None:
        raise DialogueError("The Working Document has not been created.")
    if dialogue.waiting_for is not None:
        raise DialogueError("Review the pending Resolution first.")

    current = dialogue.current_threads()
    if any(thread.status in {"open", "suggested"} for thread in current):
        raise DialogueError("Resolve the available Threads before continuing.")

    resolution = dialogue.latest_resolution(resolution_id)
    question = (resolution.open_question or "").strip() if resolution else ""
    if resolution is None or resolution.status != "accepted" or not question:
        raise DialogueError("Choose an open question from an accepted Resolution.")

    identity = " ".join(question.casefold().split())
    if any(
        resolution.id in thread.origin_ids
        or " ".join(thread.question.casefold().split()) == identity
        for thread in current
    ):
        raise DialogueError("This open question already has a Thread.")

    index = len({thread.id for thread in dialogue.threads}) + 1
    dialogue.threads.append(
        Thread(
            id=f"{dialogue.id}:thread:{index}",
            version=1,
            status="suggested",
            title=_clip(question.rstrip("?"), 6),
            question=question,
            context="Continued from an accepted Resolution's open question.",
            origin_ids=[resolution.id],
            created_by="researcher",
            created_at=utcnow(),
        )
    )


def synthesize_report(state: SessionState) -> str:
    """Kat's final Document: hypotheses from closed Threads, open questions."""
    dialogue = _require_dialogue(state)
    document = dialogue.document
    title = (document.title if document else state.problem) or "Investigation"
    lines: list[str] = [f"# {title}", "", "## Hypotheses"]
    closed = [
        thread
        for thread in dialogue.current_threads()
        if thread.status == "closed" and thread.resolution_id
    ]
    index = 0
    for thread in closed:
        resolution = dialogue.latest_resolution(thread.resolution_id)
        if resolution is None or resolution.status != "accepted":
            continue
        statement = resolution.consensus or resolution.disagreement
        if not statement:
            continue
        index += 1
        explanation = ""
        if document is not None and thread.section_id:
            for section in document.sections:
                if section.id == thread.section_id:
                    explanation = section.text
        lines.extend(
            [
                "",
                f"### {thread.title}",
                "",
                f"**H{index}.** {statement}",
                "",
                f"**Explanation.** {explanation or resolution.consensus}",
            ]
        )
    if index == 0:
        lines.extend(["", "_No Threads have been resolved yet._"])
    open_questions: list[str] = []
    for thread in dialogue.current_threads():
        if thread.status == "suggested":
            open_questions.append(thread.question)
    for resolution in dialogue.resolutions:
        if resolution.status == "accepted" and resolution.open_question:
            open_questions.append(resolution.open_question)
    lines.extend(["", "## Open Questions", ""])
    if open_questions:
        lines.extend(
            f"{number}. {question}"
            for number, question in enumerate(dict.fromkeys(open_questions), start=1)
        )
    else:
        lines.append("_None recorded._")
    return "\n".join(lines) + "\n"


__all__ = [
    "NULL_REPORTER",
    "DemoDialogueEngine",
    "DialogueError",
    "DialogueReporter",
    "LiveDialogueEngine",
    "corpus_observations",
    "decide_dialogue_thread",
    "message_thread",
    "open_dialogue_thread",
    "perspective_states",
    "researcher_profile",
    "select_directions",
    "start_dialogue",
    "synthesize_report",
]
