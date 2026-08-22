"""Optional shared-token gate for the public deployment API."""

from __future__ import annotations

import secrets

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

PROXY_TOKEN_HEADER = "x-agora-proxy-token"
PUBLIC_PATHS = frozenset({"/api/v1/focused/health"})


class ProxyTokenMiddleware:
    def __init__(self, app: ASGIApp, *, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            self.token
            and scope["type"] == "http"
            and str(scope.get("path", "")).startswith("/api/v1/")
            and scope.get("path") not in PUBLIC_PATHS
        ):
            supplied = Headers(scope=scope).get(PROXY_TOKEN_HEADER)
            if not supplied or not secrets.compare_digest(supplied, self.token):
                response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
