"""Central configuration. All values overridable via environment / .env file."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---------------- App ----------------
    app_name: str = "Job Matching Agent"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    backend_url: str = "http://localhost:8000"

    # ---------------- Database ----------------
    database_url: str = "sqlite:///./data/job_agent.db"

    # ---------------- OpenRouter / LLM ----------------
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Comma separated fallback chain, tried left to right.
    openrouter_models: str = (
        "meta-llama/llama-3.3-70b-instruct:free,"
        "deepseek/deepseek-chat-v3-0324:free,"
        "google/gemma-3-27b-it:free,"
        "qwen/qwen-2.5-72b-instruct:free,"
        "mistralai/mistral-small-3.2-24b-instruct:free"
    )
    llm_timeout_seconds: int = 90
    llm_max_tokens: int = 1400
    llm_temperature: float = 0.3

    # ---------------- Embeddings ----------------
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_fallback_enabled: bool = True

    # ---------------- Scraping ----------------
    scraper_headless: bool = True
    scraper_timeout_ms: int = 45000
    scraper_max_retries: int = 2
    scraper_min_delay_ms: int = 800
    scraper_max_delay_ms: int = 2200
    scraper_max_results_per_source: int = 20
    scraper_proxy: str = ""
    scraper_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    enabled_sources: str = "wuzzuf,bayt,tanqeeb,indeed,linkedin"

    # ---------------- Alerts / Scheduler ----------------
    scheduler_enabled: bool = True
    alert_interval_hours: int = 6

    # ---------------- SMTP ----------------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    @property
    def model_chain(self) -> List[str]:
        return [m.strip() for m in self.openrouter_models.split(",") if m.strip()]

    @property
    def sources(self) -> List[str]:
        return [s.strip().lower() for s in self.enabled_sources.split(",") if s.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from_email)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
