from __future__ import annotations

import asyncio
import sqlite3

import pytest

from agora.focused import agents
from agora.focused.models import (
    FACETS,
    AgentState,
    DeliberationRound,
    FacetEvidence,
    HypothesisDev,
    Perspective,
    RecommendedQuestion,
)
from agora.focused.persistence import FocusedPersistence
from agora.focused.service import FocusedPanelService, SessionError

PROBLEM = (
    "How should broad antibiotic coverage balance acute benefit and ecological harm?"
)


def hypothesis(label: str) -> HypothesisDev:
    return HypothesisDev(
        problem=f"{label} problem",
        previous_work=f"{label} previous work",
        reasoning=f"{label} reasoning",
        hypothesis=f"{label} testable claim",
    )


def panel_perspective(perspective_id: str, name: str, prefix: str) -> Perspective:
    return Perspective(
        id=perspective_id,
        name=name,
        color="#345678",
        facets={
            facet: FacetEvidence(
                facet=facet,
                text=f"{prefix} {facet}",
                edited=True,
            )
            for facet in FACETS
        },
    )


async def apply_checkpoint(
    service: FocusedPanelService,
    investigation_id: str,
    value: HypothesisDev,
) -> None:
    state = await service.create_deliberation(investigation_id)
    deliberation = state.deliberations[0]
    deliberation.rounds.append(
        DeliberationRound(
            n=len(deliberation.rounds) + 1,
            lead_iid=1,
            facets=["scope"],
            completed=True,
        )
    )
    deliberation.hypothesis = value.model_copy(deep=True)
    deliberation.hypothesis_confirmed = False
    await service.confirm_deliberation_hypothesis(
        investigation_id,
        deliberation.id,
        value,
    )
    await service.save_deliberation_hypothesis(
        investigation_id,
        deliberation.id,
    )


def add_open_question(
    service: FocusedPanelService,
    investigation_id: str,
    question_id: str,
    text: str,
) -> None:
    state = service.get(investigation_id)
    deliberation = state.deliberations[0]
    deliberation.recommended_questions.append(
        RecommendedQuestion(
            id=question_id,
            question=text,
            rationale="The panel left this boundary unresolved.",
            source_kind="unsettled",
            source_point="Unresolved boundary",
            facets=["scope"],
        )
    )
    deliberation.questions_generated = True


def test_child_branches_from_last_applied_checkpoint_while_update_is_pending() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        view = service.create_workspace(
            problem=PROBLEM,
            research_questions=["What is the initial boundary?"],
            demo=True,
        )
        root = view.active
        await apply_checkpoint(service, root.id, hypothesis("H1"))
        root = service.get(root.id)
        deliberation = root.deliberations[0]
        pending = hypothesis("pending")
        deliberation.rounds.append(
            DeliberationRound(
                n=2,
                lead_iid=1,
                facets=["approach"],
                completed=True,
            )
        )
        deliberation.hypothesis = pending
        deliberation.hypothesis_confirmed = False
        add_open_question(
            service,
            root.id,
            "q-pending",
            "Which evidence would resolve the pending approach?",
        )

        child_view = await service.create_child_investigation(
            root.workspace_id,
            root.id,
            "q-pending",
        )
        parent = service.get(root.id)
        child = child_view.active

        assert parent.deliberations[0].hypothesis == pending
        assert not parent.deliberations[0].hypothesis_confirmed
        assert parent.applied_hypothesis == hypothesis("H1")
        assert child.applied_hypothesis == hypothesis("H1")
        assert child.applied_hypothesis is not parent.applied_hypothesis
        assert child.applied_hypothesis_version_id == "H1"
        assert child.research_questions == [
            "Which evidence would resolve the pending approach?"
        ]
        assert child.papers == []
        assert child.perspectives == []
        assert child.agents == []
        assert child.deliberations == []
        question = parent.deliberations[0].recommended_questions[0]
        assert question.status == "investigating"
        assert question.child_investigation_id == child.id

        with pytest.raises(SessionError, match="Only an open question"):
            await service.create_child_investigation(
                root.workspace_id,
                root.id,
                "q-pending",
            )

        with pytest.raises(SessionError, match="research problem is shared"):
            service.update_brief(
                child.id,
                problem="A different root problem",
                research_questions=child.research_questions,
            )

        service.set_question_status(
            root.workspace_id,
            root.id,
            question.id,
            "archived",
        )
        assert (
            service.get(root.id).deliberations[0].recommended_questions[0].status
            == "archived"
        )
        with pytest.raises(SessionError, match="archived to open"):
            service.set_question_status(
                root.workspace_id,
                root.id,
                question.id,
                "open",
            )
        service.set_question_status(
            root.workspace_id,
            root.id,
            question.id,
            "investigating",
        )

    asyncio.run(go())


