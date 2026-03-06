from __future__ import annotations

from pathlib import Path

from .config import get_settings
from .db import normalize_sync_database_url


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def create_alembic_config(database_url: str | None = None):
    from alembic.config import Config

    root = _repo_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    resolved_url = normalize_sync_database_url(database_url or get_settings().database_url)
    config.set_main_option("sqlalchemy.url", resolved_url)
    return config


def upgrade_database(revision: str = "head", database_url: str | None = None) -> None:
    from alembic import command

    command.upgrade(create_alembic_config(database_url), revision)
