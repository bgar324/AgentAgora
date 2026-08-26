"""Shared fixtures for focused-panel persistence and migration tests."""

from __future__ import annotations

from typing import Any

import pytest

_LEGACY_HYPOTHESIS = {
    "problem": "legacy problem",
    "previous_work": "legacy previous work",
    "reasoning": "legacy reasoning",
    "hypothesis": "H legacy before",
}


def _legacy_v5_round() -> dict[str, Any]:
    """One deliberation round exactly as schema v5 persisted it.

    Production v5 (main) wrote per-facet ``verdicts`` and single-facet
    resolution points; intermediate development snapshots additionally
    wrote pre-canonical turn vocabulary (``response``/``qualify``) and
    facet-shaped moderator checks. The round covers both.
    """
    return {
        "n": 1,
        "lead_iid": 1,
        "participant_iids": [1, 2],
        "facets": ["scope"],
        "turns": [
            {
                "id": 1,
                "agent_iid": 1,
                "agent_label": "Lead",
                "role": "lead",
                "kind": "open",
                "facet": "scope",
                "text": "Opening position.",
                "citations": ["p1"],
            },
            {
                "id": 2,
                "agent_iid": 2,
                "agent_label": "Other",
                "role": "other",
                "kind": "response",
                "relation": "qualify",
                "facet": "scope",
                "text": "Qualified response.",
                "citations": [],
            },
        ],
        "verdicts": [
            {
                "facet": "scope",
                "status": "consensus",
                "summary": "Shared boundary.",
                "consensus": "Adults in inpatient care.",
                "supporting": ["Lead", "Other"],
                "positions": {"Lead": "Boundary A", "Other": "Boundary A"},
                "evidence": {"Lead": ["p1"]},
            },
            {
                "facet": "significance",
                "status": "unsettled",
                "summary": "Downstream stakes remain open.",
                "unsettled": "Long-term harms unmeasured.",
                "evidence": {"Lead": ["p1"], "Other": ["p2"]},
            },
        ],
        "moderator_checks": [
            {
                "exchange_n": 1,
                "proposed_shared_ground": "Adults in inpatient care.",
                "verdict": {
                    "facet": "scope",
                    "status": "consensus",
                    "summary": "Shared boundary.",
                    "consensus": "Adults in inpatient care.",
                },
                "assents": [
                    {
                        "agent_iid": 2,
                        "agent_label": "Other",
                        "decision": "accept",
                        "reason": "Accepted as stated.",
                    }
                ],
                "unanimous": True,
            }
        ],
        "resolution": {
            "summary": "The panel agreed on the boundary.",
            "consensus_points": [
                {
                    "facet": "scope",
                    "text": "Adults in inpatient care.",
                    "rationale": "Both perspectives accepted it.",
                    "citations": ["p1"],
                }
            ],
            "disagreement_points": [],
            "unsettled_points": [
                {
                    "facet": "significance",
                    "text": "Long-term harms unmeasured.",
                }
            ],
        },
        "reflections": [],
        "metrics": None,
        "completed": True,
        "hypothesis_before": dict(_LEGACY_HYPOTHESIS),
        "hypothesis_proposal": None,
        "hypothesis_decision": "accepted",
    }


def _legacy_v5_deliberation(lead_perspective_id: str) -> dict[str, Any]:
    return {
        "id": "delib-legacy",
        "agent_iids": [1, 2],
        "lead_perspective_id": lead_perspective_id,
        "baseline_hypothesis": dict(_LEGACY_HYPOTHESIS),
        "rounds": [_legacy_v5_round()],
        "chat": [
            {
                "id": 9,
                "agent_label": "You",
                "role": "user",
                "kind": "user",
                "text": "What changed?",
                "citations": [],
            }
        ],
        "completion_history": [
            {
                "reason": "restarted",
                "round_count": 1,
                "chat_count": 0,
                "agent_iids": [1, 2],
                "rounds": [_legacy_v5_round()],
                "chat": [],
            }
        ],
    }


@pytest.fixture
def legacy_v5_deliberation():
    return _legacy_v5_deliberation
