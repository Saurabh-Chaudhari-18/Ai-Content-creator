from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

# Known placeholder values from .env.example — must never run in production.
_PLACEHOLDER_SECRETS = {
    "your-super-secret-key-change-this-in-production-min-32-chars",
    "your-32-byte-encryption-key-here!",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    APP_NAME: str = "Social Media SaaS"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str
    DATABASE_URL_SYNC: str

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ISSUER: str = "omnipost-api"
    JWT_AUDIENCE: str = "omnipost-client"

    # Token Encryption
    ENCRYPTION_KEY: str

    # S3 / R2 / MinIO
    S3_BUCKET_NAME: str = "social-saas-media"
    S3_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_ENDPOINT_URL: str = ""  # Empty = AWS S3, set for R2/MinIO

    # Meta (Facebook / Instagram)
    FACEBOOK_APP_ID: str = ""
    FACEBOOK_APP_SECRET: str = ""
    FACEBOOK_REDIRECT_URI: str = "http://localhost:8000/api/v1/social/callback/facebook"
    # Graph API version is config, never hardcoded in adapters — Meta
    # deprecates versions on a fixed schedule.
    META_GRAPH_API_VERSION: str = "v21.0"

    # LinkedIn
    LINKEDIN_CLIENT_ID: str = ""
    LINKEDIN_CLIENT_SECRET: str = ""
    LINKEDIN_REDIRECT_URI: str = "http://localhost:8000/api/v1/social/callback/linkedin"

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    @model_validator(mode="after")
    def _production_guards(self):
        """Fail fast at boot instead of running production with dev secrets."""
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY in _PLACEHOLDER_SECRETS or len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "SECRET_KEY is a placeholder or too short for production. "
                    'Generate one: python -c "import secrets; print(secrets.token_urlsafe(64))"'
                )
            if self.ENCRYPTION_KEY in _PLACEHOLDER_SECRETS:
                raise ValueError(
                    "ENCRYPTION_KEY is the .env.example placeholder. Generate a real key: "
                    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
                )
            if self.DEBUG:
                raise ValueError("DEBUG must be false in production.")
        return self


settings = Settings()
