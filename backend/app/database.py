"""Database engine and session management."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import create_engine, event, inspect

from .config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""
    pass


settings = get_settings()
engine = create_async_engine(
    settings.database.url,
    echo=settings.database.echo,
    connect_args={
        "check_same_thread": False,  # SQLite-specific
        "timeout": 30,  # SQLite busy_timeout in seconds
    },
)


# Set WAL mode and busy_timeout on every new connection automatically
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _sync_db_url() -> str:
    """A synchronous DB URL for Alembic (strips the async driver suffix)."""
    return settings.database.url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg2")


def _alembic_config():
    """Build an Alembic Config pointing at this project's migration scripts."""
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parent.parent  # .../backend
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


def _run_migrations() -> None:
    """Bring the schema to the latest Alembic revision (runs synchronously)."""
    from alembic import command

    cfg = _alembic_config()

    # Decide between stamping and upgrading by inspecting the current DB.
    sync_engine = create_engine(_sync_db_url())
    try:
        with sync_engine.connect() as conn:
            insp = inspect(conn)
            has_version = insp.has_table("alembic_version")
            has_legacy_schema = insp.has_table("projects")
    finally:
        sync_engine.dispose()

    if not has_version and has_legacy_schema:
        # A database created before Alembic was adopted: the tables already
        # exist, so just record the current revision without re-creating them.
        logger.info("Existing pre-Alembic database detected; stamping to head")
        command.stamp(cfg, "head")
    else:
        # Fresh database (the baseline migration creates everything) or an
        # already-tracked one (any pending migrations are applied).
        command.upgrade(cfg, "head")


async def init_db() -> None:
    """Bring the database schema up to date via Alembic migrations.

    Schema changes are no longer hand-written here. To change the schema,
    edit the models and run:  alembic revision --autogenerate -m "describe it"
    then review the generated file. It is applied automatically on next start.
    """
    await asyncio.to_thread(_run_migrations)
