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
    #
    # ``alpaca_api_key`` / ``alpaca_api_secret`` are dev / single-account
    # convenience only (e.g. local seed/smoke scripts). Per-user Alpaca access
    # uses per-user API keys entered at connect time and stored encrypted per
    # ``broker_connections`` row — the portfolio-sync path no longer reads
    # ``alpaca_api_secret``.
    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None
    # Paper-trading base URL used by the per-user adapter.
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    # Currently unused — reserved for a future real-Alpaca-OAuth follow-up
    # (Pattern 1). Not used by the per-user-keys path.
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

    # News + sentiment pipeline (m2-12).
    #
    # GNews free tier caps at 100 req/day; we track usage in Redis and fall
    # back to RSS when the budget is hit. Missing key → RSS-only path.
    gnews_api_key: str | None = None

    # Reddit (PRAW) social-sentiment source — fully degradable (20% weight).
    # When either ID/secret is None, the sentiment engine redistributes the
    # social weight to news + macro per AC #3.
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "investiq-sentiment/0.1 (by /u/investiq_bot)"

    # --- MODE 4: AI-Enhanced Analysis (M3-17) ---------------------------------
    # AI analysis is OFF by default. When enabled, a Celery task in the
    # ``ai_analysis`` queue runs per recommendation. Shadow mode is the Phase 1
    # safety gate: outputs are logged but not blended into the composite.
    # Disabling shadow mode in production requires an explicit legal-review
    # flag (``ai_analysis_legal_review_approved=true``); otherwise the API
    # layer forces shadow_mode back on (MODE 4 AC #2).
    ai_analysis_enabled: bool = False
    ai_analysis_shadow_mode: bool = True
    ai_analysis_weight: float = 0.20  # capped by MAX_AI_WEIGHT=0.30 in code
    ai_analysis_legal_review_approved: bool = False
    ai_analysis_provider: str = "claude_cli"  # claude_cli | api
    ai_analysis_timeout_s: float = 30.0
    anthropic_api_key: str | None = None

    # --- Recommendation staleness (M4-23) -----------------------------------
    # Age thresholds (in hours) used by backend.app.intelligence.staleness.
    # Defaults: <1h fresh, <6h aging (-5% confidence), <24h stale (-15%),
    # >=24h suppressed. Overridable per-env for backtests / staging.
    staleness_fresh_hours: float = 1.0
    staleness_aging_hours: float = 6.0
    staleness_stale_hours: float = 24.0

    # --- MODE E: Risk Guardian & Notifications (M3-20) ------------------------
    # Expo push-service access token used by the dispatcher to call the
    # authenticated Expo Push API. When unset, push delivery is skipped and
    # notifications remain in-app only.
    expo_push_access_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
