import os
import tempfile

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")
os.environ.setdefault("AGORA_DATA_DIR", tempfile.mkdtemp(prefix="agora-api-test-"))

from fastapi.testclient import TestClient

from agora.app import app


def test_focused_condition_is_runnable_from_standalone_app() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/focused/health").json() == {"status": "ok"}

        focused = client.post(
            "/api/v1/focused/workspaces",
            json={
                "problem": "Should antibiotics be prescribed broadly?",
                "research_questions": [],
                "demo": True,
            },
        )
        assert focused.status_code == 200
        workspace_view = focused.json()
        focused_state = workspace_view["active"]
        focused_id = focused_state["id"]
        focused_state = client.post(
            f"/api/v1/focused/sessions/{focused_id}/suggest-queries"
        ).json()["active"]
        selected = [item["query"] for item in focused_state["suggested_queries"][:3]]
        searched = client.post(
            f"/api/v1/focused/sessions/{focused_id}/search",
            json={"queries": selected},
        )
        assert searched.status_code == 200
        searched_state = searched.json()["active"]
        assert searched_state["clusters"]
        assert {item["facet"] for item in searched_state["clusters"][0]["facets"]} == {
            "scope",
            "explanation",
            "approach",
            "significance",
        }
