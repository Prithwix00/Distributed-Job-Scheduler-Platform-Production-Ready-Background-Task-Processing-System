"""Application configuration loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    app_name: str = "Distributed Job Scheduler"
    environment: str = "development"

    # Database. Postgres in production, SQLite is supported for local dev / tests.
    database_url: str = "postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler"

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 24

    # Worker / scheduler tuning
    worker_poll_interval_seconds: float = 1.0
    worker_heartbeat_interval_seconds: float = 5.0
    worker_claim_batch_size: int = 5
    heartbeat_timeout_seconds: int = 30
    scheduler_tick_seconds: float = 2.0

    # API defaults
    default_page_size: int = 25
    max_page_size: int = 200

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
