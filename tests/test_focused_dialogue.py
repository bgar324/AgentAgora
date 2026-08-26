"""Thread-centered dialogue protocol over the canonical deliberation engine."""

from __future__ import annotations

import asyncio

import pytest

from agora.focused.service import FocusedPanelService, SessionError

PROBLEM = "Should antibiotics be prescribed broadly?"


async def _dialogue_panel(
    perspectives: int = 3,
) -> tuple[FocusedPanelService, str]:
    service = FocusedPanelService()
    state = service.create_workspace(
        problem=PROBLEM, research_questions=[], demo=True
    ).active
    state = await service.suggest_queries(state.id)
    state = await service.run_search(
        state.id,
        [query.query for query in state.suggested_queries[:3]],
    )
    for cluster in state.clusters[:perspectives]:
        state = await service.generate_perspective(
            state.id,
            cluster_id=cluster.id,
        )
    return service, state.id


async def _to_selection(service: FocusedPanelService, session_id: str) -> None:
    await service.start_dialogue(session_id)


async def _to_deliberation(service: FocusedPanelService, session_id: str) -> None:
    await _to_selection(service, session_id)
    dialogue = service.get(session_id).dialogue
    assert dialogue is not None
    proposal_ids = list(dict.fromkeys(proposal.id for proposal in dialogue.proposals))
    await service.select_dialogue_directions(session_id, proposal_ids=proposal_ids[:2])


async def _to_pending_resolution(service: FocusedPanelService, session_id: str) -> str:
    await _to_deliberation(service, session_id)
    dialogue = service.get(session_id).dialogue
    thread = next(
        thread for thread in dialogue.current_threads() if thread.status == "suggested"
    )
    await service.open_dialogue_thread(session_id, thread_id=thread.id)
    return thread.id


def _pending_resolution_id(service: FocusedPanelService, session_id: str) -> str:
    dialogue = service.get(session_id).dialogue
    pending = [
        resolution.id
        for resolution in dialogue.resolutions
        if dialogue.latest_resolution(resolution.id).status == "pending"
    ]
    assert pending, "expected a pending resolution"
    return pending[-1]


def test_opening_produces_reviewed_refinements_and_waits_for_selection() -> None:
    async def go() -> None:
        service, session_id = await _dialogue_panel()
        await _to_selection(service, session_id)
        state = service.get(session_id)
        dialogue = state.dialogue
        assert dialogue is not None
        assert dialogue.stage == "selection"
        assert dialogue.waiting_for == "proposal_selection"
        panel = len(state.perspectives)
        assert len({p.id for p in dialogue.proposals}) == panel
        assert len(dialogue.reviews) == panel
        assert len(dialogue.refinements) == panel
        # every proposal cites at least one supporting observation
        for proposal in dialogue.proposals:
            assert proposal.argument.evidence
            assert any(
                item.relation == "support" for item in proposal.argument.evidence
            )
        # observations are grounded in the searched corpus
        paper_ids = {paper.id for paper in state.papers}
        assert dialogue.observations
        assert {
            observation.source_id for observation in dialogue.observations
        } <= paper_ids

    asyncio.run(go())


def test_opening_requires_two_perspectives() -> None:
    async def go() -> None:
        service, session_id = await _dialogue_panel(perspectives=1)
        with pytest.raises(SessionError):
            await service.start_dialogue(session_id)

    asyncio.run(go())


def test_selection_creates_document_and_suggested_threads() -> None:
    async def go() -> None:
        service, session_id = await _dialogue_panel()
        await _to_deliberation(service, session_id)
        dialogue = service.get(session_id).dialogue
        assert dialogue.stage == "deliberation"
        assert dialogue.waiting_for is None
        assert dialogue.document is not None
        assert dialogue.document.objectives
        threads = dialogue.current_threads()
        assert threads
        assert all(thread.status == "suggested" for thread in threads)

    asyncio.run(go())


