from __future__ import annotations

from copy import deepcopy
from typing import Any

CURRENT_SCHEMA_VERSION = 6
LEGACY_SCHEMA_VERSION = 5

_HYPOTHESIS_FIELDS = frozenset(
    {
        "applied_hypothesis",
        "baseline_hypothesis",
        "hypothesis",
        "hypothesis_before",
        "hypothesis_proposal",
        "steps",
    }
)
_LEGACY_PARTS = frozenset({"problem", "previous_work", "reasoning", "hypothesis"})


def _collapse_hypotheses(value: Any) -> Any:
    if isinstance(value, list):
        return [_collapse_hypotheses(item) for item in value]
    if not isinstance(value, dict):
        return value

    out: dict[str, Any] = {}
    for key, item in value.items():
        if (
            key in _HYPOTHESIS_FIELDS
            and isinstance(item, dict)
            and _LEGACY_PARTS <= item.keys()
        ):
            out[key] = {"hypothesis": item["hypothesis"]}
        elif key == "step_sources" and isinstance(item, dict):
            source = item.get("hypothesis")
            out[key] = {"hypothesis": source} if source else {}
        else:
            out[key] = _collapse_hypotheses(item)
    return out


def migrate_v5_payloads(
    workspace_payload: dict[str, Any],
    investigation_payloads: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], bool]:
    """Transform one persisted v5 aggregate into the strict v6 hypothesis shape."""

    version = workspace_payload.get("schema_version", LEGACY_SCHEMA_VERSION)
    if version == CURRENT_SCHEMA_VERSION:
        return workspace_payload, investigation_payloads, False
    if version != LEGACY_SCHEMA_VERSION:
        raise ValueError(f"unsupported focused workspace schema version: {version}")

    workspace = _collapse_hypotheses(deepcopy(workspace_payload))
    investigations = {
        investigation_id: _collapse_hypotheses(deepcopy(payload))
        for investigation_id, payload in investigation_payloads.items()
    }
    workspace["schema_version"] = CURRENT_SCHEMA_VERSION

    for version_payload in workspace.get("hypothesis_versions", []):
        sources = version_payload.setdefault("step_sources", {})
        sources.setdefault("hypothesis", version_payload.get("id"))

    return workspace, investigations, True
