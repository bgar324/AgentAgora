import sqlite3
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from agora.config.settings import Settings, load_settings
from agora.db.store import SqliteDeliberationStore
from agora.core.errors import NotFound
from agora.workflow.run import Runner


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def get_runner(request: Request) -> Runner:
    return request.app.state.runner


def get_store(request: Request) -> SqliteDeliberationStore:
    return request.app.state.runner.store


SettingsDep = Annotated[Settings, Depends(get_settings)]
RunnerDep = Annotated[Runner, Depends(get_runner)]
StoreDep = Annotated[SqliteDeliberationStore, Depends(get_store)]


def require_investigation(
    investigation_id: str,
    runner: RunnerDep,
) -> sqlite3.Row:
    try:
        return runner.investigation(investigation_id)
    except NotFound as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": error.message},
        ) from error


InvestigationDep = Annotated[sqlite3.Row, Depends(require_investigation)]
