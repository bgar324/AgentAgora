"""Baseline four-part draft and persistent multi-Perspective review agenda."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from agora.focused.models import (
    NOTEPAD_PARTS,
    NotepadAgenda,
    NotepadDoc,
    NotepadFinalSnapshot,
    NotepadPart,
    NotepadState,
    NotepadTurn,
    NotepadVersion,
    Perspective,
    SessionState,
    Statement,
    utcnow,
)

MAX_DISCUSSION_TURNS = 8
MAX_VERSIONS = 8
MAX_PERSPECTIVES = 6


class NotepadError(Exception):
    """A baseline study command hit an invalid state."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ReviewTurnPlan:
    version_id: str
    review_n: int
    part: NotepadPart
    phase: Literal["feedback", "comparison"]
    comparison_cycle: int
    speaker: Perspective
    subject_text: str
    feedback: tuple[NotepadTurn, ...]


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _require(state: SessionState) -> NotepadState:
    if state.notepad is None:
        raise NotepadError("The discussion has not started yet.")
    return state.notepad


def _ensure_open(notepad: NotepadState) -> None:
    if notepad.final_snapshot is not None:
        raise NotepadError("This study is finished and read-only.", status=409)


def _version(notepad: NotepadState, version_id: str) -> NotepadVersion:
    version = next((item for item in notepad.versions if item.id == version_id), None)
    if version is None:
        raise NotepadError(
            f"Document version '{version_id}' was not found.",
            status=404,
        )
    return version


def _cast(state: SessionState, notepad: NotepadState) -> list[Perspective]:
    by_id = {perspective.id: perspective for perspective in state.perspectives}
    return [by_id[identifier] for identifier in notepad.in_chat if identifier in by_id]


def _fresh_agenda(
    doc: NotepadDoc, participants: list[str], review_n: int = 1
) -> NotepadAgenda:
    return NotepadAgenda(
        review_n=review_n,
        part="framing",
        phase="feedback",
        subject_text=doc.framing,
        participant_ids=list(participants),
    )


def start_notepad(state: SessionState) -> NotepadState:
    """Open Step 3 and seed v1 from Step 1. Idempotent."""
    if state.notepad is not None:
        return state.notepad
    if not state.perspectives:
        raise NotepadError("Build at least one Perspective first.")
    participants = [perspective.id for perspective in state.perspectives]
    version = NotepadVersion(
        id=_new_id("ver"),
        name="v1",
        doc=NotepadDoc(**state.position.model_dump()),
    )
    version.agenda = _fresh_agenda(version.doc, participants)
    state.notepad = NotepadState(
        id=state.id,
        versions=[version],
        active_version_id=version.id,
        in_chat=participants,
    )
    return state.notepad


def edit_part(
    state: SessionState,
    *,
    version_id: str,
    part: NotepadPart,
    text: str,
) -> NotepadState:
    notepad = _require(state)
    _ensure_open(notepad)
    version = _version(notepad, version_id)
    setattr(version.doc, part, text)
    if version.agenda.part == part and version.agenda.phase != "complete":
        version.agenda.subject_text = text
    return notepad


def add_version(state: SessionState, *, copy_current: bool) -> NotepadState:
    notepad = _require(state)
    _ensure_open(notepad)
    if len(notepad.versions) >= MAX_VERSIONS:
        raise NotepadError(f"A Document holds at most {MAX_VERSIONS} versions.")
    current = notepad.active_version()
    doc = (
        NotepadDoc(**current.doc.model_dump())
        if copy_current and current is not None
        else NotepadDoc()
    )
    version_numbers = [
        int(version.name[1:])
        for version in notepad.versions
        if version.name.startswith("v") and version.name[1:].isdigit()
    ]
    version = NotepadVersion(
        id=_new_id("ver"),
        name=f"v{max(version_numbers, default=0) + 1}",
        doc=doc,
        agenda=_fresh_agenda(doc, notepad.in_chat),
        created_from=current.id if copy_current and current else None,
    )
    notepad.versions.append(version)
    notepad.active_version_id = version.id
    return notepad


def switch_version(state: SessionState, *, version_id: str) -> NotepadState:
    notepad = _require(state)
    _version(notepad, version_id)
    notepad.active_version_id = version_id
    return notepad


def delete_version(state: SessionState, *, version_id: str) -> NotepadState:
    notepad = _require(state)
    _ensure_open(notepad)
    if len(notepad.versions) <= 1:
        raise NotepadError("The last version cannot be deleted.")
    _version(notepad, version_id)
    notepad.versions = [item for item in notepad.versions if item.id != version_id]
    notepad.turns = [turn for turn in notepad.turns if turn.version_id != version_id]
    if notepad.active_version_id == version_id:
        notepad.active_version_id = notepad.versions[0].id
    return notepad


def clear_chat(state: SessionState) -> NotepadState:
    notepad = _require(state)
    _ensure_open(notepad)
    version = notepad.active_version()
    if version is None:
        raise NotepadError("No Document version is open.")
    version.visible_turn_start = sum(
        turn.version_id == version.id for turn in notepad.turns
    )
    notepad.turns.append(
        NotepadTurn(
            id=_new_id("turn"),
            version_id=version.id,
            kind="system",
            role="system",
            text="Chat cleared. The document and review progress are unchanged.",
        )
    )
    return notepad


