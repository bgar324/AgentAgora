import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("agora.client")

CACHE_MISS = object()
CACHE_VERSION = "1"


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__} for the cache")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


class FileCache:
    def __init__(self, directory: str | Path, *, ttl: float | None = None) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(method: str, path: str, *, params: Any = None, json_body: Any = None) -> str:
        material = _canonical_json(
            {
                "version": CACHE_VERSION,
                "method": method.upper(),
                "path": path,
                "params": params,
                "json": json_body,
            }
        )
        return sha256(material.encode()).hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str, *, ttl: float | None = None) -> Any:
        path = self._path(key)
        try:
            envelope = json.loads(path.read_text())
        except FileNotFoundError:
            self.misses += 1
            return CACHE_MISS
        except (OSError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            self.misses += 1
            return CACHE_MISS

        if not isinstance(envelope, dict):
            path.unlink(missing_ok=True)
            self.misses += 1
            return CACHE_MISS

        limit = self.ttl if ttl is None else ttl
        if limit is not None and time.time() - envelope.get("created_at", 0.0) > limit:
            path.unlink(missing_ok=True)
            self.misses += 1
            return CACHE_MISS

        self.hits += 1
        return envelope.get("value")

    def set(self, key: str, value: Any) -> None:
        try:
            payload = json.dumps(
                {"created_at": time.time(), "value": value},
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as error:
            logger.warning("Skipping cache write for %s: %s", key[:8], error)
            return

        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, path)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def clear(self) -> None:
        for path in self.directory.rglob("*.json"):
            path.unlink(missing_ok=True)
