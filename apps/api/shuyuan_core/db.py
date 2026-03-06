from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def normalize_sync_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return url


def create_sync_engine(url: str | None = None) -> Engine:
    settings = get_settings()
    resolved = normalize_sync_database_url(url or settings.database_url)
    return create_engine(resolved, future=True)


def create_session_factory(engine_or_url: Engine | str | None = None):
    engine = engine_or_url if isinstance(engine_or_url, Engine) else create_sync_engine(engine_or_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