def test_applied_hypothesis_is_not_a_checkpoint_until_saved() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        root = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        state = await service.create_deliberation(root.id)
        deliberation = state.deliberations[0]
        deliberation.rounds.append(
            DeliberationRound(
                n=1,
                lead_iid=1,
                facets=["scope"],
                completed=True,
            )
        )
        value = hypothesis("working")
        deliberation.hypothesis = value.model_copy(deep=True)
        deliberation.hypothesis_confirmed = False

        applied = await service.confirm_deliberation_hypothesis(
            root.id,
            deliberation.id,
            value,
        )

        assert applied.deliberations[0].applied_hypothesis == value
        assert applied.applied_hypothesis_version_id is None
        assert (
            service.workspace_view(root.workspace_id).workspace.hypothesis_versions
            == []
        )

        saved = await service.save_deliberation_hypothesis(
            root.id,
            deliberation.id,
        )

        assert saved.applied_hypothesis_version_id == "H1"
        assert [
            version.id
            for version in service.workspace_view(
                root.workspace_id
            ).workspace.hypothesis_versions
        ] == ["H1"]

    asyncio.run(go())


def test_repeating_an_applied_hypothesis_does_not_fabricate_a_checkpoint() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        root = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        await apply_checkpoint(service, root.id, hypothesis("root"))
        state = service.get(root.id)
        deliberation = state.deliberations[0]

        state = await service.confirm_deliberation_hypothesis(
            root.id,
            deliberation.id,
            hypothesis("root"),
        )

        assert state.applied_hypothesis_version_id == "H1"
        assert [
            version.id
            for version in service.workspace_view(
                root.workspace_id
            ).workspace.hypothesis_versions
        ] == ["H1"]

    asyncio.run(go())


def test_unchanged_pending_hypothesis_reuses_the_applied_checkpoint() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        root = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        await apply_checkpoint(service, root.id, hypothesis("root"))
        state = service.get(root.id)
        deliberation = state.deliberations[0]
        deliberation.rounds.append(
            DeliberationRound(
                n=2,
                lead_iid=1,
                facets=["scope"],
                completed=True,
            )
        )
        deliberation.hypothesis = hypothesis("root")
        deliberation.hypothesis_confirmed = False

        state = await service.confirm_deliberation_hypothesis(
            root.id,
            deliberation.id,
            hypothesis("root"),
        )

        assert state.applied_hypothesis_version_id == "H1"
        assert state.deliberations[0].hypothesis_confirmed
        assert (
            len(service.workspace_view(root.workspace_id).workspace.hypothesis_versions)
            == 1
        )

    asyncio.run(go())


def test_edit_applied_creates_a_provenance_preserving_version() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        root = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        await apply_checkpoint(service, root.id, hypothesis("root"))
        state = service.get(root.id)
        deliberation = state.deliberations[0]
        edited = hypothesis("root").model_copy(
            update={"reasoning": "researcher-edited reasoning"}
        )

        state = await service.confirm_deliberation_hypothesis(
            root.id,
            deliberation.id,
            edited,
            mode="edit_applied",
        )

        assert state.applied_hypothesis_version_id == "H1"
        assert (
            len(service.workspace_view(root.workspace_id).workspace.hypothesis_versions)
            == 1
        )

        state = await service.save_deliberation_hypothesis(
            root.id,
            deliberation.id,
        )

        assert state.applied_hypothesis_version_id == "H2"
        version = service.workspace_view(
            root.workspace_id
        ).workspace.hypothesis_versions[-1]
        assert version.source_kind == "edit"
        assert version.parent_ids == ["H1"]
        assert version.step_sources == {
            "problem": "H1",
            "previous_work": "H1",
            "reasoning": "H2",
            "hypothesis": "H1",
        }
        assert (
            service.workspace_view(
                root.workspace_id
            ).workspace.promoted_hypothesis_version_id
            == "H2"
        )

        await service.confirm_deliberation_hypothesis(
            root.id,
            deliberation.id,
            edited,
            mode="edit_applied",
        )
        await service.save_deliberation_hypothesis(
            root.id,
            deliberation.id,
        )
        assert (
            len(service.workspace_view(root.workspace_id).workspace.hypothesis_versions)
            == 2
        )

    asyncio.run(go())