def _sync_participants(
    state: SessionState, version: NotepadVersion
) -> list[Perspective]:
    agenda = version.agenda
    cast = _cast(state, _require(state))
    cast_ids = [perspective.id for perspective in cast]
    previous_ids = list(agenda.participant_ids)
    newcomers = [
        identifier for identifier in cast_ids if identifier not in previous_ids
    ]
    if newcomers:
        agenda.participant_ids.extend(newcomers)
        if agenda.phase in {"comparison", "complete"}:
            agenda.phase = "feedback"
            agenda.completed_at = None
            agenda.feedback_done_ids = [
                identifier
                for identifier in agenda.feedback_done_ids
                if identifier in previous_ids
            ]
            agenda.comparison_done_ids = []
            agenda.comparison_cycle += 1
    agenda.participant_ids = [
        identifier for identifier in agenda.participant_ids if identifier in cast_ids
    ]
    agenda.feedback_done_ids = [
        identifier for identifier in agenda.feedback_done_ids if identifier in cast_ids
    ]
    agenda.comparison_done_ids = [
        identifier
        for identifier in agenda.comparison_done_ids
        if identifier in cast_ids
    ]
    if (
        cast_ids
        and agenda.phase == "feedback"
        and set(agenda.feedback_done_ids) >= set(agenda.participant_ids)
    ):
        agenda.phase = "comparison"
    if (
        cast_ids
        and agenda.phase == "comparison"
        and set(agenda.comparison_done_ids) >= set(agenda.participant_ids)
    ):
        _advance_element(version)
    return cast


def reconcile_roster(state: SessionState) -> NotepadState:
    """Apply the current Perspective roster to every version agenda."""
    notepad = _require(state)
    _ensure_open(notepad)
    for version in notepad.versions:
        _sync_participants(state, version)
    return notepad


def _feedback_turns(
    notepad: NotepadState,
    version: NotepadVersion,
) -> tuple[NotepadTurn, ...]:
    agenda = version.agenda
    return tuple(
        turn
        for turn in notepad.turns
        if turn.version_id == version.id
        and turn.review_n == agenda.review_n
        and turn.part == agenda.part
        and turn.kind == "feedback"
        and turn.author_id in agenda.participant_ids
    )


def remaining_review_turns(state: SessionState, *, version_id: str) -> int:
    """Return the exact number of agenda turns left before terminal completion."""
    notepad = _require(state)
    _ensure_open(notepad)
    version = _version(notepad, version_id)
    agenda = version.agenda
    cast = _sync_participants(state, version)
    if not cast:
        raise NotepadError("No Perspectives are available. Build one first.")
    if agenda.phase == "complete":
        return 0
    participant_count = len(agenda.participant_ids)
    part_index = NOTEPAD_PARTS.index(agenda.part)
    future_parts = len(NOTEPAD_PARTS) - part_index - 1
    if agenda.phase == "feedback":
        current = participant_count - len(agenda.feedback_done_ids) + participant_count
    else:
        current = participant_count - len(agenda.comparison_done_ids)
    return current + future_parts * participant_count * 2


def plan_review_turn(
    state: SessionState, *, version_id: str, turns: int
) -> ReviewTurnPlan:
    notepad = _require(state)
    _ensure_open(notepad)
    if turns < 1 or turns > MAX_DISCUSSION_TURNS:
        raise NotepadError(f"Choose between 1 and {MAX_DISCUSSION_TURNS} turns.")
    version = _version(notepad, version_id)
    agenda = version.agenda
    agenda.turn_budget = turns
    cast = _sync_participants(state, version)
    if not cast:
        raise NotepadError("Nobody is in the chat. Add a Perspective first.")
    if agenda.phase == "complete":
        raise NotepadError(
            "This draft review is complete. Start another review to continue."
        )

    by_id = {perspective.id: perspective for perspective in cast}
    feedback_missing = [
        identifier
        for identifier in agenda.participant_ids
        if identifier not in agenda.feedback_done_ids
    ]
    if feedback_missing:
        agenda.phase = "feedback"
        speaker = by_id[feedback_missing[0]]
        phase = "feedback"
    else:
        agenda.phase = "comparison"
        comparison_missing = [
            identifier
            for identifier in agenda.participant_ids
            if identifier not in agenda.comparison_done_ids
        ]
        if not comparison_missing:
            raise NotepadError("The current review element is ready to advance.")
        speaker = by_id[comparison_missing[0]]
        phase = "comparison"

    return ReviewTurnPlan(
        version_id=version.id,
        review_n=agenda.review_n,
        part=agenda.part,
        phase=phase,
        comparison_cycle=agenda.comparison_cycle,
        speaker=speaker,
        subject_text=agenda.subject_text,
        feedback=_feedback_turns(notepad, version),
    )


