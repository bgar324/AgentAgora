"""The group-chat stage over a four-part notepad.

These tests pin the study's manipulation: the two arms must differ in
exactly one thing (perspective guidance), never in step count or in
whether the researcher is asked.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from agora.focused.models import (
    FACETS,
    ExpPaper,
    Facet,
    FacetEvidence,
    NotepadDoc,
    Perspective,
)
from agora.focused.persistence import FocusedPersistence
from agora.focused.service import FocusedPanelService

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


def _perspective(name: str, prefix: str, paper_id: str) -> Perspective:
    return Perspective(
        id=name.lower(),
        name=name,
        color="#336699",
        summary=f"{prefix} reads the problem one way. A second sentence follows.",
        facets=_facet_map(prefix, paper_id),
        sources=[paper_id],
    )


async def _panel(arm: str) -> tuple[FocusedPanelService, str]:
    service = FocusedPanelService()
    view = service.create_workspace(
        problem=PROBLEM,
        research_questions=[],
        position=dict(POSITION),
        arm=arm,
        demo=True,
    )
    session_id = view.active.id
    state = service.get(session_id)
    state.papers = [
        ExpPaper(
            id=f"p{index}",
            title=f"Paper {index}",
            abstract="Shared evidence.",
            abstract_sentences=["Shared evidence."],
        )
        for index in (1, 2, 3)
    ]
    state.perspectives = [
        _perspective("First", "Alpha", "p1"),
        _perspective("Second", "Beta", "p2"),
        _perspective("Third", "Gamma", "p3"),
    ]
    state.searched = True
    await service.start_notepad(session_id)
    return service, session_id


def _active_doc(service: FocusedPanelService, session_id: str) -> NotepadDoc:
    notepad = service.get(session_id).notepad
    assert notepad is not None
    version = notepad.active_version()
    assert version is not None
    return version.doc


def test_notepad_v1_is_seeded_from_the_input_screen() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        doc = _active_doc(service, session_id)
        assert doc.framing == POSITION["framing"]
        assert doc.expected == POSITION["expected"]
        notepad = service.get(session_id).notepad
        assert notepad is not None
        assert [version.name for version in notepad.versions] == ["v1"]
        # Everyone with a Perspective starts in the chat.
        assert len(notepad.in_chat) == 3

    asyncio.run(go())


def test_researcher_edits_take_effect_without_a_save_step() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        await service.edit_notepad_part(session_id, part="method", text="Rewritten.")
        assert _active_doc(service, session_id).method == "Rewritten."

    asyncio.run(go())


def test_versions_are_independent_and_the_first_is_never_mutated() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        await service.add_notepad_version(session_id, copy_current=True)
        await service.edit_notepad_part(session_id, part="framing", text="v2 wording.")
        notepad = service.get(session_id).notepad
        assert notepad is not None
        assert [version.name for version in notepad.versions] == ["v1", "v2"]
        assert notepad.versions[0].doc.framing == POSITION["framing"]
        assert notepad.versions[1].doc.framing == "v2 wording."
        # Switching back exposes the original wording again.
        await service.switch_notepad_version(
            session_id, version_id=notepad.versions[0].id
        )
        assert _active_doc(service, session_id).framing == POSITION["framing"]

    asyncio.run(go())


def test_the_last_version_cannot_be_deleted() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        notepad = service.get(session_id).notepad
        assert notepad is not None
        with pytest.raises(Exception, match="last version cannot be deleted"):
            await service.delete_notepad_version(
                session_id, version_id=notepad.versions[0].id
            )

    asyncio.run(go())


def test_guided_turns_cite_evidence_and_quote_the_researchers_wording() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        await service.discuss_notepad(session_id, turns=3)
        notepad = service.get(session_id).notepad
        assert notepad is not None
        spoken = [turn for turn in notepad.turns if turn.role == "perspective"]
        assert len(spoken) == 3
        # Every guided turn is grounded in its own cluster's paper.
        assert all(turn.citations for turn in spoken)
        # And at least one names the researcher's own wording back to them,
        # quoted rather than spliced into a clause.
        assert any('"' in turn.text for turn in spoken)

    asyncio.run(go())


def test_baseline_turns_are_ungrounded_and_grammatical() -> None:
    async def go() -> None:
        service, session_id = await _panel("baseline")
        await service.discuss_notepad(session_id, turns=3)
        notepad = service.get(session_id).notepad
        assert notepad is not None
        spoken = [turn for turn in notepad.turns if turn.role == "perspective"]
        assert len(spoken) == 3
        assert all(not turn.citations for turn in spoken)
        # A persona blurb runs several sentences; splicing it into a frame
        # produced "…resistance genes is what matters here."
        assert all(
            ". That is what I am weighing here." not in turn.text[:1] for turn in spoken
        )
        for turn in spoken:
            assert not turn.text.endswith("is what matters here.")

    asyncio.run(go())


def test_a_speaker_taking_a_second_turn_answers_instead_of_repeating() -> None:
    async def go() -> None:
        for arm in ("guided", "baseline"):
            service, session_id = await _panel(arm)
            await service.discuss_notepad(session_id, turns=8)
            notepad = service.get(session_id).notepad
            assert notepad is not None
            spoken = [turn.text for turn in notepad.turns if turn.role == "perspective"]
            assert len(spoken) == 8
            assert len(set(spoken)) == 8, f"{arm} repeated a turn verbatim"

    asyncio.run(go())


def test_neither_arm_writes_the_notepad_without_a_researcher_decision() -> None:
    async def go() -> None:
        for arm in ("guided", "baseline"):
            service, session_id = await _panel(arm)
            await service.discuss_notepad(session_id, turns=4)
            await service.summarize_notepad(session_id, part="prior")
            notepad = service.get(session_id).notepad
            assert notepad is not None
            pending = notepad.pending_proposals()
            # Same seam, same count, in both arms.
            assert len(pending) == 1, arm
            assert _active_doc(service, session_id).prior == POSITION["prior"], arm

            await service.decide_notepad_proposal(
                session_id, proposal_id=pending[0].id, action="approve"
            )
            assert _active_doc(service, session_id).prior != POSITION["prior"], arm

    asyncio.run(go())


def test_only_the_guided_seam_carries_a_reason_and_its_evidence() -> None:
    async def go() -> None:
        guided, guided_id = await _panel("guided")
        await guided.discuss_notepad(guided_id, turns=4)
        await guided.summarize_notepad(guided_id, part="prior")
        guided_notepad = guided.get(guided_id).notepad
        assert guided_notepad is not None
        proposal = guided_notepad.pending_proposals()[0]
        assert proposal.reason
        assert proposal.citations

        baseline, baseline_id = await _panel("baseline")
        await baseline.discuss_notepad(baseline_id, turns=4)
        await baseline.summarize_notepad(baseline_id, part="prior")
        baseline_notepad = baseline.get(baseline_id).notepad
        assert baseline_notepad is not None
        bare = baseline_notepad.pending_proposals()[0]
        assert not bare.reason
        assert not bare.citations

    asyncio.run(go())


def test_approving_after_your_own_edit_keeps_both() -> None:
    """The notepad is editable while a proposal is pending.

    Writing the proposal's frozen text here would silently restore the
    wording it was raised against, discarding the researcher's edit.
    """

    async def go() -> None:
        for arm in ("guided", "baseline"):
            service, session_id = await _panel(arm)
            await service.discuss_notepad(session_id, turns=4)
            await service.summarize_notepad(session_id, part="prior")
            notepad = service.get(session_id).notepad
            assert notepad is not None
            proposal_id = notepad.pending_proposals()[0].id

            edit = f"{POSITION['prior']} And my own qualification."
            await service.edit_notepad_part(session_id, part="prior", text=edit)
            await service.decide_notepad_proposal(
                session_id, proposal_id=proposal_id, action="approve"
            )

            final = _active_doc(service, session_id).prior
            assert "And my own qualification." in final, arm
            assert "The discussion so far" in final, arm
            # The stale prefix is not pasted back in a second time.
            assert final.count(POSITION["prior"]) == 1, arm
            notepad = service.get(session_id).notepad
            assert notepad is not None
            assert any(
                "folded into your newer wording" in turn.text
                for turn in notepad.turns
                if turn.role == "system"
            ), arm

    asyncio.run(go())


def test_approving_without_an_edit_appends_as_proposed() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        await service.discuss_notepad(session_id, turns=4)
        await service.summarize_notepad(session_id, part="prior")
        notepad = service.get(session_id).notepad
        assert notepad is not None
        await service.decide_notepad_proposal(
            session_id,
            proposal_id=notepad.pending_proposals()[0].id,
            action="approve",
        )
        final = _active_doc(service, session_id).prior
        assert final.startswith(POSITION["prior"])
        assert "The discussion so far" in final
        notepad = service.get(session_id).notepad
        assert notepad is not None
        assert any(
            "as proposed" in turn.text
            for turn in notepad.turns
            if turn.role == "system"
        )

    asyncio.run(go())


def test_switching_versions_leaves_a_pending_proposal_decidable() -> None:
    """A proposal names its version, so a fork cannot orphan it."""

    async def go() -> None:
        service, session_id = await _panel("guided")
        await service.discuss_notepad(session_id, turns=4)
        await service.summarize_notepad(session_id, part="expected")
        notepad = service.get(session_id).notepad
        assert notepad is not None
        proposal = notepad.pending_proposals()[0]
        v1_id = proposal.version_id

        await service.add_notepad_version(session_id, copy_current=True)
        await service.decide_notepad_proposal(
            session_id, proposal_id=proposal.id, action="approve"
        )

        notepad = service.get(session_id).notepad
        assert notepad is not None
        v1 = next(item for item in notepad.versions if item.id == v1_id)
        v2 = next(item for item in notepad.versions if item.id != v1_id)
        # The decision lands on the version it was raised against, not on
        # whichever version happens to be open.
        assert "The discussion so far" in v1.doc.expected
        assert v2.doc.expected == POSITION["expected"]

    asyncio.run(go())


def test_editing_a_proposal_lands_the_researchers_wording_verbatim() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        await service.discuss_notepad(session_id, turns=4)
        await service.summarize_notepad(session_id, part="expected")
        notepad = service.get(session_id).notepad
        assert notepad is not None
        proposal = notepad.pending_proposals()[0]
        await service.decide_notepad_proposal(
            session_id,
            proposal_id=proposal.id,
            action="edit",
            text="Only my wording survives.",
        )
        assert _active_doc(service, session_id).expected == "Only my wording survives."
        notepad = service.get(session_id).notepad
        assert notepad is not None
        assert notepad.proposals[0].status == "edited"

    asyncio.run(go())


def test_rejecting_a_proposal_leaves_the_notepad_and_records_the_reason() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        await service.discuss_notepad(session_id, turns=4)
        await service.summarize_notepad(session_id, part="framing")
        notepad = service.get(session_id).notepad
        assert notepad is not None
        proposal = notepad.pending_proposals()[0]
        await service.decide_notepad_proposal(
            session_id,
            proposal_id=proposal.id,
            action="reject",
            reason="Wrong endpoint.",
        )
        assert _active_doc(service, session_id).framing == POSITION["framing"]
        notepad = service.get(session_id).notepad
        assert notepad is not None
        rejected = notepad.proposals[0]
        assert rejected.status == "rejected"
        assert rejected.decision_reason == "Wrong endpoint."
        # The panel reads the rejection back.
        assert any(
            "Wrong endpoint." in turn.text
            for turn in notepad.turns
            if turn.role in {"researcher", "system"}
        )

    asyncio.run(go())


def test_a_proposal_is_decided_once() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        await service.discuss_notepad(session_id, turns=4)
        await service.summarize_notepad(session_id, part="prior")
        notepad = service.get(session_id).notepad
        assert notepad is not None
        proposal_id = notepad.pending_proposals()[0].id
        await service.decide_notepad_proposal(
            session_id, proposal_id=proposal_id, action="approve"
        )
        with pytest.raises(Exception, match="already"):
            await service.decide_notepad_proposal(
                session_id, proposal_id=proposal_id, action="reject"
            )

    asyncio.run(go())


def test_removing_every_participant_stops_the_discussion() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        for perspective in service.get(session_id).perspectives:
            await service.set_notepad_participant(
                session_id, perspective_id=perspective.id, participating=False
            )
        notepad = service.get(session_id).notepad
        assert notepad is not None
        assert notepad.in_chat == []
        with pytest.raises(Exception, match="Nobody is in the chat"):
            await service.discuss_notepad(session_id, turns=2)

    asyncio.run(go())


def test_clearing_the_chat_leaves_the_notepad_alone() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        await service.discuss_notepad(session_id, turns=4)
        await service.summarize_notepad(session_id, part="prior")
        notepad = service.get(session_id).notepad
        assert notepad is not None
        proposal_id = notepad.pending_proposals()[0].id
        await service.decide_notepad_proposal(
            session_id, proposal_id=proposal_id, action="approve"
        )
        written = _active_doc(service, session_id).prior

        await service.clear_notepad_chat(session_id)
        notepad = service.get(session_id).notepad
        assert notepad is not None
        assert [turn.role for turn in notepad.turns] == ["system"]
        assert _active_doc(service, session_id).prior == written

    asyncio.run(go())


def test_asking_the_panel_gets_one_answer_from_a_participant() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        await service.ask_notepad(session_id, message="Which endpoint decides this?")
        notepad = service.get(session_id).notepad
        assert notepad is not None
        roles = [turn.role for turn in notepad.turns]
        assert roles == ["researcher", "perspective"]
        assert notepad.turns[0].text == "Which endpoint decides this?"

    asyncio.run(go())


def test_a_turn_budget_is_bounded() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        with pytest.raises(Exception, match="between 1 and"):
            await service.discuss_notepad(session_id, turns=99)

    asyncio.run(go())


def test_summarizing_before_a_discussion_is_refused() -> None:
    async def go() -> None:
        service, session_id = await _panel("guided")
        with pytest.raises(Exception, match="summarize"):
            await service.summarize_notepad(session_id, part="prior")

    asyncio.run(go())


@pytest.mark.parametrize("facet", list(FACETS))
def test_every_facet_has_display_evidence(facet: Facet) -> None:
    # The Perspective column shows a facet sentence per card; a missing
    # facet would render an empty card.
    evidence = _facet_map("Alpha", "p1")[facet]
    assert evidence.text
    assert evidence.paper_id == "p1"


def test_the_notepad_survives_a_cold_reload(tmp_path) -> None:
    """A study session outlives the process that created it."""

    def store() -> FocusedPersistence:
        connection = sqlite3.connect(tmp_path / "focused.db", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return FocusedPersistence(connection)

    async def go() -> None:
        service = FocusedPanelService(persistence=store())
        view = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            position=dict(POSITION),
            arm="guided",
            demo=True,
        )
        session_id = view.active.id
        workspace_id = view.workspace.id
        state = service.get(session_id)
        state.papers = [
            ExpPaper(
                id=f"p{index}",
                title=f"Paper {index}",
                abstract="Shared evidence.",
                abstract_sentences=["Shared evidence."],
            )
            for index in (1, 2, 3)
        ]
        state.perspectives = [
            _perspective("First", "Alpha", "p1"),
            _perspective("Second", "Beta", "p2"),
            _perspective("Third", "Gamma", "p3"),
        ]
        state.searched = True
        await service.start_notepad(session_id)
        await service.discuss_notepad(session_id, turns=4)
        await service.summarize_notepad(session_id, part="prior")
        notepad = service.get(session_id).notepad
        assert notepad is not None
        await service.decide_notepad_proposal(
            session_id,
            proposal_id=notepad.pending_proposals()[0].id,
            action="edit",
            text="Researcher wording only.",
        )
        await service.add_notepad_version(session_id, copy_current=True)
        await service.edit_notepad_part(session_id, part="framing", text="v2 framing.")

        restored = FocusedPanelService(persistence=store()).workspace_view(workspace_id)
        assert restored.active.arm == "guided"
        assert restored.active.position.framing == POSITION["framing"]
        reloaded = restored.active.notepad
        assert reloaded is not None
        assert [version.name for version in reloaded.versions] == ["v1", "v2"]
        active = reloaded.active_version()
        assert active is not None and active.name == "v2"
        assert reloaded.versions[0].doc.framing == POSITION["framing"]
        assert reloaded.versions[0].doc.prior == "Researcher wording only."
        assert reloaded.versions[1].doc.framing == "v2 framing."
        assert [item.status for item in reloaded.proposals] == ["edited"]
        assert any(turn.citations for turn in reloaded.turns)
        assert len(reloaded.in_chat) == 3
        assert reloaded.turn_cursor == 4

    asyncio.run(go())
