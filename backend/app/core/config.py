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
    API_TITLE: str = "Book Translator API"
    API_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:5173"

    # --- Database ---
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://bt:bt@localhost:5432/book-translator",
        description="Async SQLAlchemy URL used by the app.",
    )

    # --- Storage ---
    UPLOAD_DIR: Path = Path("/data/uploads")
    MAX_UPLOAD_SIZE_MB: int = 50

    # --- LLM providers ---
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-3.1-flash-lite-preview"
    # Optional: override per-million-token USD prices used in glossary cost estimates.
    GEMINI_INPUT_PRICE_USD_PER_MTOK: float | None = None
    GEMINI_OUTPUT_PRICE_USD_PER_MTOK: float | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