def _advance_element(version: NotepadVersion) -> None:
    agenda = version.agenda
    index = NOTEPAD_PARTS.index(agenda.part)
    if index == len(NOTEPAD_PARTS) - 1:
        agenda.phase = "complete"
        agenda.completed_at = utcnow()
        return
    agenda.part = NOTEPAD_PARTS[index + 1]
    agenda.phase = "feedback"
    agenda.subject_text = getattr(version.doc, agenda.part)
    agenda.feedback_done_ids = []
    agenda.comparison_done_ids = []
    agenda.comparison_cycle = 1


def record_review_turn(
    state: SessionState,
    *,
    plan: ReviewTurnPlan,
    statement: Statement,
) -> NotepadState:
    notepad = _require(state)
    _ensure_open(notepad)
    version = _version(notepad, plan.version_id)
    agenda = version.agenda
    if plan.review_n != agenda.review_n or plan.part != agenda.part:
        raise NotepadError("The review agenda changed before the turn was recorded.")
    notepad.turns.append(
        NotepadTurn(
            id=_new_id("turn"),
            version_id=version.id,
            kind=plan.phase,
            role="perspective",
            author_id=plan.speaker.id,
            author_label=plan.speaker.name,
            text=statement.text,
            citations=statement.citations,
            review_n=agenda.review_n,
            part=agenda.part,
            comparison_cycle=agenda.comparison_cycle,
        )
    )
    target = (
        agenda.feedback_done_ids
        if plan.phase == "feedback"
        else agenda.comparison_done_ids
    )
    if plan.speaker.id not in target:
        target.append(plan.speaker.id)
    agenda.turns_emitted += 1
    if plan.phase == "feedback" and set(agenda.feedback_done_ids) >= set(
        agenda.participant_ids
    ):
        agenda.phase = "comparison"
    if plan.phase == "comparison" and set(agenda.comparison_done_ids) >= set(
        agenda.participant_ids
    ):
        _advance_element(version)
    return notepad


def next_direct_speakers(state: SessionState) -> list[Perspective]:
    notepad = _require(state)
    _ensure_open(notepad)
    cast = _cast(state, notepad)
    if not cast:
        raise NotepadError("Nobody is in the chat. Add a Perspective first.")
    return cast


def record_direct_exchange(
    state: SessionState,
    *,
    version_id: str,
    message: str,
    replies: list[tuple[Perspective, Statement]],
    topic_id: str | None = None,
) -> NotepadState:
    notepad = _require(state)
    _ensure_open(notepad)
    version = _version(notepad, version_id)
    text = " ".join(message.split())
    if not text:
        raise NotepadError("A message requires text.")
    user_turn = NotepadTurn(
        id=_new_id("turn"),
        version_id=version.id,
        kind="researcher",
        role="researcher",
        author_label="You",
        text=text,
        topic_id=topic_id,
    )
    notepad.turns.append(user_turn)
    for perspective, statement in replies:
        notepad.turns.append(
            NotepadTurn(
                id=_new_id("turn"),
                version_id=version.id,
                kind="direct_reply",
                role="perspective",
                author_id=perspective.id,
                author_label=perspective.name,
                text=statement.text,
                citations=statement.citations,
                reply_to_turn_id=user_turn.id,
                topic_id=topic_id,
            )
        )
        version.agenda.turns_emitted += 1
    return notepad


def record_summary(
    state: SessionState,
    *,
    version_id: str,
    statement: Statement,
) -> NotepadState:
    notepad = _require(state)
    _ensure_open(notepad)
    version = _version(notepad, version_id)
    notepad.turns.append(
        NotepadTurn(
            id=_new_id("turn"),
            version_id=version.id,
            kind="summary",
            role="summary",
            author_label="Summary",
            text=statement.text,
            citations=statement.citations,
            review_n=version.agenda.review_n,
            part=version.agenda.part,
        )
    )
    return notepad


def restart_review(state: SessionState, *, version_id: str) -> NotepadState:
    notepad = _require(state)
    _ensure_open(notepad)
    version = _version(notepad, version_id)
    if version.agenda.phase != "complete":
        raise NotepadError("Finish the current review before starting another.")
    version.agenda = _fresh_agenda(
        version.doc,
        notepad.in_chat,
        review_n=version.agenda.review_n + 1,
    )
    return notepad


def finish_study(state: SessionState) -> NotepadState:
    notepad = _require(state)
    if notepad.final_snapshot is None:
        notepad.final_snapshot = NotepadFinalSnapshot(
            versions=[version.model_copy(deep=True) for version in notepad.versions]
        )
    return notepad


__all__ = [
    "MAX_DISCUSSION_TURNS",
    "MAX_PERSPECTIVES",
    "MAX_VERSIONS",
    "NotepadError",
    "ReviewTurnPlan",
    "add_version",
    "clear_chat",
    "delete_version",
    "edit_part",
    "finish_study",
    "next_direct_speakers",
    "plan_review_turn",
    "reconcile_roster",
    "record_direct_exchange",
    "record_review_turn",
    "record_summary",
    "remaining_review_turns",
    "restart_review",
    "start_notepad",
    "switch_version",
]
