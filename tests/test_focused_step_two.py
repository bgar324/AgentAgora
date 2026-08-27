"""Step 2 of Youngseung's baseline: find papers, author the Perspective.

Two things his spec asks for that the product did not do: queries drawn
from the researcher's four-part position as well as the problem, and a
Perspective the researcher authors rather than accepts.
"""

from __future__ import annotations

import asyncio

import pytest

from agora.focused import agents
from agora.focused.models import (
    FACETS,
    ClusterCard,
    ExpPaper,
    FacetEvidence,
    NotepadDoc,
)
from agora.focused.service import FocusedPanelService

PROBLEM = "Should antibiotics be prescribed broadly?"
POSITION = {
    "framing": "Prescribing breadth is an evolutionary-pressure problem.",
    "prior": "Cohorts link broad days to resistance without pricing benefit.",
    "method": "Compare severity-matched cohorts on resistome carriage.",
    "expected": "Narrower first-line holds outcomes outside sepsis.",
}


def test_the_position_block_names_every_part_the_researcher_wrote() -> None:
    block = agents._position_block(NotepadDoc(**POSITION))
    for label in ("Framing", "Previous work", "Methodology", "Expected results"):
        assert f"### {label}" in block
    assert POSITION["method"] in block


def test_an_unwritten_position_adds_nothing_to_the_prompt() -> None:
    # A blank position must not append an empty heading block: the prompt
    # would then describe a position the researcher never took.
    assert agents._position_block(NotepadDoc()) == ""
    assert agents._position_block(None) == ""


def test_a_partly_written_position_only_names_the_parts_that_exist() -> None:
    block = agents._position_block(NotepadDoc(framing="Only this one."))
    assert "### Framing" in block
    assert "Methodology" not in block


