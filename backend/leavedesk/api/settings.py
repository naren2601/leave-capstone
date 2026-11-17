"""Settings read from environment variables or a .env file.

Secrets are never written in code. Copy .env.example to .env and fill it in.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="LEAVEDESK_", extra="ignore")

    environment: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"

    # At least 32 characters, so the HS256 key is long enough to be safe.
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_minutes: int = Field(default=30, ge=1, le=24 * 60)

    # Password for the demo users created at startup. Dev only.
    seed_password: SecretStr = Field(min_length=6)

    sse_keepalive_seconds: float = Field(default=15, gt=0)

    # Day 3: PostgreSQL. Without a URL the API keeps everything in memory, as on Day 2.
    # Example: postgresql+psycopg://leavedesk:<password>@localhost:5432/leavedesk
    database_url: SecretStr | None = None
    tenant_name: str = "LeaveDesk Demo"
    # Log every SQL statement, to spot N+1 queries while developing.
    database_echo: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
