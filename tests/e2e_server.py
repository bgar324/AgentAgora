"""Hermetic FastAPI surface used by browser end-to-end tests."""

import sqlite3

from fastapi import FastAPI

from agora.api.focused import focused_router
from agora.focused.persistence import FocusedPersistence
from agora.focused.service import FocusedPanelService

connection = sqlite3.connect(":memory:", check_same_thread=False)
connection.row_factory = sqlite3.Row
persistence = FocusedPersistence(connection)

app = FastAPI()
app.state.focused = FocusedPanelService(persistence=persistence)
app.include_router(focused_router, prefix="/api/v1")


@app.get("/api/v1/testing/study-events")
def study_events() -> list[dict[str, object]]:
    return [
        event.model_dump(mode="json")
        for event in persistence.load_study_events(limit=10_000)
    ]
