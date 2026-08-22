"""Hermetic FastAPI surface used by browser end-to-end tests."""

from fastapi import FastAPI

from agora.api.focused import focused_router
from agora.focused.service import FocusedPanelService

app = FastAPI()
app.state.focused = FocusedPanelService()
app.include_router(focused_router, prefix="/api/v1")