def test_hypothesis_versions_promote_merge_archive_and_close_question() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        view = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        )
        root = view.active
        await apply_checkpoint(service, root.id, hypothesis("root"))
        add_open_question(service, root.id, "q-one", "What does branch one establish?")
        add_open_question(service, root.id, "q-two", "What does branch two establish?")

        first = (
            await service.create_child_investigation(
                root.workspace_id,
                root.id,
                "q-one",
            )
        ).active
        await apply_checkpoint(service, first.id, hypothesis("first"))
        first_version = service.get(first.id).applied_hypothesis_version_id
        assert first_version == "H2"

        second = (
            await service.create_child_investigation(
                root.workspace_id,
                root.id,
                "q-two",
            )
        ).active
        assert second.applied_hypothesis_version_id == "H1"
        await apply_checkpoint(service, second.id, hypothesis("second"))
        second_version = service.get(second.id).applied_hypothesis_version_id
        assert second_version == "H3"

        promoted = service.promote_hypothesis(root.workspace_id, first_version)
        assert promoted.workspace.promoted_hypothesis_version_id == "H2"
        assert (
            service.get(root.id).deliberations[0].recommended_questions[0].status
            == "addressed"
        )

        service.promote_hypothesis(root.workspace_id, second_version)
        merged = service.merge_hypotheses(
            root.workspace_id,
            target_investigation_id=second.id,
            source_version_id=first_version,
            parts_from_source=["problem", "hypothesis"],
        )
        assert merged.workspace.promoted_hypothesis_version_id == "H4"
        merged_version = merged.workspace.hypothesis_versions[-1]
        assert merged_version.parent_ids == ["H3", "H2"]
        assert merged_version.source_kind == "merge"
        assert merged_version.steps.problem == "first problem"
        assert merged_version.steps.hypothesis == "first testable claim"
        assert merged_version.steps.previous_work == "second previous work"
        assert merged_version.steps.reasoning == "second reasoning"
        assert merged_version.step_sources == {
            "problem": "H2",
            "previous_work": "H3",
            "reasoning": "H3",
            "hypothesis": "H2",
        }

        with pytest.raises(SessionError, match="current checkpoint"):
            service.promote_hypothesis(root.workspace_id, "H3")

        archived = service.archive_hypothesis(root.workspace_id, "H3")
        assert archived.workspace.hypothesis_versions[2].archived
        restored = service.restore_hypothesis(root.workspace_id, "H3")
        assert not restored.workspace.hypothesis_versions[2].archived
        service.archive_hypothesis(root.workspace_id, "H3")
        with pytest.raises(SessionError, match="Promote another"):
            service.archive_hypothesis(root.workspace_id, "H4")

    asyncio.run(go())


def test_merge_cannot_overwrite_a_pending_panel_update() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        root = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        await apply_checkpoint(service, root.id, hypothesis("root"))
        add_open_question(service, root.id, "q-merge", "What should merge?")
        child = (
            await service.create_child_investigation(
                root.workspace_id,
                root.id,
                "q-merge",
            )
        ).active
        await apply_checkpoint(service, child.id, hypothesis("child"))
        deliberation = service.get(root.id).deliberations[0]
        deliberation.hypothesis = hypothesis("pending")
        deliberation.hypothesis_confirmed = False

        with pytest.raises(SessionError, match="pending"):
            service.merge_hypotheses(
                root.workspace_id,
                target_investigation_id=root.id,
                source_version_id="H2",
                parts_from_source=["problem"],
            )

    asyncio.run(go())


def test_promoted_merge_addresses_its_contributing_child_question() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        root = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        await apply_checkpoint(service, root.id, hypothesis("root"))
        add_open_question(service, root.id, "q-source", "What does the child add?")
        child = (
            await service.create_child_investigation(
                root.workspace_id,
                root.id,
                "q-source",
            )
        ).active
        await apply_checkpoint(service, child.id, hypothesis("child"))

        merged = service.merge_hypotheses(
            root.workspace_id,
            target_investigation_id=root.id,
            source_version_id="H2",
            parts_from_source=["reasoning"],
        )

        assert merged.workspace.promoted_hypothesis_version_id == "H3"
        question = service.get(root.id).deliberations[0].recommended_questions[0]
        assert question.status == "addressed"

    asyncio.run(go())


