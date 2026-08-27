"""Group-chat stage over a four-part notepad.

Implements the surface Youngseung specified: a notepad of four parts with
independent versions, a group chat whose participants are the panel's
Perspectives, and summaries that reach the notepad only through an
explicit researcher decision.

The two study arms share this module. The arm decides how a turn is
produced and whether a notepad write must be reviewed:

* ``baseline`` - personas speak without grounding; a summary is copied
  into a part directly.
* ``guided`` - Perspectives speak from their abstract-grounded facets and
  cite evidence; a summary arrives as a proposal the researcher must
  approve, edit, or reject, following the human-in-the-loop decision
  vocabulary Kat referenced.

No dspy import lives here. Live turns are produced through the existing
``FocusedProvider`` task boundary, so this module stays importable in the
hermetic tests.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from agora.focused.models import (
    NOTEPAD_LABELS,
    ExpPaper,
    NotepadDoc,
    NotepadPart,
    NotepadProposal,
    NotepadState,
    NotepadTurn,
    NotepadVersion,
    Perspective,
    SessionState,
)

MAX_DISCUSSION_TURNS = 8
MAX_VERSIONS = 8
SUMMARY_AUTHOR = "moderator"


class NotepadError(Exception):
    """A notepad command hit an invalid state."""


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _facet_text(perspective: Perspective, facet: str) -> str:
    evidence = perspective.facets.get(facet)  # type: ignore[arg-type]
    return " ".join((evidence.text if evidence else "").split())


def _sentence(text: str) -> str:
    body = " ".join((text or "").split())
    if not body:
        return ""
    body = body[0].upper() + body[1:]
    return body if body.endswith((".", "?", "!")) else f"{body}."


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _quote(text: str, words: int = 12) -> str:
    """A short quotation of the researcher's own wording.

    Quoted and self-contained: never spliced into a subordinate clause,
    which is what produced ungrammatical turns.
    """
    parts = " ".join(text.split()).rstrip(".").split()
    if not parts:
        return ""
    clipped = " ".join(parts[:words])
    tail = "..." if len(parts) > words else ""
    return f'"{clipped}{tail}"'


def _source_paper(state: SessionState, perspective: Perspective) -> ExpPaper | None:
    for source in perspective.sources:
        for paper in state.papers:
            if paper.id == source:
                return paper
    return None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def start_notepad(state: SessionState) -> NotepadState:
    """Open the group-chat stage, seeding v1 from the input screen."""
    if state.notepad is not None:
        return state.notepad
    if not state.perspectives:
        raise NotepadError("Build at least one Perspective first.")
    version = NotepadVersion(
        id=_new_id("ver"),
        name="v1",
        doc=NotepadDoc(**state.position.model_dump()),
    )
    notepad = NotepadState(
        id=state.id,
        versions=[version],
        active_version_id=version.id,
        in_chat=[perspective.id for perspective in state.perspectives],
    )
    state.notepad = notepad
    return notepad


def _require(state: SessionState) -> NotepadState:
    if state.notepad is None:
        raise NotepadError("The group chat has not started yet.")
    return state.notepad


def edit_part(state: SessionState, *, part: NotepadPart, text: str) -> NotepadState:
    """Researcher edit. Never reviewed, never blocked."""
    notepad = _require(state)
    version = notepad.active_version()
    if version is None:
        raise NotepadError("No notepad version is open.")
    setattr(version.doc, part, text)
    return notepad


def add_version(state: SessionState, *, copy_current: bool) -> NotepadState:
    notepad = _require(state)
    if len(notepad.versions) >= MAX_VERSIONS:
        raise NotepadError(f"A notepad holds at most {MAX_VERSIONS} versions.")
    current = notepad.active_version()
    doc = (
        NotepadDoc(**current.doc.model_dump())
        if copy_current and current is not None
        else NotepadDoc()
    )
    version = NotepadVersion(
        id=_new_id("ver"),
        name=f"v{len(notepad.versions) + 1}",
        doc=doc,
        created_from=current.id if copy_current and current else None,
    )
    notepad.versions.append(version)
    notepad.active_version_id = version.id
    return notepad


def switch_version(state: SessionState, *, version_id: str) -> NotepadState:
    notepad = _require(state)
    if all(version.id != version_id for version in notepad.versions):
        raise NotepadError("Unknown notepad version.")
    notepad.active_version_id = version_id
    return notepad


def delete_version(state: SessionState, *, version_id: str) -> NotepadState:
    notepad = _require(state)
    if len(notepad.versions) <= 1:
        raise NotepadError("The last version cannot be deleted.")
    notepad.versions = [
        version for version in notepad.versions if version.id != version_id
    ]
    if notepad.active_version_id == version_id:
        notepad.active_version_id = notepad.versions[-1].id
    # Pending proposals against a deleted version can no longer apply.
    for proposal in notepad.proposals:
        if proposal.version_id == version_id and proposal.status == "pending":
            proposal.status = "rejected"
            proposal.decision_reason = "Its notepad version was deleted."
    return notepad


def set_in_chat(
    state: SessionState, *, perspective_id: str, participating: bool
) -> NotepadState:
    notepad = _require(state)
    known = {perspective.id for perspective in state.perspectives}
    if perspective_id not in known:
        raise NotepadError("Unknown Perspective.")
    if participating and perspective_id not in notepad.in_chat:
        notepad.in_chat.append(perspective_id)
    if not participating:
        notepad.in_chat = [item for item in notepad.in_chat if item != perspective_id]
    return notepad


def clear_chat(state: SessionState) -> NotepadState:
    """Clear the conversation. The notepad is untouched."""
    notepad = _require(state)
    notepad.turns = []
    notepad.turn_cursor = 0
    notepad.turns.append(
        NotepadTurn(
            id=_new_id("turn"),
            role="system",
            text="Chat cleared. The notepad is unchanged.",
        )
    )
    return notepad


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


def _cast(state: SessionState, notepad: NotepadState) -> list[Perspective]:
    order = {pid: index for index, pid in enumerate(notepad.in_chat)}
    cast = [p for p in state.perspectives if p.id in order]
    cast.sort(key=lambda p: order[p.id])
    return cast


def _transcript(notepad: NotepadState, limit: int = 12) -> list[str]:
    return [
        f"{turn.author_label or turn.role}: {turn.text}"
        for turn in notepad.turns[-limit:]
        if turn.role in {"researcher", "perspective"}
    ]


def _guided_line(
    state: SessionState,
    perspective: Perspective,
    doc: NotepadDoc,
    index: int,
    *,
    round_n: int = 0,
    prior: Perspective | None = None,
) -> tuple[str, list[str]]:
    """A grounded turn: the Perspective's own facet evidence, cited.

    A speaker's first turn states its claim against the researcher's own
    wording. Later turns answer the previous speaker by name, so the
    transcript reads as an exchange instead of repeating the opening.
    """
    paper = _source_paper(state, perspective)
    citation = [paper.id] if paper else []
    explanation = _facet_text(perspective, "explanation")
    approach = _facet_text(perspective, "approach")
    scope = _facet_text(perspective, "scope")
    significance = _facet_text(perspective, "significance")
    marker = " [1]" if citation else ""
    if round_n > 0 and prior is not None:
        own = explanation or significance or scope
        if index % 2 == 0:
            text = (
                f"{prior.name}, you are holding the outcome measure fixed. "
                f"Did you say that because the effect only shows up there? I "
                f"read it the other way: {_lower_first(_sentence(own).rstrip('.'))}"
                f"{marker}."
            )
        else:
            text = (
                f"Yes, and the reason is {_lower_first(_sentence(own).rstrip('.'))}"
                f"{marker}. Where {prior.name} and I part is what counts as the "
                "endpoint, not whether the trade-off is real."
            )
        return text, citation

    if index % 3 == 0 and explanation:
        quote = _quote(doc.framing)
        pointer = (
            f"You framed it as {quote}. That puts the outcome first, where my "
            "evidence makes the mechanism the question."
            if quote
            else (
                "Your framing does not say where the mechanism enters, and on "
                "this evidence that is what decides the answer."
            )
        )
        text = f"{_sentence(explanation).rstrip('.')}{marker}. {pointer}"
    elif index % 3 == 1 and approach:
        quote = _quote(doc.method)
        pointer = (
            f"Your methodology reads {quote}. Measured that way it would not "
            "register the effect I am pointing at."
            if quote
            else (
                "Your methodology does not fix how exposure is measured, and "
                "the measure decides whether the effect shows up at all."
            )
        )
        text = f"{_sentence(approach).rstrip('.')}{marker}. {pointer}"
    else:
        base = significance or scope
        quote = _quote(doc.expected)
        pointer = (
            f"You expect {quote}. That holds only inside the conditions my "
            "evidence covers."
            if quote
            else (
                "Your expected result is not stated, so there is nothing yet "
                "for my evidence to hold against."
            )
        )
        text = f"{_sentence(base).rstrip('.')}{marker}. {pointer}"
    return text, citation


def _baseline_line(
    perspective: Perspective,
    index: int,
    *,
    round_n: int = 0,
    prior: Perspective | None = None,
) -> tuple[str, list[str]]:
    """An ungrounded turn: the persona's own description, no citation.

    Later turns address the previous speaker so the transcript does not
    repeat verbatim. Turn-taking is not perspective guidance: these turns
    still cite nothing and never reference the notepad.
    """
    if round_n > 0 and prior is not None:
        replies = [
            (
                f"{prior.name}, that is where I disagree. The harm you are "
                "pricing is not the harm I am pricing."
            ),
            (
                f"I hear {prior.name}, but the same reasoning would justify the "
                "opposite call, which tells me the reasoning is not doing the "
                "work."
            ),
            (
                f"{prior.name} and I want different things from the same "
                "number. That is the whole disagreement."
            ),
            (
                "Say more about the endpoint. If it is cure, I concede the "
                "point; if it is carriage, I do not."
            ),
            (
                "That framing settles the answer before the question is asked, "
                "which is why we keep landing in different places."
            ),
        ]
        return replies[index % len(replies)], []

    # First sentence only, kept as its own sentence: the persona's blurb runs
    # several sentences, and wrapping it in a frame produced broken prose.
    blurb = " ".join((perspective.summary or perspective.name).split())
    lead = blurb.split(". ")[0].rstrip(".")
    openers = [
        f"{lead}. That is what I am weighing here.",
        (
            "I would push back on that. The measure I care about would not "
            "register the effect you are describing."
        ),
        (
            "Both of those hold only if exposure is measured the same way. It "
            "usually is not, and that is where the disagreement lives."
        ),
    ]
    return openers[index % len(openers)], []


def discuss(
    state: SessionState,
    *,
    turns: int,
    guided: bool,
) -> NotepadState:
    """Run a bounded round of agent turns. Cost is stated before the click."""
    notepad = _require(state)
    if turns < 1 or turns > MAX_DISCUSSION_TURNS:
        raise NotepadError(f"Choose between 1 and {MAX_DISCUSSION_TURNS} turns.")
    cast = _cast(state, notepad)
    if not cast:
        raise NotepadError("Nobody is in the chat. Add a Perspective first.")
    version = notepad.active_version()
    doc = version.doc if version else NotepadDoc()
    for offset in range(turns):
        cursor = notepad.turn_cursor + offset
        speaker = cast[cursor % len(cast)]
        if guided:
            text, citations = _guided_line(
                state,
                speaker,
                doc,
                cursor,
                round_n=cursor // len(cast),
                prior=cast[(cursor - 1) % len(cast)] if cursor > 0 else None,
            )
        else:
            text, citations = _baseline_line(
                speaker,
                cursor,
                round_n=cursor // len(cast),
                prior=cast[(cursor - 1) % len(cast)] if cursor > 0 else None,
            )
        notepad.turns.append(
            NotepadTurn(
                id=_new_id("turn"),
                role="perspective",
                author_id=speaker.id,
                author_label=speaker.name,
                text=text,
                citations=citations,
            )
        )
    notepad.turn_cursor += turns
    return notepad


def ask(
    state: SessionState,
    *,
    message: str,
    guided: bool,
) -> NotepadState:
    """The researcher speaks; the next participant answers once."""
    notepad = _require(state)
    text = " ".join(message.split())
    if not text:
        raise NotepadError("A message requires text.")
    notepad.turns.append(
        NotepadTurn(
            id=_new_id("turn"),
            role="researcher",
            author_label="You",
            text=text,
        )
    )
    cast = _cast(state, notepad)
    if not cast:
        return notepad
    speaker = cast[notepad.turn_cursor % len(cast)]
    version = notepad.active_version()
    doc = version.doc if version else NotepadDoc()
    if guided:
        reply, citations = _guided_line(state, speaker, doc, notepad.turn_cursor)
    else:
        reply, citations = _baseline_line(speaker, notepad.turn_cursor)
    notepad.turn_cursor += 1
    notepad.turns.append(
        NotepadTurn(
            id=_new_id("turn"),
            role="perspective",
            author_id=speaker.id,
            author_label=speaker.name,
            text=reply,
            citations=citations,
        )
    )
    return notepad


# ---------------------------------------------------------------------------
# Summaries: the only path from the chat into the notepad
# ---------------------------------------------------------------------------


def _summary_text(notepad: NotepadState, cast: Sequence[Perspective]) -> str:
    names = ", ".join(p.name for p in cast[:3])
    return (
        f"The discussion so far turns on where each account stops holding. "
        f"{names} agree the trade-off is real, but the outcome and the timing "
        f"of harm are not settled: the measure decides the answer."
    )


def summarize(
    state: SessionState,
    *,
    part: NotepadPart,
    guided: bool,
) -> NotepadState:
    """Summarize the discussion for one notepad part.

    Both arms stage the summary and wait for the researcher: the baseline
    exposes Youngseung's single ``Copy into the notepad`` seam, the guided arm
    exposes the same seam as a reviewable proposal carrying its evidence and
    a reason. Only the affordance differs, so a measured difference is
    attributable to perspective guidance rather than to step count.
    """
    notepad = _require(state)
    spoken = [turn for turn in notepad.turns if turn.role == "perspective"]
    if len(spoken) < 2:
        raise NotepadError("Not much to summarize yet.")
    version = notepad.active_version()
    if version is None:
        raise NotepadError("No notepad version is open.")
    cast = _cast(state, notepad)
    summary = _summary_text(notepad, cast)
    current = getattr(version.doc, part)
    proposed = f"{current} {summary}".strip() if current else summary

    citations = (
        list(dict.fromkeys(c for turn in spoken for c in turn.citations))
        if guided
        else []
    )
    notepad.turns.append(
        NotepadTurn(
            id=_new_id("turn"),
            role="summary",
            author_label="Panel summary" if guided else "Summary",
            text=summary,
            citations=citations,
        )
    )

    if not guided:
        # The baseline summary card carries no diff, reason, or evidence:
        # one button blind-appends it.
        notepad.proposals.append(
            NotepadProposal(
                id=_new_id("prop"),
                version_id=version.id,
                part=part,
                author_id=SUMMARY_AUTHOR,
                author_label="Summary",
                current_text=current,
                proposed_text=proposed,
                addition=summary,
            )
        )
        return notepad

    notepad.proposals.append(
        NotepadProposal(
            id=_new_id("prop"),
            version_id=version.id,
            part=part,
            author_id=SUMMARY_AUTHOR,
            author_label="Panel summary",
            current_text=current,
            proposed_text=proposed,
            addition=summary,
            reason=(
                f"The discussion bears on {NOTEPAD_LABELS[part]}; this folds "
                "what the panel settled into that part."
            ),
            citations=citations,
        )
    )
    return notepad


def decide_proposal(
    state: SessionState,
    *,
    proposal_id: str,
    action: str,
    text: str | None = None,
    reason: str = "",
) -> NotepadState:
    """Approve, edit, or reject a pending proposal.

    The decision vocabulary matches the human-in-the-loop middleware Kat
    referenced: approve takes it as written, edit takes the researcher's
    wording, reject records why so a later proposal can differ.
    """
    notepad = _require(state)
    if action not in {"approve", "edit", "reject"}:
        raise NotepadError("Unknown decision.")
    proposal = next(
        (item for item in notepad.proposals if item.id == proposal_id), None
    )
    if proposal is None:
        raise NotepadError("Unknown proposal.")
    if proposal.status != "pending":
        raise NotepadError("That proposal has already been decided.")
    version = next(
        (item for item in notepad.versions if item.id == proposal.version_id),
        None,
    )
    if version is None:
        raise NotepadError("The proposal's notepad version is gone.")

    if action == "reject":
        proposal.status = "rejected"
        proposal.decision_reason = " ".join(reason.split())
        notepad.turns.append(
            NotepadTurn(
                id=_new_id("turn"),
                role="system",
                text=(
                    "Researcher rejected the proposed "
                    f"{NOTEPAD_LABELS[proposal.part]} change"
                    + (f": {proposal.decision_reason}" if reason.strip() else ".")
                ),
            )
        )
        return notepad

    live = getattr(version.doc, proposal.part)
    rebased = live != proposal.current_text
    if action == "approve":
        # The notepad stays editable while a proposal is pending, so the
        # researcher's newer wording wins and the panel's addition folds
        # onto it. Writing proposal.proposed_text here would silently
        # restore the text the proposal was raised against.
        addition = proposal.addition or proposal.proposed_text
        accepted = f"{live} {addition}".strip() if live else addition
    else:
        accepted = " ".join((text or "").split())
    if not accepted:
        raise NotepadError("An edited proposal requires replacement text.")
    setattr(version.doc, proposal.part, accepted)
    proposal.status = "accepted" if action == "approve" else "edited"
    proposal.decided_text = accepted
    if action == "approve":
        detail = "folded into your newer wording" if rebased else "as proposed"
    else:
        detail = "researcher wording"
    notepad.turns.append(
        NotepadTurn(
            id=_new_id("turn"),
            role="system",
            text=f"{NOTEPAD_LABELS[proposal.part]} updated in {version.name} ({detail}).",
        )
    )
    return notepad


__all__ = [
    "MAX_DISCUSSION_TURNS",
    "NotepadError",
    "add_version",
    "ask",
    "clear_chat",
    "decide_proposal",
    "delete_version",
    "discuss",
    "edit_part",
    "set_in_chat",
    "start_notepad",
    "summarize",
    "switch_version",
]
