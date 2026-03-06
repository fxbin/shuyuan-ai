from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def create_sync_engine(url: str | None = None):
    settings = get_settings()
    return create_engine(url or settings.database_url, future=True)


def create_session_factory(url: str | None = None):
    engine = create_sync_engine(url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
