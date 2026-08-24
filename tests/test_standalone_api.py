import os
import subprocess
import sys
import tempfile
import textwrap

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")
os.environ.setdefault("AGORA_DATA_DIR", tempfile.mkdtemp(prefix="agora-api-test-"))



def test_focused_app_does_not_load_legacy_ml_stack() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import agora.focused_app; "
                "assert 'torch' not in sys.modules; "
                "assert 'sklearn' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_focused_condition_is_runnable_from_standalone_app() -> None:
    script = textwrap.dedent(
        """
        import os
        import sys
        import tempfile

        os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
        os.environ.setdefault("AGORA_DATA_DIR", tempfile.mkdtemp(prefix="agora-api-test-"))

        from fastapi.testclient import TestClient
        from agora.focused_app import app

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
            state = focused.json()["active"]
            state = client.post(
                f"/api/v1/focused/sessions/{state['id']}/suggest-queries"
            ).json()["active"]
            selected = [item["query"] for item in state["suggested_queries"][:3]]
            searched = client.post(
                f"/api/v1/focused/sessions/{state['id']}/search",
                json={"queries": selected},
            )
            assert searched.status_code == 200
            clusters = searched.json()["active"]["clusters"]
            assert clusters
            assert {item["facet"] for item in clusters[0]["facets"]} == {
                "scope",
                "explanation",
                "approach",
                "significance",
            }
            assert "torch" not in sys.modules
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
