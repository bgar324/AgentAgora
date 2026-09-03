from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agora.api.focused import focused_router
from agora.focused.demo_data import DEMO_PAPERS
from agora.focused.persistence import FocusedPersistence
from agora.focused.service import FocusedPanelService, SessionError
from agora.focused.study_export import export_study_log
from agora.focused.study_export import main as export_study_log_main
from agora.focused.study_log import (
    ACTION_STAGES,
    StudyAction,
    StudyAssignment,
    StudyEvent,
    StudyOutcome,
    build_study_event,
)


def sqlite_persistence() -> tuple[sqlite3.Connection, FocusedPersistence]:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection, FocusedPersistence(connection)


def test_service_records_terminal_events_and_retains_history_after_delete() -> None:
    connection, persistence = sqlite_persistence()
    try:
        service = FocusedPanelService(persistence=persistence)
        view = service.create_workspace(
            problem="How should antibiotic breadth be bounded?",
            demo=True,
            participant_id="P-0042",
            condition="baseline-a",
        )
        session_id = view.active.id
        workspace_id = view.workspace.id

        asyncio.run(service.suggest_queries(session_id))
        revision_before_failure = service.workspace_view(
            workspace_id
        ).workspace.revision
        with pytest.raises(SessionError, match="Pick at least one query"):
            asyncio.run(service.run_search(session_id, []))
        assert (
            service.workspace_view(workspace_id).workspace.revision
            == revision_before_failure
        )
        untrusted_object_id = "RAW PARTICIPANT DRAFT MUST NOT BE LOGGED"
        with pytest.raises(SessionError, match="not found"):
            asyncio.run(
                service.generate_perspective(
                    session_id,
                    paper_id=untrusted_object_id,
                )
            )

        service.delete_workspace(workspace_id)

        assert persistence.load() == ([], [])
        assignments = persistence.load_study_assignments()
        assert len(assignments) == 1
        assert assignments[0].workspace_id == workspace_id
        assert assignments[0].participant_id == "P-0042"
        assert assignments[0].condition == "baseline-a"
        events = persistence.load_study_events()
        assert [event.action for event in events] == [
            StudyAction.WORKSPACE_CREATE,
            StudyAction.QUERIES_SUGGEST,
            StudyAction.PAPERS_SEARCH,
            StudyAction.PERSPECTIVE_CREATE,
            StudyAction.WORKSPACE_DELETE,
        ]
        assert [event.outcome for event in events] == [
            StudyOutcome.SUCCESS,
            StudyOutcome.SUCCESS,
            StudyOutcome.FAILURE,
            StudyOutcome.FAILURE,
            StudyOutcome.SUCCESS,
        ]
        assert [event.event_seq for event in events] == [1, 2, 3, 4, 5]
        assert all(event.participant_id == "P-0042" for event in events)
        assert all(event.condition == "baseline-a" for event in events)
        assert events[0].revision_before is None
        assert events[0].revision_after == 0
        assert events[1].revision_before == 0
        assert events[1].revision_after == 1
        assert events[2].revision_before == revision_before_failure
        assert events[2].revision_after == revision_before_failure
        assert events[2].error_code == "invalid_request"
        assert events[3].object_id is None
        assert untrusted_object_id not in events[3].model_dump_json()
        assert events[4].revision_before == revision_before_failure
        assert events[4].revision_after is None
        assert all(event.duration_ms >= 0 for event in events)
    finally:
        connection.close()


