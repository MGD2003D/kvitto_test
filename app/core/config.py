from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """The subset Alembic needs: migrations must not require app secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://kvitto:kvitto@localhost:5432/kvitto"


class Settings(DatabaseSettings):
    webhook_secret: SecretStr

    @field_validator("webhook_secret")
    @classmethod
    def secret_not_blank(cls, value: SecretStr) -> SecretStr:
        # An empty HMAC key lets anyone forge webhook signatures.
        if not value.get_secret_value().strip():
            raise ValueError("webhook_secret must not be blank")
        return value


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
