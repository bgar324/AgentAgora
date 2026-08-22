from fastapi import FastAPI
from fastapi.testclient import TestClient

from agora.api.proxy_auth import ProxyTokenMiddleware


def app_with_token(token: str | None) -> TestClient:
    app = FastAPI()
    app.add_middleware(ProxyTokenMiddleware, token=token)

    @app.get("/api/v1/focused/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/focused/workspaces/example")
    async def workspace():
        return {"id": "example"}

    return TestClient(app)


def test_proxy_token_blocks_direct_api_requests() -> None:
    client = app_with_token("shared-secret")

    missing = client.get("/api/v1/focused/workspaces/example")
    wrong = client.get(
        "/api/v1/focused/workspaces/example",
        headers={"x-agora-proxy-token": "wrong"},
    )
    allowed = client.get(
        "/api/v1/focused/workspaces/example",
        headers={"x-agora-proxy-token": "shared-secret"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json() == {"detail": "Unauthorized"}
    assert allowed.status_code == 200


def test_proxy_token_keeps_health_check_public() -> None:
    assert app_with_token("shared-secret").get(
        "/api/v1/focused/health"
    ).status_code == 200


def test_proxy_token_is_disabled_for_local_development() -> None:
    assert app_with_token(None).get(
        "/api/v1/focused/workspaces/example"
    ).status_code == 200
