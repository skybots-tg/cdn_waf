"""Application configuration"""
import logging
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import validator, PostgresDsn

logger = logging.getLogger(__name__)

# Placeholder values shipped in .env.example. Booting a production instance with
# any of these means anyone can forge tokens / decrypt data, so we refuse.
_INSECURE_SECRET_PREFIXES = ("change-me", "changeme", "test_", "test-", "secret")
_MIN_SECRET_LENGTH = 32


def _is_insecure_secret(value: str) -> bool:
    if not value or len(value) < _MIN_SECRET_LENGTH:
        return True
    lowered = value.lower()
    return any(lowered.startswith(prefix) for prefix in _INSECURE_SECRET_PREFIXES)


class Settings(BaseSettings):
    """Application settings"""

    # Application
    APP_NAME: str = "FlareCloud"
    APP_ENV: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    PUBLIC_URL: str = "http://localhost:8000"
    
    # Database
    DATABASE_URL: PostgresDsn
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    
    # Redis
    REDIS_URL: str
    REDIS_CACHE_DB: int = 1
    
    # Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str
    
    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 2880  # 48 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30  # 30 days

    # Internal node-to-control-plane shared secret (DNS/edge sync endpoints).
    NODE_SYNC_TOKEN: Optional[str] = None
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]
    
    @validator("CORS_ORIGINS", pre=True)
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v
    
    # ACME/Let's Encrypt
    ACME_EMAIL: str
    ACME_DIRECTORY_URL: str = "https://acme-staging-v02.api.letsencrypt.org/directory"  # Use staging for now to avoid rate limits
    ACME_ACCOUNT_KEY_PATH: str = "./data/acme_account_key.pem"  # Path to persistent account key
    
    # Edge Nodes
    EDGE_CONFIG_UPDATE_INTERVAL: int = 30
    
    # DNS / NS Verification
    EXPECTED_NS: str = "ns1.flarecloud.ru,ns2.flarecloud.ru"
    DNS_RESOLVERS: str = "8.8.8.8,8.8.4.4"

    # Analytics retention (days)
    ANALYTICS_RAW_LOGS_RETENTION: int = 30  # Raw request logs
    ANALYTICS_HOURLY_RETENTION: int = 90    # Hourly aggregated stats
    ANALYTICS_DAILY_RETENTION: int = 365    # Daily aggregated stats (1 year)
    
    # MaxMind GeoIP (for geo analytics on edge nodes)
    # Get free account at: https://www.maxmind.com/en/geolite2/signup
    MAXMIND_ACCOUNT_ID: Optional[str] = None
    MAXMIND_LICENSE_KEY: Optional[str] = None
    
    # Telegram Alerts
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    TELEGRAM_ALERT_USER_ID: Optional[str] = None  # User ID to tag on critical alerts

    # Health Check
    ORIGIN_HEALTH_CHECK_INTERVAL: int = 60  # seconds between health checks
    ORIGIN_UNHEALTHY_THRESHOLD: int = 1  # failures before marking unhealthy
    ORIGIN_HEALTHY_THRESHOLD: int = 1  # successes before marking healthy again
    ORIGIN_COOLDOWN_SECONDS: int = 60  # how long to keep node out of rotation

    # Logging
    LOG_LEVEL: str = "INFO"
    
    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() in ("production", "prod") or not self.DEBUG

    @validator("JWT_SECRET_KEY")
    def _validate_jwt_secret(cls, v, values):
        # A predictable JWT secret lets anyone mint a superuser token, so this is
        # a hard failure in production. Rotating it only logs users out.
        env = (values.get("APP_ENV") or "").lower()
        is_prod = env in ("production", "prod") or values.get("DEBUG") is False
        if is_prod and _is_insecure_secret(v):
            raise ValueError(
                "JWT_SECRET_KEY is a default/weak value; set a strong random secret "
                "(e.g. `openssl rand -hex 48`) before running in production."
            )
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

# SECRET_KEY derives the Fernet key that encrypts certificate private keys, so it
# cannot be rotated without a decrypt-then-re-encrypt migration. We therefore warn
# loudly instead of hard-failing, to avoid bricking an instance mid-migration.
if settings.is_production and _is_insecure_secret(settings.SECRET_KEY):
    logger.critical(
        "SECRET_KEY is a default/weak value in production. It encrypts certificate "
        "private keys — rotate it with the re-encryption migration (see "
        "scripts/rotate_secret_key.py) as soon as possible."
    )