def test_paper_detail_records_views_without_leaking_failed_ids() -> None:
    connection, persistence = sqlite_persistence()
    try:
        service = FocusedPanelService(persistence=persistence)
        view = service.create_workspace(
            problem="Which retrieved papers did participants inspect?",
            demo=True,
            participant_id="P-0042",
            condition="baseline-a",
        )
        paper = DEMO_PAPERS[0].model_copy(deep=True)
        service.get(view.active.id).papers = [paper]

        detail = asyncio.run(service.paper_detail(view.active.id, paper.id))
        assert detail.id == paper.id

        untrusted_object_id = "RAW PARTICIPANT DRAFT MUST NOT BE LOGGED"
        with pytest.raises(SessionError, match="not in this session"):
            asyncio.run(
                service.paper_detail(view.active.id, untrusted_object_id)
            )

        events = persistence.load_study_events()
        assert [event.action for event in events] == [
            StudyAction.WORKSPACE_CREATE,
            StudyAction.PAPER_VIEW,
            StudyAction.PAPER_VIEW,
        ]
        assert events[1].outcome == StudyOutcome.SUCCESS
        assert events[1].object_type == "paper"
        assert events[1].object_id == paper.id
        assert events[1].revision_before == events[1].revision_after == 0
        assert events[2].outcome == StudyOutcome.FAILURE
        assert events[2].object_id is None
        assert untrusted_object_id not in events[2].model_dump_json()
    finally:
        connection.close()


def test_event_metadata_records_shape_not_research_content() -> None:
    sentinel = "RAW PARTICIPANT DRAFT MUST NOT BE LOGGED"
    event = build_study_event(
        event_id="a" * 32,
        action=StudyAction.DOCUMENT_EDIT,
        assignment=None,
        workspace_id="workspace",
        session_id="session",
        outcome=StudyOutcome.SUCCESS,
        occurred_at=StudyAssignment(
            workspace_id="workspace",
            condition="baseline",
        ).assigned_at,
        duration_ms=4,
        revision_before=3,
        revision_after=4,
        arguments={
            "version_id": "v1",
            "part": "method",
            "text": sentinel,
        },
    )

    serialized = event.model_dump_json()
    assert sentinel not in serialized
    assert event.details == {
        "part": "method",
        "text_characters": len(sentinel),
    }
    assert event.object_type == "version"
    assert event.object_id == "v1"
    for index, (action, arguments, expected_details) in enumerate(
        [
            (
                StudyAction.PAPERS_SEARCH,
                {"queries": [sentinel]},
                {"query_count": 1},
            ),
            (
                StudyAction.QUESTION_SEND,
                {"version_id": "v1", "message": sentinel},
                {"message_characters": len(sentinel)},
            ),
            (
                StudyAction.PERSPECTIVE_CREATE,
                {
                    "paper_id": "paper-1",
                    "name": sentinel,
                    "description": sentinel,
                },
                {
                    "custom_name": True,
                    "description_characters": len(sentinel),
                },
            ),
        ]
    ):
        content_event = build_study_event(
            event_id=f"{index + 12:x}" * 32,
            action=action,
            assignment=None,
            workspace_id="workspace",
            session_id="session",
            outcome=StudyOutcome.SUCCESS,
            occurred_at=event.occurred_at,
            duration_ms=1,
            revision_before=3,
            revision_after=4,
            arguments=arguments,
        )
        assert sentinel not in content_event.model_dump_json()
        assert content_event.details == expected_details

    with pytest.raises(ValidationError, match="unsupported study event details"):
        StudyEvent.model_validate(
            {
                **event.model_dump(),
                "details": {"text": sentinel},
            }
        )


