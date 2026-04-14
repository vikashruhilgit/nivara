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

    # Broker token encryption (AES-256-GCM).
    #
    # Comma-separated list of URL-safe base64-encoded 32-byte master keys;
    # primary key is first, older keys afterwards for decrypt-only fallback
    # during rotation. Generate:
    # ``python -c "import os, base64;
    # print(base64.urlsafe_b64encode(os.urandom(32)).decode())"``.
    master_encryption_key: str | None = None

    # Alpaca (paper trading by default — never point MVP at live).
    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_oauth_client_id: str | None = None
    alpaca_oauth_redirect_uri: str = "http://localhost:8000/api/auth/broker/alpaca/callback"

    # Zerodha (stub in MVP).
    zerodha_api_key: str | None = None
    zerodha_api_secret: str | None = None

    # FRED (Federal Reserve Economic Data) — primary FX source for USD/INR.
    # Register a free key at https://fred.stlouisfed.org/docs/api/api_key.html.
    # When unset, the FX refresh pipeline falls back to ECB.
    fred_api_key: str | None = None

    # Corporate actions / OHLCV adjustment tunables.
    # Cap the retroactive adjustment window to keep bulk UPDATEs bounded
    # (see m2-11 risk assessment).
    corp_action_adjust_history_days: int = 365 * 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
