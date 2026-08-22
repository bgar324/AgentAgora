import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from agora.core.errors import ConfigurationError

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SEMANTIC_SCHOLAR_BASE_URL = "https://api.semanticscholar.org"


def _env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}") from exc


def _env_list(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def _env_optional_float(name: str) -> float | None:
    raw = _env(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}") from exc


@dataclass
class OpenAISettings:
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    max_retries: int = 2
    timeout: float = 180.0


@dataclass
class OpenRouterSettings:
    api_key: str | None = field(default=None, repr=False)
    base_url: str = OPENROUTER_BASE_URL
    max_retries: int = 2
    timeout: float = 120.0
    provider_sort: str | None = "throughput"
    models: list[str] = field(default_factory=list)
    app_url: str | None = None
    app_title: str | None = "agora"


@dataclass
class SemanticScholarSettings:
    api_key: str | None = field(default=None, repr=False)
    base_url: str = SEMANTIC_SCHOLAR_BASE_URL
    timeout: float = 60.0
    min_request_interval: float = 1.5
    max_retries: int = 5
    retry_threshold_s: float = 90.0
    cache_dir: Path | None = Path(".cache/s2")
    cache_ttl: float | None = None


@dataclass
class SupabaseSettings:
    url: str | None = None
    secret_key: str | None = field(default=None, repr=False)


@dataclass
class PhaseModel:
    model: str
    temperature: float
    max_tokens: int


@dataclass
class ModelSettings:
    brief: PhaseModel = field(
        default_factory=lambda: PhaseModel("openai/gpt-4o-mini", 1.0, 4_000)
    )
    panel: PhaseModel = field(
        default_factory=lambda: PhaseModel("openai/gpt-4o-mini", 0.0, 4_000)
    )
    deliberation: PhaseModel = field(
        default_factory=lambda: PhaseModel("openai/gpt-4o-mini", 0.0, 800)
    )


@dataclass
class ServerSettings:
    data_dir: Path = Path("artifacts")
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    persistence_backend: Literal["sqlite", "supabase"] = "sqlite"
    proxy_token: str | None = field(default=None, repr=False)
    log_level: str = "INFO"


@dataclass
class Settings:
    openai: OpenAISettings = field(default_factory=OpenAISettings)
    openrouter: OpenRouterSettings = field(default_factory=OpenRouterSettings)
    semantic_scholar: SemanticScholarSettings = field(
        default_factory=SemanticScholarSettings
    )
    supabase: SupabaseSettings = field(default_factory=SupabaseSettings)
    models: ModelSettings = field(default_factory=ModelSettings)
    server: ServerSettings = field(default_factory=ServerSettings)


def load_settings() -> Settings:
    load_dotenv(override=False)
    persistence_value = _env("AGORA_PERSISTENCE") or "sqlite"
    if persistence_value not in {"sqlite", "supabase"}:
        raise ConfigurationError(
            "AGORA_PERSISTENCE must be either 'sqlite' or 'supabase'"
        )
    persistence_backend: Literal["sqlite", "supabase"] = (
        "supabase" if persistence_value == "supabase" else "sqlite"
    )
    supabase_url = _env("SUPABASE_URL")
    supabase_secret_key = _env("SUPABASE_SECRET_KEY")
    proxy_token = _env("AGORA_PROXY_TOKEN")
    if persistence_backend == "supabase" and (
        not supabase_url or not supabase_secret_key
    ):
        raise ConfigurationError(
            "Supabase persistence requires SUPABASE_URL and SUPABASE_SECRET_KEY"
        )
    if persistence_backend == "supabase" and not proxy_token:
        raise ConfigurationError(
            "Supabase deployment requires AGORA_PROXY_TOKEN"
        )


    return Settings(
        openai=OpenAISettings(
            api_key=_env("OPENAI_API_KEY"),
            base_url=_env("OPENAI_BASE_URL"),
            max_retries=_env_int("OPENAI_MAX_RETRIES", 2),
            timeout=_env_float("OPENAI_TIMEOUT", 180.0),
        ),
        openrouter=OpenRouterSettings(
            api_key=_env("OPENROUTER_API_KEY"),
            base_url=_env("OPENROUTER_BASE_URL") or OPENROUTER_BASE_URL,
            max_retries=_env_int("OPENROUTER_MAX_RETRIES", 2),
            timeout=_env_float("OPENROUTER_TIMEOUT", 120.0),
            provider_sort=_env("OPENROUTER_PROVIDER_SORT") or "throughput",
            models=_env_list("OPENROUTER_MODELS"),
            app_url=_env("OPENROUTER_APP_URL"),
            app_title=_env("OPENROUTER_APP_TITLE") or "agora",
        ),
        supabase=SupabaseSettings(
            url=supabase_url,
            secret_key=supabase_secret_key,
        ),
        semantic_scholar=SemanticScholarSettings(
            api_key=_env("SEMANTIC_SCHOLAR_API_KEY"),
            base_url=_env("SEMANTIC_SCHOLAR_BASE_URL") or SEMANTIC_SCHOLAR_BASE_URL,
            timeout=_env_float("SEMANTIC_SCHOLAR_TIMEOUT", 60.0),
            min_request_interval=_env_float(
                "SEMANTIC_SCHOLAR_MIN_REQUEST_INTERVAL", 1.5
            ),
            max_retries=_env_int("SEMANTIC_SCHOLAR_MAX_RETRIES", 5),
            retry_threshold_s=_env_float("SEMANTIC_SCHOLAR_RETRY_THRESHOLD_S", 90.0),
            cache_dir=Path(_env("SEMANTIC_SCHOLAR_CACHE_DIR") or ".cache/s2"),
            cache_ttl=_env_optional_float("SEMANTIC_SCHOLAR_CACHE_TTL"),
        ),
        models=ModelSettings(
            brief=PhaseModel(
                model=_env("AGORA_BRIEF_MODEL") or "openai/gpt-4o-mini",
                temperature=_env_float("AGORA_BRIEF_TEMPERATURE", 1.0),
                max_tokens=_env_int("AGORA_BRIEF_MAX_TOKENS", 4_000),
            ),
            panel=PhaseModel(
                model=_env("AGORA_PANEL_MODEL") or "openai/gpt-4o-mini",
                temperature=_env_float("AGORA_PANEL_TEMPERATURE", 0.0),
                max_tokens=_env_int("AGORA_PANEL_MAX_TOKENS", 4_000),
            ),
            deliberation=PhaseModel(
                model=(_env("AGORA_DELIBERATION_MODEL") or "openai/gpt-4o-mini"),
                temperature=_env_float("AGORA_DELIBERATION_TEMPERATURE", 0.0),
                max_tokens=_env_int("AGORA_DELIBERATION_MAX_TOKENS", 800),
            ),
        ),
        server=ServerSettings(
            data_dir=Path(_env("AGORA_DATA_DIR") or "artifacts"),
            cors_origins=(_env_list("AGORA_CORS_ORIGINS") or ["http://localhost:3000"]),
            persistence_backend=persistence_backend,
            proxy_token=proxy_token,
            log_level=_env("AGORA_LOG_LEVEL") or "INFO",
        ),
    )