def test_query_suggestion_sees_the_four_parts(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def capture(provider, system, user, schema, **kwargs):
        captured["user"] = user

    monkeypatch.setattr(agents, "_structured", capture)

    async def go() -> None:
        await agents.suggest_queries(
            PROBLEM,
            ["Does breadth raise resistance?"],
            position=NotepadDoc(**POSITION),
        )

    asyncio.run(go())
    assert "## RESEARCHER POSITION" in captured["user"]
    assert POSITION["expected"] in captured["user"]
    # The problem and questions are still there; the parts are additive.
    assert PROBLEM in captured["user"]
    assert "Does breadth raise resistance?" in captured["user"]


def test_question_derivation_sees_the_four_parts(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def capture(provider, system, user, schema, **kwargs):
        captured["user"] = user

    monkeypatch.setattr(agents, "_structured", capture)

    async def go() -> None:
        await agents.derive_research_questions(PROBLEM, position=NotepadDoc(**POSITION))

    asyncio.run(go())
    assert "## RESEARCHER POSITION" in captured["user"]
    assert POSITION["prior"] in captured["user"]


def _seeded_service() -> tuple[FocusedPanelService, str]:
    service = FocusedPanelService()
    view = service.create_workspace(
        problem=PROBLEM,
        research_questions=[],
        position=dict(POSITION),
        arm="guided",
        demo=True,
    )
    session_id = view.active.id
    state = service.get(session_id)
    state.papers = [
        ExpPaper(
            id="p1",
            title="Broad-spectrum exposure and resistance",
            abstract="Longer exposure selects for resistance genes.",
            abstract_sentences=["Longer exposure selects for resistance genes."],
        )
    ]
    state.clusters = [
        ClusterCard(
            id="cluster-1",
            name="Resistance ecology",
            blurb="Reads prescribing as evolutionary pressure.",
            facets=[
                FacetEvidence(
                    facet=facet,
                    text="Longer exposure selects for resistance genes.",
                    paper_id="p1",
                    sentence_index=0,
                    sentence="Longer exposure selects for resistance genes.",
                )
                for facet in FACETS
            ],
            paper_ids=["p1"],
            representative_paper_ids=["p1"],
        )
    ]
    state.searched = True
    return service, session_id


def test_the_researchers_job_and_description_land_verbatim() -> None:
    async def go() -> None:
        service, session_id = _seeded_service()
        await service.generate_perspective(
            session_id,
            cluster_id="cluster-1",
            name="Resistance ecologist",
            description="I weigh prescribing by what accumulates in the population.",
        )
        perspective = service.get(session_id).perspectives[0]
        assert perspective.name == "Resistance ecologist"
        assert (
            perspective.summary
            == "I weigh prescribing by what accumulates in the population."
        )
        # The derived framing is still recorded; it is the prefill, not the
        # authority, so the researcher's wording is not silently replaced.
        assert perspective.framing is not None

    asyncio.run(go())


def test_an_unedited_description_falls_back_to_the_derived_framing() -> None:
    async def go() -> None:
        service, session_id = _seeded_service()
        await service.generate_perspective(session_id, cluster_id="cluster-1")
        perspective = service.get(session_id).perspectives[0]
        assert perspective.framing is not None
        assert perspective.summary == perspective.framing.framing
        assert perspective.name == "Resistance ecology"

    asyncio.run(go())


def test_a_whitespace_description_does_not_blank_the_perspective() -> None:
    async def go() -> None:
        service, session_id = _seeded_service()
        await service.generate_perspective(
            session_id, cluster_id="cluster-1", description="   \n  "
        )
        perspective = service.get(session_id).perspectives[0]
        assert perspective.summary.strip()

    asyncio.run(go())


def test_one_perspective_is_enough_to_leave_step_two() -> None:
    """His spec: "Once at least one exists, Continue to group chat opens." """

    async def go() -> None:
        service, session_id = _seeded_service()
        await service.generate_perspective(
            session_id, cluster_id="cluster-1", name="Only one"
        )
        state = service.get(session_id)
        built = [
            perspective
            for perspective in state.perspectives
            if not perspective.id.startswith("optimistic:")
        ]
        assert len(built) == 1
        # The discussion can open on a single Perspective.
        await service.start_notepad(session_id)
        notepad = service.get(session_id).notepad
        assert notepad is not None
        assert notepad.in_chat == [built[0].id]

    asyncio.run(go())


def test_the_position_survives_into_the_document_unchanged() -> None:
    """Step 1 writes it, Step 2 shows it read-only, Step 3 edits it."""

    async def go() -> None:
        service, session_id = _seeded_service()
        state = service.get(session_id)
        for part, text in POSITION.items():
            assert getattr(state.position, part) == text
        await service.generate_perspective(session_id, cluster_id="cluster-1")
        await service.start_notepad(session_id)
        notepad = service.get(session_id).notepad
        assert notepad is not None
        version = notepad.active_version()
        assert version is not None
        for part, text in POSITION.items():
            assert getattr(version.doc, part) == text

    asyncio.run(go())


@pytest.mark.parametrize("part", list(POSITION))
def test_every_part_reaches_the_query_prompt(monkeypatch, part: str) -> None:
    captured: dict[str, str] = {}

    async def capture(provider, system, user, schema, **kwargs):
        captured["user"] = user

    monkeypatch.setattr(agents, "_structured", capture)

    async def go() -> None:
        await agents.suggest_queries(
            PROBLEM, [], position=NotepadDoc(**{part: POSITION[part]})
        )

    asyncio.run(go())
    assert POSITION[part] in captured["user"]


def _second_cluster(service: FocusedPanelService, session_id: str) -> None:
    state = service.get(session_id)
    state.papers.append(
        ExpPaper(
            id="p2",
            title="Microbiome recovery after therapy",
            abstract="Diversity recovery remains incomplete.",
            abstract_sentences=["Diversity recovery remains incomplete."],
        )
    )
    state.clusters.append(
        ClusterCard(
            id="cluster-2",
            name="Host and microbiome",
            blurb="Treats the patient's microbial ecology as an outcome.",
            facets=[
                FacetEvidence(
                    facet=facet,
                    text="Diversity recovery remains incomplete.",
                    paper_id="p2",
                    sentence_index=0,
                    sentence="Diversity recovery remains incomplete.",
                )
                for facet in FACETS
            ],
            paper_ids=["p2"],
            representative_paper_ids=["p2"],
        )
    )


def test_a_perspective_built_later_joins_the_discussion() -> None:
    """His spec: the dashed box builds one "which joins the chat on return"."""

    async def go() -> None:
        service, session_id = _seeded_service()
        await service.generate_perspective(session_id, cluster_id="cluster-1")
        await service.start_notepad(session_id)
        notepad = service.get(session_id).notepad
        assert notepad is not None
        assert len(notepad.in_chat) == 1

        _second_cluster(service, session_id)
        await service.generate_perspective(session_id, cluster_id="cluster-2")

        state = service.get(session_id)
        assert state.notepad is not None
        built = [p.id for p in state.perspectives]
        # Both take part; the newcomer is not silently excluded.
        assert state.notepad.in_chat == built

    asyncio.run(go())


def test_the_newcomer_speaks_in_the_next_round() -> None:
    async def go() -> None:
        service, session_id = _seeded_service()
        await service.generate_perspective(session_id, cluster_id="cluster-1")
        await service.start_notepad(session_id)
        _second_cluster(service, session_id)
        await service.generate_perspective(
            session_id, cluster_id="cluster-2", name="Host and microbiome"
        )
        await service.discuss_notepad(session_id, turns=2)
        notepad = service.get(session_id).notepad
        assert notepad is not None
        speakers = {
            turn.author_label for turn in notepad.turns if turn.role == "perspective"
        }
        assert "Host and microbiome" in speakers

    asyncio.run(go())


def test_removing_a_perspective_drops_it_from_the_discussion() -> None:
    async def go() -> None:
        service, session_id = _seeded_service()
        await service.generate_perspective(session_id, cluster_id="cluster-1")
        await service.start_notepad(session_id)
        _second_cluster(service, session_id)
        await service.generate_perspective(session_id, cluster_id="cluster-2")
        state = service.get(session_id)
        doomed = state.perspectives[1].id

        await service.remove_perspective(session_id, doomed)

        state = service.get(session_id)
        assert state.notepad is not None
        # No dead ids left on the roster.
        assert doomed not in state.notepad.in_chat
        assert all(
            any(p.id == item for p in state.perspectives)
            for item in state.notepad.in_chat
        )

    asyncio.run(go())


def test_building_before_the_discussion_opens_touches_no_roster() -> None:
    async def go() -> None:
        service, session_id = _seeded_service()
        await service.generate_perspective(session_id, cluster_id="cluster-1")
        assert service.get(session_id).notepad is None

    asyncio.run(go())