def test_repeated_unsettled_round_does_not_duplicate_open_question() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        state = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        state.perspectives = [
            panel_perspective("first", "First", "first"),
            panel_perspective("second", "Second", "second"),
        ]
        state = await service.create_deliberation(state.id)
        deliberation = state.deliberations[0]
        agent_iids = [agent.iid for agent in state.agents]

        for _ in range(2):
            await service.run_round(
                state.id,
                deliberation.id,
                lead_iid=agent_iids[0],
                facets=["scope"],
            )

        questions = service.get(state.id).deliberations[0].recommended_questions
        identities = {
            " ".join(question.question.casefold().split()) for question in questions
        }
        assert len(questions) == len(identities)

    asyncio.run(go())


def test_concurrent_round_requests_serialize_without_detached_side_effects(
    monkeypatch,
) -> None:
    async def go() -> None:
        service = FocusedPanelService()
        state = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        state.perspectives = [
            panel_perspective("first", "First", "first"),
            panel_perspective("second", "Second", "second"),
        ]
        state = await service.create_deliberation(state.id)
        deliberation = state.deliberations[0]
        agent_iids = [agent.iid for agent in state.agents]

        entered = asyncio.Event()
        release = asyncio.Event()
        original = agents.open_statement
        first_call = True

        async def slow_first_open(*args, **kwargs):
            nonlocal first_call
            if first_call:
                first_call = False
                entered.set()
                await release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(agents, "open_statement", slow_first_open)
        first_round = asyncio.create_task(
            service.run_round(
                state.id,
                deliberation.id,
                lead_iid=agent_iids[0],
                facets=["scope"],
            )
        )
        await entered.wait()
        second_round = asyncio.create_task(
            service.run_round(
                state.id,
                deliberation.id,
                lead_iid=agent_iids[1],
                facets=["explanation"],
            )
        )
        await asyncio.sleep(0.05)
        assert not second_round.done()

        release.set()
        await asyncio.gather(first_round, second_round)
        rounds = service.get(state.id).deliberations[0].rounds
        assert [round_state.n for round_state in rounds] == [1, 2]
        assert all(round_state.completed for round_state in rounds)

    asyncio.run(go())


