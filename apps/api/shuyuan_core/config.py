from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ShuYuanAI Governance Core"
    app_version: str = "0.1.0"
    repository_mode: str = Field(default="memory", alias="REPOSITORY_MODE")
    database_url: str = Field(
        default="postgresql+psycopg://shuyuan:shuyuan@localhost:5432/shuyuan",
        alias="DATABASE_URL",
    )
    coordination_backend: str = Field(default="auto", alias="COORDINATION_BACKEND")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    run_lock_ttl_s: int = Field(default=30, alias="RUN_LOCK_TTL_S")
    short_state_ttl_s: int = Field(default=300, alias="SHORT_STATE_TTL_S")
    receipt_idempotency_ttl_s: int = Field(default=86400, alias="RECEIPT_IDEMPOTENCY_TTL_S")
    object_store_mode: str = Field(default="local", alias="OBJECT_STORE_MODE")
    object_store_endpoint: str = Field(default="http://localhost:9000", alias="MINIO_ENDPOINT")
    object_store_bucket: str = "shuyuan-artifacts"
    object_store_access_key: str = Field(default="minioadmin", alias="MINIO_ACCESS_KEY")
    object_store_secret_key: str = Field(default="minioadmin", alias="MINIO_SECRET_KEY")
    object_store_secure: bool = Field(default=False, alias="MINIO_SECURE")
    object_store_local_path: Path = Field(default=Path(".data/object-store"), alias="OBJECT_STORE_LOCAL_PATH")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
