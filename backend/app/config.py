"""Application settings, loaded from environment variables / .env."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# backend/ folder: .env and the default SQLite file live here, whatever folder
# the server is started from (terminal, Claude Code preview, Render).
BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "MandiLink"
    environment: str = "development"
    jwt_secret: str = "change-me-in-production-please-32+chars"
    jwt_ttl_hours: int = 24 * 14
    database_url: str = "sqlite:///./mandilink.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Nexconn (server side only; the App Secret never reaches the browser) ---
    nexconn_app_key: str = ""
    nexconn_app_secret: str = ""
    # Data-center API host from the Nexconn Console (Singapore DC shown as default).
    nexconn_api_host: str = "https://api.sg-light-api.com"
    nexconn_backup_api_host: str = ""

    # --- AI ---
    # llm_provider: "gemini" | "openai" (any OpenAI-compatible endpoint, e.g. Groq) | "none"
    llm_provider: str = "none"
    gemini_api_key: str = ""
    # Flash-Lite answers chat translations in ~1.5 s (3.8 Flash was slow and often
    # overloaded with 503s). The "-latest" alias is tried if the main model fails.
    # gemini-2.0-flash was shut down on 2026-06-01: never use it.
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_model: str = "gemini-flash-lite-latest"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 20.0

    # --- Market prices (data.gov.in Agmarknet "Current Daily Price" dataset) ---
    datagov_api_key: str = ""
    datagov_resource_id: str = "9ef84268-d588-465a-a308-a864a43d0070"

    # --- Support desk bootstrap ---
    support_agent_pin: str = "2468"

    @property
    def nexconn_enabled(self) -> bool:
        return bool(self.nexconn_app_key and self.nexconn_app_secret)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