def test_open_thread_runs_answers_exchange_and_pends_resolution() -> None:
    async def go() -> None:
        service, session_id = await _dialogue_panel()
        thread_id = await _to_pending_resolution(service, session_id)
        state = service.get(session_id)
        dialogue = state.dialogue
        assert dialogue.waiting_for == "resolution_decision"
        assert dialogue.active_thread_id == thread_id
        opened = dialogue.latest_thread(thread_id)
        assert opened.status == "open"
        assert opened.section_id is not None
        turns = [
            contribution
            for contribution in dialogue.contributions
            if contribution.thread_id == thread_id
        ]
        answers = [turn for turn in turns if turn.kind == "answer"]
        replies = [turn for turn in turns if turn.kind == "reply"]
        assert len(answers) == len(state.perspectives)
        assert replies, "the panel must exchange beyond opening statements"
        for reply in replies:
            assert reply.reply_to is not None
        # a second open is blocked while the decision is pending
        other = next(
            thread
            for thread in dialogue.current_threads()
            if thread.status == "suggested"
        )
        with pytest.raises(SessionError):
            await service.open_dialogue_thread(session_id, thread_id=other.id)

    asyncio.run(go())


def test_researcher_message_gets_reply_and_supersedes_pending() -> None:
    async def go() -> None:
        service, session_id = await _dialogue_panel()
        thread_id = await _to_pending_resolution(service, session_id)
        first_pending = _pending_resolution_id(service, session_id)
        await service.message_dialogue_thread(
            session_id,
            thread_id=thread_id,
            message="Why should that boundary hold?",
        )
        dialogue = service.get(session_id).dialogue
        turns = [
            contribution
            for contribution in dialogue.contributions
            if contribution.thread_id == thread_id
        ]
        challenge = next(turn for turn in turns if turn.author_id == "researcher")
        assert challenge.kind == "challenge"
        reply = next(turn for turn in turns if turn.reply_to == challenge.id)
        assert reply.author_id != "researcher"
        # the earlier pending resolution is superseded, a new one pends
        assert dialogue.latest_resolution(first_pending).status == "rejected"
        latest = _pending_resolution_id(service, session_id)
        assert latest != first_pending
        assert dialogue.waiting_for == "resolution_decision"

    asyncio.run(go())


def test_close_folds_document_reflects_and_suggests_next_threads() -> None:
    async def go() -> None:
        service, session_id = await _dialogue_panel()
        thread_id = await _to_pending_resolution(service, session_id)
        dialogue = service.get(session_id).dialogue
        before_threads = len({t.id for t in dialogue.current_threads()})
        section_id = dialogue.latest_thread(thread_id).section_id
        section_before = next(
            section.text
            for section in dialogue.document.sections
            if section.id == section_id
        )
        resolution_id = _pending_resolution_id(service, session_id)
        await service.decide_dialogue_thread(
            session_id, resolution_id=resolution_id, action="close"
        )
        dialogue = service.get(session_id).dialogue
        closed = dialogue.latest_thread(thread_id)
        assert closed.status == "closed"
        assert closed.resolution_id == resolution_id
        assert dialogue.latest_resolution(resolution_id).status == "accepted"
        assert dialogue.waiting_for is None
        # the resolution was folded into the Thread's section
        section_after = next(
            section.text
            for section in dialogue.document.sections
            if section.id == section_id
        )
        assert section_after != section_before
        assert dialogue.suggestions
        assert dialogue.revisions
        # every participant reflected
        reflected = {
            reflection.perspective_id
            for reflection in dialogue.reflections
            if reflection.thread_id == thread_id
        }
        assert reflected == {state.id for state in dialogue.perspective_states}
        # open questions came back as suggested Threads
        after_threads = len({t.id for t in dialogue.current_threads()})
        assert after_threads > before_threads

    asyncio.run(go())


def test_keep_open_rejects_resolution_and_keeps_thread_open() -> None:
    async def go() -> None:
        service, session_id = await _dialogue_panel()
        thread_id = await _to_pending_resolution(service, session_id)
        resolution_id = _pending_resolution_id(service, session_id)
        await service.decide_dialogue_thread(
            session_id, resolution_id=resolution_id, action="keep_open"
        )
        dialogue = service.get(session_id).dialogue
        assert dialogue.latest_thread(thread_id).status == "open"
        assert dialogue.latest_resolution(resolution_id).status == "rejected"
        assert dialogue.waiting_for is None
        # the discussion can continue and re-pend
        await service.message_dialogue_thread(
            session_id,
            thread_id=thread_id,
            message="Name the strongest counter-evidence.",
        )
        assert service.get(session_id).dialogue.waiting_for == "resolution_decision"

    asyncio.run(go())