def test_sqlite_rolls_back_snapshot_when_success_event_cannot_persist() -> None:
    connection, persistence = sqlite_persistence()
    try:
        service = FocusedPanelService(persistence=persistence)
        view = service.create_workspace(
            problem="Can snapshot and event writes diverge?",
            demo=True,
        )
        workspace, investigations = persistence.load()
        next_workspace = workspace[0].model_copy(
            update={"revision": workspace[0].revision + 1}
        )
        assignment = persistence.load_study_assignments()[0]
        connection.execute(
            """
            create trigger reject_test_event
            before insert on focused_interaction_events
            begin
                select raise(abort, 'injected event failure');
            end
            """
        )
        event = build_study_event(
            event_id="b" * 32,
            action=StudyAction.QUERIES_SUGGEST,
            assignment=assignment,
            workspace_id=view.workspace.id,
            session_id=view.active.id,
            outcome=StudyOutcome.SUCCESS,
            occurred_at=assignment.assigned_at,
            duration_ms=1,
            revision_before=0,
            revision_after=1,
            arguments={},
        )

        with pytest.raises(sqlite3.DatabaseError, match="injected event failure"):
            persistence.save(
                next_workspace,
                investigations,
                expected_revision=0,
                event=event,
            )

        restored, _ = persistence.load()
        assert restored[0].revision == 0
        assert [item.action for item in persistence.load_study_events()] == [
            StudyAction.WORKSPACE_CREATE
        ]
    finally:
        connection.close()


def test_sqlite_study_history_rejects_update_and_delete() -> None:
    connection, persistence = sqlite_persistence()
    try:
        service = FocusedPanelService(persistence=persistence)
        service.create_workspace(problem="Is the study log append-only?", demo=True)

        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute(
                "update focused_interaction_events set action = 'chat.clear'"
            )
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute("delete from focused_study_assignments")
    finally:
        connection.close()


def test_api_validates_and_persists_study_assignment() -> None:
    connection, persistence = sqlite_persistence()
    try:
        app = FastAPI()
        app.state.focused = FocusedPanelService(persistence=persistence)
        app.include_router(focused_router)
        client = TestClient(app)

        response = client.post(
            "/focused/workspaces",
            json={
                "problem": "How should antibiotic breadth be bounded?",
                "participant_id": "P_0042",
                "condition": "treatment-1",
                "demo": True,
            },
        )
        assert response.status_code == 200
        assignment = persistence.load_study_assignments()[0]
        assert assignment.participant_id == "P_0042"
        assert assignment.condition == "treatment-1"

        invalid = client.post(
            "/focused/workspaces",
            json={
                "problem": "How should antibiotic breadth be bounded?",
                "participant_id": "person@example.com",
                "condition": "Treatment Group",
                "demo": True,
            },
        )
        assert invalid.status_code == 422
    finally:
        connection.close()


def test_export_is_stable_ndjson_without_snapshot_content() -> None:
    connection, persistence = sqlite_persistence()
    try:
        service = FocusedPanelService(persistence=persistence)
        service.create_workspace(
            problem="SECRET RESEARCH PROBLEM",
            demo=True,
            participant_id="P-7",
            condition="baseline",
        )
        output = io.StringIO()

        assert export_study_log(persistence, output) == 2
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        assert [record["record_type"] for record in records] == [
            "assignment",
            "event",
        ]
        assert records[1]["event_seq"] == 1
        assert "SECRET RESEARCH PROBLEM" not in output.getvalue()
        assert records[1]["details"]["problem_characters"] == len(
            "SECRET RESEARCH PROBLEM"
        )
        assert records[1]["stage"] == ACTION_STAGES[StudyAction.WORKSPACE_CREATE]
    finally:
        connection.close()


def test_export_cli_refuses_to_replace_its_sqlite_source(
    tmp_path,
    monkeypatch,
) -> None:
    sqlite_path = tmp_path / "focused.db"
    connection = sqlite3.connect(sqlite_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        service = FocusedPanelService(persistence=FocusedPersistence(connection))
        service.create_workspace(
            problem="The export must not destroy this workspace.",
            demo=True,
        )
    finally:
        connection.close()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "study-export",
            "--sqlite",
            str(sqlite_path),
            "--output",
            str(sqlite_path),
        ],
    )
    with pytest.raises(ValueError, match="cannot replace its SQLite source"):
        export_study_log_main()

    connection = sqlite3.connect(sqlite_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        persistence = FocusedPersistence(connection)
        assert len(persistence.load()[0]) == 1
        assert len(persistence.load_study_events()) == 1
    finally:
        connection.close()
