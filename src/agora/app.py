# ruff: noqa: I001
from contextlib import asynccontextmanager

import numpy as _numpy  # noqa: F401 — must load before dspy's lazy numpy alias
import dspy
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI

from agora.api.focused import focused_router
from agora.api.proxy_auth import ProxyTokenMiddleware
from agora.api.router import router
from agora.client.s2 import SemanticScholarClient
from agora.config.settings import load_settings
from agora.core.log import configure_logging
from agora.db.store import connect
from agora.db.vector import EMBEDDING_MODEL, embed_texts
from agora.focused.provider import FocusedProvider
from agora.focused.retrieval import FocusedSemanticScholar
from agora.focused.persistence import FocusedPersistence
from agora.focused.supabase_persistence import SupabaseFocusedPersistence
from agora.focused.service import FocusedPanelService
from agora.llm.providers.openai import OpenAIProvider
from agora.workflow.run import Runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    configure_logging(settings.server.log_level)
    settings.server.data_dir.mkdir(parents=True, exist_ok=True)
    dspy.configure_cache(
        disk_cache_dir=str(settings.server.data_dir / ".cache" / "dspy")
    )

    db = connect(settings.server.data_dir / "agora.db")
    focused_db = None
    if settings.server.persistence_backend == "supabase":
        focused_persistence = SupabaseFocusedPersistence(
            settings.supabase.url,
            settings.supabase.secret_key,
        )
    else:
        focused_db = connect(settings.server.data_dir / "agora.db")
        focused_persistence = FocusedPersistence(focused_db)
    openai_client = AsyncOpenAI(api_key=settings.openai.api_key)
    s2_client = SemanticScholarClient(settings.semantic_scholar)

    async def embed(texts):
        return await embed_texts(texts, client=openai_client)

    app.state.settings = settings
    app.state.corpus_cache = {}
    app.state.runner = Runner(
        db=db,
        settings=settings,
        embedder=embed,
        s2_client=s2_client,
    )
    focused_provider = None
    if settings.openai.api_key:
        focused_provider = FocusedProvider(
            llm=OpenAIProvider(settings.openai),
            models=settings.focused_models,
        )
    focused_s2 = FocusedSemanticScholar(s2_client)
    app.state.focused_provider = focused_provider
    app.state.focused = FocusedPanelService(
        provider=focused_provider,
        embedder=embed,
        embedding_model=EMBEDDING_MODEL,
        s2=focused_s2,
        persistence=focused_persistence,
    )

    yield

    await app.state.runner.shutdown()
    if app.state.focused_provider is not None:
        await app.state.focused_provider.close()
    await s2_client.close()
    await openai_client.close()
    if focused_db is not None:
        focused_db.close()
    db.close()


app = FastAPI(title="AGORA", lifespan=lifespan)
settings = load_settings()
app.add_middleware(ProxyTokenMiddleware, token=settings.server.proxy_token)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(focused_router, prefix="/api/v1")
