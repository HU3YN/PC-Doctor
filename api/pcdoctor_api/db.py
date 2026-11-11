"""Database engine, session and schema migration."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import Settings, get_settings

MIGRATIONS = Path(__file__).parent / "migrations"


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """A timezone-aware UTC timestamp on every database.

    PostgreSQL keeps the time zone; SQLite silently drops it. This puts UTC
    back on the way out so the API always returns times with an offset.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def ensure_sqlite_folder(url: str) -> None:
    """SQLite creates the file but not the folder it lives in."""
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)


def make_engine(settings: Settings) -> Engine:
    url = settings.sqlalchemy_url
    if url.startswith("sqlite"):
        ensure_sqlite_folder(url)
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(connection, _record):  # noqa: ANN001
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")  # off by default in SQLite
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True)


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        _engine = make_engine(get_settings())
        _session_factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    """Forget the engine (tests use this after changing settings)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_db() -> Iterator[Session]:
    get_engine()
    assert _session_factory is not None
    with _session_factory() as session:
        yield session


def alembic_config(settings: Settings | None = None) -> Config:
    settings = settings or get_settings()
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    # '%' must be doubled for configparser (passwords can contain it).
    config.set_main_option("sqlalchemy.url", settings.sqlalchemy_url.replace("%", "%%"))
    return config


def migrate() -> None:
    """Create or upgrade the tables to the newest migration."""
    command.upgrade(alembic_config(), "head")
