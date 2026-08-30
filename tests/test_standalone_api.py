import os
import subprocess
import sys
import tempfile
import textwrap

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


def test_focused_demo_is_runnable_without_api_keys() -> None:
    script = textwrap.dedent(
        """
        import os
        import sys
        import tempfile

        os.environ.setdefault("AGORA_DATA_DIR", tempfile.mkdtemp(prefix="agora-api-test-"))
        for name in (
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "SEMANTIC_SCHOLAR_API_KEY",
        ):
            assert name not in os.environ


        from fastapi.testclient import TestClient
        from agora.focused_app import app

        with TestClient(app) as client:
            assert client.get("/api/v1/focused/health").json() == {"status": "ok"}
            focused = client.post(
                "/api/v1/focused/workspaces",
                json={
                    "problem": "Should antibiotics be prescribed broadly?",
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
            state = searched.json()["active"]
            assert state["papers"]
            assert "clusters" not in state
            built = client.post(
                f"/api/v1/focused/sessions/{state['id']}/perspectives",
                json={"paper_id": state["papers"][0]["id"]},
            )
            assert built.status_code == 200
            perspective = built.json()["active"]["perspectives"][0]
            assert perspective["anchor_paper_id"] == state["papers"][0]["id"]
            assert "facets" not in perspective
            assert "torch" not in sys.modules
        """
    )
    env = os.environ.copy()
    env["AGORA_PERSISTENCE"] = "sqlite"
    env["PYTHON_DOTENV_DISABLED"] = "1"
    for name in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "SEMANTIC_SCHOLAR_API_KEY",
    ):
        env.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
