from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ShuYuanAI Governance Core"
    app_version: str = "0.1.0"
    repository_mode: str = "memory"
    database_url: str = "postgresql+psycopg://shuyuan:shuyuan@localhost:5432/shuyuan"
    redis_url: str = "redis://localhost:6379/0"
    object_store_endpoint: str = "http://localhost:9000"
    object_store_bucket: str = "shuyuan-artifacts"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
