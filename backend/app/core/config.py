"""Application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables.

    Each layer (API, DB, parsing) reads only what it needs from this
    object; we never sprinkle os.environ.get() across the codebase.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- API ---
    API_TITLE: str = "Mneme API"
    API_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:5177"

    # --- Database ---
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://bt:bt@localhost:5432/book-translator",
        description="Async SQLAlchemy URL used by the app.",
    )

    # --- Storage ---
    UPLOAD_DIR: Path = Path("/data/uploads")
    MAX_UPLOAD_SIZE_MB: int = 50

    # If True, books stuck in `*_extraction_status="running"` from a dead worker
    # (e.g. process restart) are marked failed on API startup. Disable in multi-replica
    # deployments where another instance may legitimately be running extraction.
    RECONCILE_STALE_EXTRACTIONS_ON_STARTUP: bool = True

    # --- LLM providers ---
    GEMINI_API_KEY: str | None = None
    # Needed only when a translation stage uses an OpenAI model (gpt-…).
    OPENAI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-3.1-flash-lite-preview"
    # Fragment translation (Step 5). Each stage falls back to TRANSLATION_MODEL,
    # then to GEMINI_MODEL, so one setting is enough to start.
    TRANSLATION_MODEL: str | None = None
    TRANSLATION_FAITHFUL_MODEL: str | None = None
    TRANSLATION_LINE_EDIT_MODEL: str | None = None
    TRANSLATION_POLISH_MODEL: str | None = None
    # How many fragments are translated at the same time.
    TRANSLATION_CONCURRENCY: int = 4
    # Thinking per stage: "minimal" | "low" | "medium" | "high", or empty for
    # the model's default. Thinking is billed as output and is most of the
    # cost. Default is "high" everywhere, for the best translation: on
    # chapter 5 of Zaplataczka, low/medium/low halved the cost but let
    # added intensity and a lost stammer through.
    TRANSLATION_THINKING_FAITHFUL: str | None = "high"
    TRANSLATION_THINKING_LINE_EDIT: str | None = "high"
    TRANSLATION_THINKING_POLISH: str | None = "high"
    # Cache the shared prompt prefix (rules, style sheet, glossary) per run.
    TRANSLATION_CACHE: bool = True
    # Optional: override per-million-token USD prices used in glossary cost estimates.
    GEMINI_INPUT_PRICE_USD_PER_MTOK: float | None = None
    GEMINI_OUTPUT_PRICE_USD_PER_MTOK: float | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
