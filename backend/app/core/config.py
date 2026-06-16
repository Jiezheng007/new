from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Yuqing-Risk-MVP"
    secret_key: str = "dev-only-change-me"
    access_token_ttl_minutes: int = 480
    database_url: str = "sqlite:///./yuqing.db"
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin123"
    # Sentiment-analysis backend. Default switched to jieba_nlp in Phase 5.
    # keyword_nlp remains available as a deterministic baseline / fallback.
    # Valid values: "jieba_nlp", "keyword_nlp".
    nlp_provider: str = "jieba_nlp"
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 300
    scheduler_fetch_batch_limit: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