def test_edit_close_pins_researcher_text() -> None:
    async def go() -> None:
        service, session_id = await _dialogue_panel()
        await _to_pending_resolution(service, session_id)
        resolution_id = _pending_resolution_id(service, session_id)
        await service.decide_dialogue_thread(
            session_id,
            resolution_id=resolution_id,
            action="edit_close",
            consensus="The panel agrees on the researcher's phrasing.",
        )
        dialogue = service.get(session_id).dialogue
        accepted = dialogue.latest_resolution(resolution_id)
        assert accepted.status == "accepted"
        assert accepted.consensus == "The panel agrees on the researcher's phrasing."

    asyncio.run(go())


def test_report_synthesizes_hypotheses_and_open_questions() -> None:
    async def go() -> None:
        service, session_id = await _dialogue_panel()
        await _to_pending_resolution(service, session_id)
        resolution_id = _pending_resolution_id(service, session_id)
        await service.decide_dialogue_thread(
            session_id, resolution_id=resolution_id, action="close"
        )
        report = service.dialogue_report(session_id)
        assert report.startswith(f"# {PROBLEM}")
        assert "## Hypotheses" in report
        assert "**H1.**" in report
        assert "## Open Questions" in report
        assert "1. " in report

    asyncio.run(go())


def test_final_open_question_can_continue_as_a_new_thread() -> None:
    async def go() -> None:
        service, session_id = await _dialogue_panel()
        await _to_deliberation(service, session_id)

        while True:
            dialogue = service.get(session_id).dialogue
            suggested = [
                thread
                for thread in dialogue.current_threads()
                if thread.status == "suggested"
            ]
            if not suggested:
                break
            await service.open_dialogue_thread(
                session_id,
                thread_id=suggested[0].id,
            )
            await service.decide_dialogue_thread(
                session_id,
                resolution_id=_pending_resolution_id(service, session_id),
                action="close",
            )

        dialogue = service.get(session_id).dialogue
        current = dialogue.current_threads()
        assert current and all(thread.status == "closed" for thread in current)
        continued_origins = {
            origin_id for thread in current for origin_id in thread.origin_ids
        }
        existing_questions = {thread.question.strip().casefold() for thread in current}
        latest = {}
        for resolution in dialogue.resolutions:
            latest[resolution.id] = resolution
        source = next(
            resolution
            for resolution in reversed(list(latest.values()))
            if resolution.status == "accepted"
            and resolution.open_question
            and resolution.id not in continued_origins
            and resolution.open_question.strip().casefold() not in existing_questions
        )

        await service.continue_dialogue_from_resolution(
            session_id,
            resolution_id=source.id,
        )

        dialogue = service.get(session_id).dialogue
        continued = next(
            thread
            for thread in dialogue.current_threads()
            if source.id in thread.origin_ids
        )
        assert continued.status == "suggested"
        assert continued.question == source.open_question
        assert continued.created_by == "researcher"
        assert not any(
            contribution.thread_id == continued.id
            for contribution in dialogue.contributions
        )

    asyncio.run(go())


def test_dialogue_state_survives_snapshot_round_trip() -> None:
    async def go() -> None:
        service, session_id = await _dialogue_panel()
        thread_id = await _to_pending_resolution(service, session_id)
        state = service.get(session_id)
        from agora.focused.models import SessionState, session_snapshot

        restored = SessionState.model_validate(session_snapshot(state))
        assert restored.dialogue is not None
        assert restored.dialogue.latest_thread(thread_id).status == "open"
        assert restored.dialogue.document == state.dialogue.document
        assert restored.dialogue.contributions == state.dialogue.contributions

    asyncio.run(go())
