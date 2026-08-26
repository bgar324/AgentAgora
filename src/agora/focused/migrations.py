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


# Turn vocabulary that predates the canonical answer/reply/support/challenge
# contribution kinds. Production v5 (main) only wrote the kept kinds, but
# intermediate development snapshots also wrote these values.
_LEGACY_TURN_KINDS = {"response": "reply", "position": "answer", "qualify": "reply"}
_LEGACY_TURN_RELATIONS = {"position": "answer", "qualify": "reply", "response": "reply"}


def _migrate_turn(turn: Any) -> None:
    if not isinstance(turn, dict):
        return
    kind = turn.get("kind")
    if kind in _LEGACY_TURN_KINDS:
        turn["kind"] = _LEGACY_TURN_KINDS[kind]
    relation = turn.get("relation")
    if relation in _LEGACY_TURN_RELATIONS:
        turn["relation"] = _LEGACY_TURN_RELATIONS[relation]


def _facet_to_facets(value: Any) -> None:
    """Rewrite a single-facet payload (`facet: str`) to `facets: [str]`."""
    if not isinstance(value, dict):
        return
    facet = value.pop("facet", None)
    if facet is not None and not value.get("facets"):
        value["facets"] = [facet]


def _merged_thread_verdict(verdicts: list[Any]) -> dict[str, Any] | None:
    """Collapse v5 per-facet verdicts into one Thread-level verdict.

    The first verdict's scalar finding wins; facets and the collection
    fields merge. The archived pre-migration payload keeps the originals.
    """
    shaped = [item for item in verdicts if isinstance(item, dict)]
    if not shaped:
        return None
    primary = dict(shaped[0])
    facets: list[Any] = []
    for item in shaped:
        for facet in [item.get("facet"), *item.get("facets", [])]:
            if facet is not None and facet not in facets:
                facets.append(facet)
    for field in ("supporting", "contested_by"):
        merged = [name for item in shaped for name in item.get(field, []) or []]
        primary[field] = list(dict.fromkeys(merged))
    positions: dict[str, Any] = {}
    evidence: dict[str, list[Any]] = {}
    for item in shaped:
        positions.update(item.get("positions", {}) or {})
        for name, citations in (item.get("evidence", {}) or {}).items():
            merged_citations = [*evidence.get(name, []), *citations]
            evidence[name] = list(dict.fromkeys(merged_citations))
    primary["positions"] = positions
    primary["evidence"] = evidence
    primary.pop("facet", None)
    primary["facets"] = facets
    return primary


def _migrate_round(round_payload: Any) -> None:
    if not isinstance(round_payload, dict):
        return
    for turn in round_payload.get("turns", []) or []:
        _migrate_turn(turn)
    verdicts = round_payload.pop("verdicts", None)
    if isinstance(verdicts, list) and round_payload.get("verdict") is None:
        round_payload["verdict"] = _merged_thread_verdict(verdicts)
    else:
        _facet_to_facets(round_payload.get("verdict"))
    for check in round_payload.get("moderator_checks", []) or []:
        if isinstance(check, dict):
            _facet_to_facets(check.get("verdict"))
    resolution = round_payload.get("resolution")
    if isinstance(resolution, dict):
        for key in ("consensus_points", "disagreement_points", "unsettled_points"):
            for point in resolution.get(key, []) or []:
                _facet_to_facets(point)


def _migrate_deliberation(deliberation: Any) -> None:
    if not isinstance(deliberation, dict):
        return
    for round_payload in deliberation.get("rounds", []) or []:
        _migrate_round(round_payload)
    for turn in deliberation.get("chat", []) or []:
        _migrate_turn(turn)
    for completion in deliberation.get("completion_history", []) or []:
        if not isinstance(completion, dict):
            continue
        for round_payload in completion.get("rounds", []) or []:
            _migrate_round(round_payload)
        for turn in completion.get("chat", []) or []:
            _migrate_turn(turn)


def migrate_v5_payloads(
    workspace_payload: dict[str, Any],
    investigation_payloads: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], bool]:
    """Transform one persisted v5 aggregate into the strict v6 shape.

    Collapses four-part hypotheses to the scalar form and rewrites round
    payloads (turn vocabulary, per-facet verdicts, single-facet points)
    onto the Thread-centered v6 contracts.
    """

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
    for payload in investigations.values():
        for deliberation in payload.get("deliberations", []) or []:
            _migrate_deliberation(deliberation)
    workspace["schema_version"] = CURRENT_SCHEMA_VERSION

    for version_payload in workspace.get("hypothesis_versions", []):
        sources = version_payload.setdefault("step_sources", {})
        sources.setdefault("hypothesis", version_payload.get("id"))

    return workspace, investigations, True
