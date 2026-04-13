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

    # Auth (bearer token pattern per CLAUDE.md / TechSpec v1.3).
    #
    # JWT access tokens are RS256-signed. Keys are loaded from PEM files on
    # disk (mounted via Docker secrets / volume in prod, generated via
    # scripts/generate_keys.sh in dev). Tests may override with inline PEMs
    # via the ``*_pem`` fields.
    jwt_algorithm: str = "RS256"
    jwt_kid: str = "dev"
    jwt_private_key_path: str | None = None
    jwt_public_key_path: str | None = None
    jwt_private_key_pem: str | None = None
    jwt_public_key_pem: str | None = None
    jwt_issuer: str = "investiq"
    jwt_audience: str = "investiq-mobile"
    access_token_expires_minutes: int = 15
    refresh_token_expires_days: int = 30

    # Argon2 password hashing (argon2-cffi) — low-cost defaults; tune per env.
    argon2_time_cost: int = 2
    argon2_memory_cost: int = 65536  # 64 MiB
    argon2_parallelism: int = 2

    # Defaults for JWT claims the ``users`` table does not yet carry.
    default_user_tier: str = "free"
    default_base_currency: str = "INR"


@lru_cache
def get_settings() -> Settings:
    return Settings()
