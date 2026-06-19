"""Centralized config (env-driven via pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env once at import-time so subprocesses and tests get the same view.
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ROOT / ".env"), extra="ignore")

    # Notion
    notion_token: str | None = None
    notion_page_url: str = ""
    notion_max_depth: int = 3
    enable_public_notion_reader: bool = True

    # ASR
    asr_provider: str = "groq"  # groq | local
    groq_api_key: str | None = None

    # LLM
    MiniMax_api_key: str | None = None
    MiniMax_model: str = "M2.7"
    MiniMax_base_url: str = "https://api.MiniMax.com/v1"

    # Embeddings
    embed_model: str = "intfloat/multilingual-e5-small"
    embed_preload: bool = False

    # Retrieval
    enable_llm_rerank: bool = False

    # App
    app_password: str | None = None
    db_path: str = "./data/askmynotion.db"
    host: str = "127.0.0.1"
    port: int = 8000
    disable_instagram_fetch: bool = False
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def _settings() -> Settings:
    return Settings()


# Convenience global (re-importing won't re-instantiate).
settings = _settings()
