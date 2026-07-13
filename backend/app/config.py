"""
RestoreProof application settings.

Purpose: Load environment configuration for API and worker.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.1.0
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://restoreproof:restoreproof@localhost:5432/restoreproof"
    )
    secret_key: str = "dev-secret-change-me-to-a-long-random-string"
    encryption_key: str = ""
    app_base_url: str = "http://localhost:3080"
    cors_origins: str = "*"
    data_dir: str = "/data"
    default_boot_wait_seconds: int = 60
    access_token_expire_minutes: int = 60 * 12
    reset_token_expire_minutes: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