def test_workspace_lock_preserves_sibling_mutation_after_failed_round(
    monkeypatch,
) -> None:
    async def go() -> None:
        service = FocusedPanelService()
        root = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        await apply_checkpoint(service, root.id, hypothesis("root"))
        add_open_question(service, root.id, "q-child", "First child?")
        add_open_question(service, root.id, "q-sibling", "Second child?")
        child = (
            await service.create_child_investigation(
                root.workspace_id,
                root.id,
                "q-child",
            )
        ).active
        child.perspectives = [
            panel_perspective("first", "First", "first"),
            panel_perspective("second", "Second", "second"),
        ]
        child = await service.create_deliberation(child.id)
        deliberation = child.deliberations[0]
        agent_iids = [agent.iid for agent in child.agents]

        entered = asyncio.Event()
        release = asyncio.Event()
        original = agents.open_statement

        async def slow_open(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        async def fail_questions(*_args, **_kwargs):
            raise RuntimeError("round failed")

        monkeypatch.setattr(agents, "open_statement", slow_open)
        monkeypatch.setattr(agents, "recommend_questions", fail_questions)
        round_task = asyncio.create_task(
            service.run_round(
                child.id,
                deliberation.id,
                lead_iid=agent_iids[0],
                facets=["scope"],
            )
        )
        await entered.wait()
        branch_task = asyncio.create_task(
            service.create_child_investigation(
                root.workspace_id,
                root.id,
                "q-sibling",
            )
        )
        await asyncio.sleep(0.05)
        assert not branch_task.done()

        release.set()
        with pytest.raises(RuntimeError, match="round failed"):
            await round_task
        sibling = (await branch_task).active

        assert (
            sibling.id
            in service.workspace_view(root.workspace_id).workspace.investigation_ids
        )
        assert service.get(child.id).deliberations[0].rounds == []

    asyncio.run(go())


def test_failed_round_restores_the_entire_in_memory_investigation(
    monkeypatch,
) -> None:
    async def go() -> None:
        service = FocusedPanelService()
        state = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        state.perspectives = [
            panel_perspective("first", "First", "first"),
            panel_perspective("second", "Second", "second"),
        ]
        state = await service.create_deliberation(state.id)
        deliberation = state.deliberations[0]
        agent_iids = [agent.iid for agent in state.agents]
        before = service.get(state.id).model_dump(mode="json")

        async def fail_after_reflection(*_args, **_kwargs):
            raise RuntimeError("question generation failed")

        monkeypatch.setattr(agents, "recommend_questions", fail_after_reflection)
        with pytest.raises(RuntimeError, match="question generation failed"):
            await service.run_round(
                state.id,
                deliberation.id,
                lead_iid=agent_iids[0],
                facets=["scope"],
            )

        assert service.get(state.id).model_dump(mode="json") == before

    asyncio.run(go())


def test_panel_automatically_includes_more_than_three_agents() -> None:
    async def go() -> None:
        service = FocusedPanelService()
        state = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        state.agents = [
            AgentState(iid=index, perspective_id=f"persp-{index}", label=f"P{index}")
            for index in range(1, 6)
        ]
        state = await service.create_deliberation(state.id)
        deliberation = state.deliberations[0]
        assert deliberation.agent_iids == [1, 2, 3, 4, 5]

    asyncio.run(go())


def test_workspace_and_lineage_reload_from_sqlite(tmp_path) -> None:
    async def go() -> None:
        connection = sqlite3.connect(tmp_path / "focused.db", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        persistence = FocusedPersistence(connection)
        service = FocusedPanelService(persistence=persistence)
        root = service.create_workspace(
            problem=PROBLEM,
            research_questions=[],
            demo=True,
        ).active
        await apply_checkpoint(service, root.id, hypothesis("persisted"))
        add_open_question(service, root.id, "q-reload", "What survives restart?")
        child = (
            await service.create_child_investigation(
                root.workspace_id,
                root.id,
                "q-reload",
            )
        ).active

        reloaded = FocusedPanelService(persistence=FocusedPersistence(connection))
        restored = reloaded.workspace_view(root.workspace_id)
        assert restored.workspace.investigation_ids == [root.id, child.id]
        assert restored.workspace.active_investigation_id == child.id
        assert restored.workspace.hypothesis_versions[0].id == "H1"
        assert restored.active.applied_hypothesis == hypothesis("persisted")
        parent = reloaded.get(root.id)
        question = parent.deliberations[0].recommended_questions[0]
        assert question.status == "investigating"
        assert question.child_investigation_id == child.id
        connection.close()

    asyncio.run(go())


def test_malformed_workspace_is_quarantined_without_blocking_healthy_state(
    tmp_path,
) -> None:
    connection = sqlite3.connect(
        tmp_path / "focused-corrupt.db",
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    service = FocusedPanelService(
        persistence=FocusedPersistence(connection),
    )
    healthy = service.create_workspace(
        problem=PROBLEM,
        research_questions=[],
        demo=True,
    ).active
    with connection:
        connection.execute(
            "insert into focused_workspaces(workspace_id, payload) values (?, ?)",
            ("broken", "{not-json"),
        )

    reloaded = FocusedPanelService(
        persistence=FocusedPersistence(connection),
    )

    assert reloaded.workspace_view(healthy.workspace_id).active.id == healthy.id
    quarantined = connection.execute(
        "select record_id from focused_quarantine where record_id = ?",
        ("broken",),
    ).fetchone()
    assert quarantined is not None
    connection.close()


def test_orphan_investigation_is_quarantined_and_not_globally_readable(
    tmp_path,
) -> None:
    connection = sqlite3.connect(
        tmp_path / "focused-orphan.db",
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    service = FocusedPanelService(
        persistence=FocusedPersistence(connection),
    )
    healthy = service.create_workspace(
        problem=PROBLEM,
        research_questions=[],
        demo=True,
    ).active
    orphan = healthy.model_copy(
        update={
            "id": "orphan",
            "workspace_id": "missing-workspace",
        }
    )
    with connection:
        connection.execute(
            """
            insert into focused_investigations(
                investigation_id, workspace_id, payload
            ) values (?, ?, ?)
            """,
            ("orphan", "missing-workspace", orphan.model_dump_json()),
        )

    reloaded = FocusedPanelService(
        persistence=FocusedPersistence(connection),
    )

    assert reloaded.workspace_view(healthy.workspace_id).active.id == healthy.id
    with pytest.raises(SessionError, match="not found"):
        reloaded.get("orphan")
    quarantined = connection.execute(
        "select record_id from focused_quarantine where record_id = 'orphan'"
    ).fetchone()
    assert quarantined is not None
    connection.close()


def test_stale_service_cannot_overwrite_a_newer_workspace_revision(tmp_path) -> None:
    database = tmp_path / "focused-cas.db"
    first_connection = sqlite3.connect(database, check_same_thread=False)
    first_connection.row_factory = sqlite3.Row
    first = FocusedPanelService(
        persistence=FocusedPersistence(first_connection),
    )
    root = first.create_workspace(
        problem=PROBLEM,
        research_questions=["original"],
        demo=True,
    ).active

    second_connection = sqlite3.connect(database, check_same_thread=False)
    second_connection.row_factory = sqlite3.Row
    stale = FocusedPanelService(
        persistence=FocusedPersistence(second_connection),
    )

    first.update_brief(
        root.id,
        problem=PROBLEM,
        research_questions=["newer"],
    )
    with pytest.raises(SessionError, match="changed in another process"):
        stale.update_brief(
            root.id,
            problem=PROBLEM,
            research_questions=["stale"],
        )

    reloaded = FocusedPanelService(
        persistence=FocusedPersistence(second_connection),
    )
    assert reloaded.get(root.id).research_questions == ["newer"]
    first_connection.close()
    second_connection.close()


def test_stale_service_cannot_resurrect_a_deleted_workspace(tmp_path) -> None:
    database = tmp_path / "focused-delete-cas.db"
    first_connection = sqlite3.connect(database, check_same_thread=False)
    first_connection.row_factory = sqlite3.Row
    first = FocusedPanelService(
        persistence=FocusedPersistence(first_connection),
    )
    root = first.create_workspace(
        problem=PROBLEM,
        research_questions=[],
        demo=True,
    ).active

    second_connection = sqlite3.connect(database, check_same_thread=False)
    second_connection.row_factory = sqlite3.Row
    stale = FocusedPanelService(
        persistence=FocusedPersistence(second_connection),
    )
    first.delete_workspace(root.workspace_id)

    with pytest.raises(SessionError, match="changed in another process"):
        stale.update_brief(
            root.id,
            problem=PROBLEM,
            research_questions=["resurrected"],
        )

    reloaded = FocusedPanelService(
        persistence=FocusedPersistence(second_connection),
    )
    with pytest.raises(SessionError, match="not found"):
        reloaded.workspace_view(root.workspace_id)
    first_connection.close()
    second_connection.close()


def test_persistence_less_validation_failure_restores_prior_state() -> None:
    service = FocusedPanelService()
    root = service.create_workspace(
        problem=PROBLEM,
        research_questions=["original"],
        demo=True,
    ).active

    with pytest.raises(ValueError):
        service.update_brief(
            root.id,
            problem=PROBLEM,
            research_questions=["x" * 5001],
        )

    assert service.get(root.id).research_questions == ["original"]


def test_cyclic_investigation_lineage_is_quarantined(tmp_path) -> None:
    connection = sqlite3.connect(
        tmp_path / "focused-cycle.db",
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    service = FocusedPanelService(
        persistence=FocusedPersistence(connection),
    )
    root = service.create_workspace(
        problem=PROBLEM,
        research_questions=[],
        demo=True,
    ).active
    corrupted = root.model_copy(
        update={
            "parent_investigation_id": root.id,
            "origin_question_id": "cycle",
            "origin_question": "Cycle",
        }
    )
    with connection:
        connection.execute(
            "update focused_investigations set payload = ? where investigation_id = ?",
            (corrupted.model_dump_json(), root.id),
        )

    reloaded = FocusedPanelService(
        persistence=FocusedPersistence(connection),
    )

    with pytest.raises(SessionError, match="not found"):
        reloaded.workspace_view(root.workspace_id)
    quarantined = connection.execute(
        "select record_id from focused_quarantine "
        "where kind = 'workspace' and record_id = ?",
        (root.workspace_id,),
    ).fetchone()
    assert quarantined is not None
    connection.close()
