from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ShuYuanAI Governance Core"
    app_version: str = "0.1.0"
    repository_mode: str = "memory"
    database_url: str = Field(
        default="postgresql+psycopg://shuyuan:shuyuan@localhost:5432/shuyuan",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    object_store_endpoint: str = Field(default="http://localhost:9000", alias="MINIO_ENDPOINT")
    object_store_bucket: str = "shuyuan-artifacts"
    object_store_access_key: str = Field(default="minioadmin", alias="MINIO_ACCESS_KEY")
    object_store_secret_key: str = Field(default="minioadmin", alias="MINIO_SECRET_KEY")
    object_store_secure: bool = Field(default=False, alias="MINIO_SECURE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
