"""Observable contracts for the baseline four-part draft review."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from agora.focused import agents
from agora.focused import notepad as notepad_module
from agora.focused.models import (
    FACETS,
    ClusterCard,
    ExpPaper,
    FacetEvidence,
    NotepadDoc,
    Perspective,
    Statement,
)
from agora.focused.persistence import FocusedPersistence
from agora.focused.service import FocusedPanelService, SessionError
from agora.focused.study_log import StudyAction, StudyOutcome

PROBLEM = "Should antibiotics be prescribed broadly?"
POSITION = {
    "framing": "Prescribing breadth is an evolutionary-pressure problem.",
    "prior": "Cohorts link broad days to resistance without pricing benefit.",
    "method": "Compare severity-matched cohorts on resistome and time-to-cure.",
    "expected": "Narrower first-line holds outcomes outside sepsis.",
}


def _facet_map(prefix: str, paper_id: str) -> dict[str, FacetEvidence]:
    return {
        facet: FacetEvidence(
            facet=facet,
            text=f"{prefix} {facet} account.",
            paper_id=paper_id,
            sentence_index=0,
            sentence=f"{prefix} {facet} account.",
        )
        for facet in FACETS
    }


def _perspective(index: int) -> Perspective:
    paper_id = f"p{index}"
    return Perspective(
        id=f"persp-{index}",
        name=f"Perspective {index}",
        color="#336699",
        summary=f"Orientation {index}.",
        facets=_facet_map(f"Evidence {index}", paper_id),
        sources=[paper_id],
        anchor_paper_id=paper_id,
        related_paper_count=2,
        cluster_id="cluster-1",
        origin=f"paper:{paper_id}",
    )


def _paper(index: int) -> ExpPaper:
    sentence = f"Evidence {index} supports a bounded antibiotic policy."
    return ExpPaper(
        id=f"p{index}",
        title=f"Paper {index}",
        abstract=sentence,
        abstract_sentences=[sentence],
        specter_v2=[float(index), 1.0],
    )


async def _panel(
    *,
    persistence: FocusedPersistence | None = None,
    participants: int = 3,
) -> tuple[FocusedPanelService, str, str]:
    service = FocusedPanelService(persistence=persistence)
    view = service.create_workspace(
        problem=PROBLEM,
        position=dict(POSITION),
        demo=True,
    )
    session_id = view.active.id
    state = service.get(session_id)
    state.papers = [_paper(index) for index in range(1, participants + 1)]
    state.clusters = [
        ClusterCard(
            id="cluster-1",
            name="Bounded policy",
            blurb="Evidence about antibiotic policy boundaries.",
            facets=list(_facet_map("Cluster", "p1").values()),
            paper_ids=[paper.id for paper in state.papers],
            representative_paper_ids=[paper.id for paper in state.papers],
        )
    ]
    state.perspectives = [_perspective(index) for index in range(1, participants + 1)]
    state.searched = True
    await service.start_notepad(session_id)
    return service, session_id, view.workspace.id


def _notepad(service: FocusedPanelService, session_id: str):
    notepad = service.get(session_id).notepad
    assert notepad is not None
    return notepad


def _version(service: FocusedPanelService, session_id: str):
    version = _notepad(service, session_id).active_version()
    assert version is not None
    return version


def test_v1_is_seeded_and_edits_update_the_current_agenda_subject() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel()
        version = _version(service, session_id)
        assert version.doc == NotepadDoc(**POSITION)
        assert version.agenda.part == "framing"
        assert version.agenda.subject_text == POSITION["framing"]
        await service.edit_notepad_part(
            session_id,
            version_id=version.id,
            part="framing",
            text="A revised evolutionary framing.",
        )
        version = _version(service, session_id)
        assert version.doc.framing == "A revised evolutionary framing."
        assert version.agenda.subject_text == "A revised evolutionary framing."

    asyncio.run(go())


def test_each_click_emits_exactly_the_selected_turns_and_resumes() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel()
        version_id = _version(service, session_id).id
        await service.discuss_notepad(session_id, version_id=version_id, turns=4)
        notepad = _notepad(service, session_id)
        review_turns = [
            turn for turn in notepad.turns if turn.kind in {"feedback", "comparison"}
        ]
        assert len(review_turns) == 4
        assert [turn.kind for turn in review_turns] == [
            "feedback",
            "feedback",
            "feedback",
            "comparison",
        ]
        assert len({turn.author_id for turn in review_turns[:3]}) == 3
        await service.discuss_notepad(session_id, version_id=version_id, turns=2)
        review_turns = [
            turn
            for turn in _notepad(service, session_id).turns
            if turn.kind in {"feedback", "comparison"}
        ]
        assert len(review_turns) == 6
        assert [turn.kind for turn in review_turns[3:]] == [
            "comparison",
            "comparison",
            "comparison",
        ]
        version = _version(service, session_id)
        assert version.agenda.part == "prior"
        assert version.agenda.phase == "feedback"
        assert version.agenda.turn_budget == 2

    asyncio.run(go())


def test_all_independent_feedback_precedes_every_comparison() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel(participants=2)
        version_id = _version(service, session_id).id
        await service.discuss_notepad(session_id, version_id=version_id, turns=4)
        turns = _notepad(service, session_id).turns
        assert [turn.kind for turn in turns] == [
            "feedback",
            "feedback",
            "comparison",
            "comparison",
        ]
        assert {turn.author_id for turn in turns[:2]} == {
            "persp-1",
            "persp-2",
        }
        assert {turn.author_id for turn in turns[2:]} == {
            "persp-1",
            "persp-2",
        }

    asyncio.run(go())


def test_direct_exchange_gets_one_reply_from_every_perspective_then_resumes() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel()
        version = _version(service, session_id)
        await service.discuss_notepad(session_id, version_id=version.id, turns=2)
        before = version.agenda.model_copy(deep=True)
        await service.ask_notepad(
            session_id,
            version_id=version.id,
            message="What boundary should I defend?",
        )
        turns = _notepad(service, session_id).turns
        assert [turn.kind for turn in turns[-4:]] == [
            "researcher",
            "direct_reply",
            "direct_reply",
            "direct_reply",
        ]
        assert len({turn.author_id for turn in turns[-3:]}) == 3
        after = _version(service, session_id).agenda
        assert after.part == before.part
        assert after.phase == before.phase
        assert after.feedback_done_ids == before.feedback_done_ids
        await service.discuss_notepad(session_id, version_id=version.id, turns=1)
        assert _notepad(service, session_id).turns[-1].kind == "feedback"

    asyncio.run(go())


def test_newcomer_joins_the_current_element_before_comparison_resumes() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel()
        version_id = _version(service, session_id).id
        await service.discuss_notepad(session_id, version_id=version_id, turns=4)
        state = service.get(session_id)
        state.papers.append(_paper(4))
        state.clusters[0].paper_ids.append("p4")
        state.perspectives.append(_perspective(4))
        assert state.notepad is not None
        state.notepad.in_chat.append("persp-4")
        await service.discuss_notepad(session_id, version_id=version_id, turns=1)
        latest = _notepad(service, session_id).turns[-1]
        assert latest.kind == "feedback"
        assert latest.author_id == "persp-4"
        agenda = _version(service, session_id).agenda
        assert agenda.part == "framing"
        assert agenda.phase == "comparison"
        assert agenda.comparison_done_ids == []

    asyncio.run(go())


def test_removing_a_perspective_prunes_the_roster_and_pending_agenda() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel()
        version_id = _version(service, session_id).id
        await service.discuss_notepad(session_id, version_id=version_id, turns=1)
        await service.remove_perspective(session_id, "persp-3")
        await service.discuss_notepad(session_id, version_id=version_id, turns=1)
        notepad = _notepad(service, session_id)
        assert "persp-3" not in notepad.in_chat
        assert "persp-3" not in _version(service, session_id).agenda.participant_ids
        assert all(turn.author_id != "persp-3" for turn in notepad.turns)

    asyncio.run(go())


def test_versions_keep_independent_agendas_histories_and_turn_budgets() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel(participants=2)
        v1 = _version(service, session_id)
        await service.discuss_notepad(session_id, version_id=v1.id, turns=3)
        await service.add_notepad_version(session_id, copy_current=True)
        v2 = _version(service, session_id)
        await service.discuss_notepad(session_id, version_id=v2.id, turns=1)
        notepad = _notepad(service, session_id)
        assert len([turn for turn in notepad.turns if turn.version_id == v1.id]) == 3
        assert len([turn for turn in notepad.turns if turn.version_id == v2.id]) == 1
        assert v1.agenda.turn_budget == 3
        assert v2.agenda.turn_budget == 1
        assert v1.agenda.phase == "comparison"
        assert v2.agenda.phase == "feedback"

    asyncio.run(go())


def test_review_stops_at_completion_and_requires_an_explicit_restart() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel(participants=1)
        version_id = _version(service, session_id).id
        for _ in range(4):
            await service.discuss_notepad(session_id, version_id=version_id, turns=2)
        agenda = _version(service, session_id).agenda
        assert agenda.phase == "complete"
        assert agenda.completed_at is not None
        with pytest.raises(SessionError, match="complete"):
            await service.discuss_notepad(
                session_id,
                version_id=version_id,
                turns=1,
            )
        await service.restart_notepad_review(session_id, version_id=version_id)
        agenda = _version(service, session_id).agenda
        assert agenda.review_n == 2
        assert agenda.part == "framing"
        assert agenda.phase == "feedback"

    asyncio.run(go())


def test_too_large_final_budget_is_rejected_without_partial_turns() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel()
        version_id = _version(service, session_id).id
        for turns in (8, 8, 7):
            await service.discuss_notepad(
                session_id,
                version_id=version_id,
                turns=turns,
            )
        before = len(_notepad(service, session_id).turns)
        with pytest.raises(SessionError, match="Only 1 review turn remains"):
            await service.discuss_notepad(
                session_id,
                version_id=version_id,
                turns=2,
            )
        assert len(_notepad(service, session_id).turns) == before
        await service.discuss_notepad(session_id, version_id=version_id, turns=1)
        assert _version(service, session_id).agenda.phase == "complete"

    asyncio.run(go())


def test_provider_failure_rolls_back_every_turn_from_the_click(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, _ = await _panel()
        version_id = _version(service, session_id).id
        original = agents.review_draft_element
        calls = 0

        async def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("provider failed")
            return await original(*args, **kwargs)

        monkeypatch.setattr(agents, "review_draft_element", fail_second)
        with pytest.raises(RuntimeError, match="provider failed"):
            await service.discuss_notepad(
                session_id,
                version_id=version_id,
                turns=2,
            )
        notepad = _notepad(service, session_id)
        assert notepad.turns == []
        assert _version(service, session_id).agenda.feedback_done_ids == []

    asyncio.run(go())


def test_summary_is_clipboard_content_and_never_mutates_the_draft() -> None:
    async def go() -> None:
        service, session_id, workspace_id = await _panel()
        version = _version(service, session_id)
        before = version.doc.model_copy(deep=True)
        await service.discuss_notepad(session_id, version_id=version.id, turns=2)
        await service.summarize_notepad(session_id, version_id=version.id)
        notepad = _notepad(service, session_id)
        assert notepad.turns[-1].kind == "summary"
        assert _version(service, session_id).doc == before
        public = service.workspace_view(workspace_id).active
        assert public.notepad is not None
        assert public.notepad.turns[-1].citations == []

    asyncio.run(go())


def test_clear_is_version_scoped_and_preserves_document_and_progress() -> None:
    async def go() -> None:
        service, session_id, workspace_id = await _panel()
        version = _version(service, session_id)
        await service.discuss_notepad(session_id, version_id=version.id, turns=2)
        before_doc = version.doc.model_copy(deep=True)
        before_agenda = version.agenda.model_copy(deep=True)
        await service.clear_notepad_chat(session_id)
        version = _version(service, session_id)
        assert version.visible_turn_start == 2
        assert version.doc == before_doc
        assert version.agenda == before_agenda
        assert _notepad(service, session_id).turns[-1].kind == "system"
        assert len(_notepad(service, session_id).turns) == 3
        public = service.workspace_view(workspace_id).active.notepad
        assert public is not None
        assert [turn.kind for turn in public.turns] == ["system"]
        assert all(item.visible_turn_start == 0 for item in public.versions)

    asyncio.run(go())


def test_finish_snapshots_every_version_and_makes_the_study_read_only() -> None:
    async def go() -> None:
        service, session_id, workspace_id = await _panel()
        await service.add_notepad_version(session_id, copy_current=False)
        active_id = _version(service, session_id).id
        await service.edit_notepad_part(
            session_id,
            version_id=active_id,
            part="method",
            text="Alternative method.",
        )
        await service.finish_notepad_study(session_id)
        notepad = _notepad(service, session_id)
        assert notepad.final_snapshot is not None
        assert [version.name for version in notepad.final_snapshot.versions] == [
            "v1",
            "v2",
        ]
        assert notepad.final_snapshot.versions[1].doc.method == "Alternative method."
        with pytest.raises(SessionError, match="read-only"):
            await service.edit_notepad_part(
                session_id,
                version_id=active_id,
                part="method",
                text="Late change.",
            )
        with pytest.raises(SessionError, match="read-only"):
            await service.remove_perspective(session_id, "persp-1")
        revision = service.workspace_view(workspace_id).workspace.revision
        await service.finish_notepad_study(session_id)
        assert service.workspace_view(workspace_id).workspace.revision == revision
        assert _notepad(service, session_id).final_snapshot == notepad.final_snapshot

    asyncio.run(go())


def test_finished_versions_survive_a_cold_reload() -> None:
    async def go() -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        persistence = FocusedPersistence(connection)
        service, session_id, workspace_id = await _panel(persistence=persistence)
        await service.finish_notepad_study(session_id)
        reloaded = FocusedPanelService(persistence=persistence)
        state = reloaded.workspace_view(workspace_id).active
        assert state.notepad is not None
        assert state.notepad.final_snapshot is not None
        assert state.notepad.final_snapshot.versions[0].doc == NotepadDoc(**POSITION)

    asyncio.run(go())


def test_removing_every_perspective_stops_without_marking_review_complete() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel(participants=1)
        version_id = _version(service, session_id).id
        await service.remove_perspective(session_id, "persp-1")
        with pytest.raises(SessionError, match="No Perspectives are available"):
            await service.discuss_notepad(
                session_id,
                version_id=version_id,
                turns=1,
            )
        assert _version(service, session_id).agenda.phase == "feedback"
        assert _notepad(service, session_id).turns == []

    asyncio.run(go())


def test_deleting_another_version_does_not_shift_the_clear_boundary() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel(participants=1)
        v1 = _version(service, session_id)
        await service.discuss_notepad(session_id, version_id=v1.id, turns=2)
        await service.add_notepad_version(session_id, copy_current=True)
        v2 = _version(service, session_id)
        await service.discuss_notepad(session_id, version_id=v2.id, turns=2)
        await service.clear_notepad_chat(session_id)
        await service.delete_notepad_version(session_id, version_id=v1.id)
        await service.discuss_notepad(session_id, version_id=v2.id, turns=1)
        notepad = _notepad(service, session_id)
        version_turns = [turn for turn in notepad.turns if turn.version_id == v2.id]
        visible = version_turns[v2.visible_turn_start :]
        assert [turn.kind for turn in visible] == ["system", "feedback"]

    asyncio.run(go())


def test_blank_direct_message_is_rejected_before_agent_work(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, _ = await _panel(participants=1)
        version_id = _version(service, session_id).id

        async def should_not_run(*args, **kwargs):
            raise AssertionError("blank message reached an agent")

        monkeypatch.setattr(agents, "reply_to_user", should_not_run)
        with pytest.raises(SessionError, match="message requires text"):
            await service.ask_notepad(
                session_id,
                version_id=version_id,
                message="   ",
            )
        assert _notepad(service, session_id).turns == []

    asyncio.run(go())


def test_roster_removal_advances_an_already_satisfied_comparison() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel(participants=2)
        version_id = _version(service, session_id).id
        await service.discuss_notepad(
            session_id,
            version_id=version_id,
            turns=3,
        )
        assert _version(service, session_id).agenda.phase == "comparison"
        await service.remove_perspective(session_id, "persp-2")
        agenda = _version(service, session_id).agenda
        assert agenda.part == "prior"
        assert agenda.phase == "feedback"
        await service.discuss_notepad(
            session_id,
            version_id=version_id,
            turns=1,
        )
        latest = _notepad(service, session_id).turns[-1]
        assert latest.kind == "feedback"
        assert latest.part == "prior"

    asyncio.run(go())


def test_comparison_uses_feedback_from_current_perspectives_only() -> None:
    async def go() -> None:
        service, session_id, _ = await _panel(participants=2)
        version_id = _version(service, session_id).id
        await service.discuss_notepad(
            session_id,
            version_id=version_id,
            turns=2,
        )
        await service.remove_perspective(session_id, "persp-2")
        plan = notepad_module.plan_review_turn(
            service.get(session_id),
            version_id=version_id,
            turns=1,
        )
        assert plan.phase == "comparison"
        assert plan.speaker.id == "persp-1"
        assert [turn.author_id for turn in plan.feedback] == ["persp-1"]

    asyncio.run(go())


def test_finished_summary_is_rejected_before_agent_work(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, _ = await _panel(participants=1)
        version_id = _version(service, session_id).id
        await service.discuss_notepad(
            session_id,
            version_id=version_id,
            turns=2,
        )
        await service.finish_notepad_study(session_id)

        async def should_not_run(*args, **kwargs):
            raise AssertionError("finished summary reached an agent")

        monkeypatch.setattr(agents, "summarize_notepad_turns", should_not_run)
        with pytest.raises(SessionError, match="read-only") as caught:
            await service.summarize_notepad(
                session_id,
                version_id=version_id,
            )
        assert caught.value.status == 409

    asyncio.run(go())


def test_feedback_text_never_exposes_internal_paper_ids(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, workspace_id = await _panel(participants=1)
        version_id = _version(service, session_id).id

        async def cited_feedback(*args, **kwargs):
            return Statement(
                text="Evidence [p1] and p1 supports the boundary.",
                citations=["p1"],
            )

        monkeypatch.setattr(agents, "review_draft_element", cited_feedback)
        await service.discuss_notepad(
            session_id,
            version_id=version_id,
            turns=1,
        )
        private_turn = _notepad(service, session_id).turns[-1]
        assert "p1" not in private_turn.text
        assert private_turn.citations == ["p1"]
        public = service.workspace_view(workspace_id).active.notepad
        assert public is not None
        assert "p1" not in public.turns[-1].text
        assert public.turns[-1].citations == []

    asyncio.run(go())


def test_topic_exchange_preserves_draft_agenda_and_survives_reload() -> None:
    async def go() -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        persistence = FocusedPersistence(connection)
        service, session_id, workspace_id = await _panel(persistence=persistence)
        await service.generate_notepad_topics(session_id)
        topics = _notepad(service, session_id).topics
        assert {topic.perspective_id for topic in topics} == {
            "persp-1",
            "persp-2",
            "persp-3",
        }
        before_generation = service.workspace_view(workspace_id)
        await service.generate_notepad_topics(session_id)
        assert service.workspace_view(workspace_id) == before_generation

        version = _version(service, session_id)
        await service.discuss_notepad(session_id, version_id=version.id, turns=1)
        agenda = version.agenda.model_copy(deep=True)
        doc = version.doc.model_copy(deep=True)
        topic = topics[0]
        await service.ask_notepad(
            session_id,
            version_id=version.id,
            message=topic.question,
            topic_id=topic.id,
        )
        exchange = _notepad(service, session_id).turns[-4:]
        assert exchange[0].text == topic.question
        assert {turn.author_id for turn in exchange[1:]} == {
            "persp-1",
            "persp-2",
            "persp-3",
        }
        assert all(turn.topic_id == topic.id for turn in exchange)
        assert all(turn.reply_to_turn_id == exchange[0].id for turn in exchange[1:])
        assert version.doc == doc
        assert version.agenda.model_dump(exclude={"turns_emitted"}) == (
            agenda.model_dump(exclude={"turns_emitted"})
        )

        await service.add_notepad_version(session_id, copy_current=True)
        await service.clear_notepad_chat(session_id)
        await service.finish_notepad_study(session_id)
        reloaded = FocusedPanelService(persistence=persistence)
        restored = _notepad(reloaded, session_id)
        assert restored.topics == topics
        assert [
            turn for turn in restored.turns if turn.topic_id == topic.id
        ] == exchange
        assert restored.final_snapshot is not None
        assert restored.final_snapshot.versions[0].doc == doc
        with pytest.raises(SessionError, match="read-only"):
            await reloaded.generate_notepad_topics(session_id)

    asyncio.run(go())


def test_topic_from_another_study_is_rejected_before_agent_work(monkeypatch) -> None:
    async def go() -> None:
        service, session_id, workspace_id = await _panel()
        other_service, other_session_id, _ = await _panel()
        await other_service.generate_notepad_topics(other_session_id)
        foreign_topic = _notepad(other_service, other_session_id).topics[0]
        before = service.workspace_view(workspace_id)

        async def should_not_run(*args, **kwargs):
            raise AssertionError("an unknown topic reached an agent")

        monkeypatch.setattr(agents, "reply_to_user", should_not_run)
        with pytest.raises(SessionError, match="Unknown discussion topic") as error:
            await service.ask_notepad(
                session_id,
                version_id=_version(service, session_id).id,
                message=foreign_topic.question,
                topic_id=foreign_topic.id,
            )
        assert error.value.status == 404
        assert service.workspace_view(workspace_id) == before

    asyncio.run(go())


def test_failed_topic_generation_is_retryable_without_resetting_chat(
    monkeypatch,
) -> None:
    async def go() -> None:
        service, session_id, workspace_id = await _panel()
        await service.discuss_notepad(
            session_id, version_id=_version(service, session_id).id, turns=1
        )
        before = service.workspace_view(workspace_id)

        async def unavailable(**kwargs):
            raise agents.FocusedAgentError("model unavailable")

        with monkeypatch.context() as patch:
            patch.setattr(agents, "generate_discussion_topics", unavailable)
            with pytest.raises(agents.FocusedAgentError):
                await service.generate_notepad_topics(session_id)
        assert service.workspace_view(workspace_id) == before
        await service.generate_notepad_topics(session_id)
        after = service.workspace_view(workspace_id)
        assert after.active.notepad.turns == before.active.notepad.turns
        assert (
            _version(service, session_id).doc == before.active.notepad.versions[0].doc
        )

    asyncio.run(go())


def test_topic_actions_keep_research_content_out_of_study_logs(monkeypatch) -> None:
    async def go() -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        persistence = FocusedPersistence(connection)
        try:
            service, session_id, _ = await _panel(persistence=persistence)

            async def unavailable(**kwargs):
                raise agents.FocusedAgentError("PRIVATE MODEL ERROR")

            with monkeypatch.context() as patch:
                patch.setattr(agents, "generate_discussion_topics", unavailable)
                with pytest.raises(agents.FocusedAgentError):
                    await service.generate_notepad_topics(session_id)
            await service.generate_notepad_topics(session_id)
            topic = _notepad(service, session_id).topics[0]
            version_id = _version(service, session_id).id
            message = "PRIVATE RESEARCHER QUESTION"
            await service.ask_notepad(
                session_id,
                version_id=version_id,
                message=message,
                topic_id=topic.id,
            )
            with pytest.raises(SessionError, match="Unknown discussion topic"):
                await service.ask_notepad(
                    session_id,
                    version_id=version_id,
                    message=message,
                    topic_id="PRIVATE INVALID TOPIC ID",
                )
            events = [
                event
                for event in persistence.load_study_events()
                if event.action
                in {StudyAction.TOPICS_GENERATE, StudyAction.QUESTION_SEND}
            ]
            assert [(event.action, event.outcome) for event in events] == [
                (StudyAction.TOPICS_GENERATE, StudyOutcome.FAILURE),
                (StudyAction.TOPICS_GENERATE, StudyOutcome.SUCCESS),
                (StudyAction.QUESTION_SEND, StudyOutcome.SUCCESS),
                (StudyAction.QUESTION_SEND, StudyOutcome.FAILURE),
            ]
            assert events[0].error_code == "model_failure"
            assert events[0].revision_before == events[0].revision_after
            assert events[2].details == {
                "message_characters": len(message),
                "topic_id": topic.id,
            }
            assert events[2].object_id == version_id
            assert "topic_id" not in events[3].details
            assert all("PRIVATE" not in event.model_dump_json() for event in events)
            assert all(
                topic.question not in event.model_dump_json() for event in events
            )
        finally:
            connection.close()

    asyncio.run(go())
