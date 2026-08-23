from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI

from agora.api.focused import focused_router
from agora.api.proxy_auth import ProxyTokenMiddleware
from agora.client.s2 import SemanticScholarClient
from agora.config.settings import load_settings
from agora.core.log import configure_logging
from agora.db.vector import EMBEDDING_MODEL, embed_texts
from agora.focused.persistence import FocusedPersistence
from agora.focused.provider import FocusedProvider
from agora.focused.retrieval import FocusedSemanticScholar
from agora.focused.service import FocusedPanelService
from agora.focused.supabase_persistence import SupabaseFocusedPersistence
from agora.llm.providers.openrouter import OpenRouterProvider

settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.server.log_level)
    settings.server.data_dir.mkdir(parents=True, exist_ok=True)

    focused_db: sqlite3.Connection | None = None
    if settings.server.persistence_backend == "supabase":
        persistence = SupabaseFocusedPersistence(
            settings.supabase.url,
            settings.supabase.secret_key,
        )
    else:
        focused_db = sqlite3.connect(
            settings.server.data_dir / "agora.db",
            check_same_thread=False,
        )
        focused_db.row_factory = sqlite3.Row
        persistence = FocusedPersistence(focused_db)

    openai_client = AsyncOpenAI(api_key=settings.openai.api_key)
    s2_client = SemanticScholarClient(settings.semantic_scholar)

    async def embed(texts: list[str]):
        return await embed_texts(texts, client=openai_client)

    provider = (
        FocusedProvider(
            llm=OpenRouterProvider(settings.openrouter),
            phase=settings.models.deliberation,
        )
        if settings.openrouter.api_key
        else None
    )
    app.state.settings = settings
    app.state.focused_provider = provider
    app.state.focused = FocusedPanelService(
        provider=provider,
        embedder=embed,
        embedding_model=EMBEDDING_MODEL,
        s2=FocusedSemanticScholar(s2_client),
        persistence=persistence,
    )

    yield

    if provider is not None:
        await provider.close()
    await s2_client.close()
    await openai_client.close()
    if focused_db is not None:
        focused_db.close()


app = FastAPI(title="Hypothesis Studio", lifespan=lifespan)
app.add_middleware(ProxyTokenMiddleware, token=settings.server.proxy_token)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(focused_router, prefix="/api/v1")
