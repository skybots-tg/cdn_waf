"""Application configuration"""
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import validator, PostgresDsn


class Settings(BaseSettings):
    """Application settings"""
    
    # Application
    APP_NAME: str = "FlareCloud"
    APP_ENV: str = "development"
    DEBUG: bool = True
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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
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
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()


