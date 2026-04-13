"""Application configuration loaded from environment."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings sourced from .env / environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "InvestIQ API"
    environment: str = "development"
    debug: bool = True

    # Database
    database_url: str = "postgresql+asyncpg://investiq:investiq@postgres:5432/investiq"
    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Auth (bearer token, per TechSpec v1.3 direction)
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expires_minutes: int = 15
    refresh_token_expires_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
