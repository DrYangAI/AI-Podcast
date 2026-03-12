"""Database engine and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from .config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""
    pass


settings = get_settings()
engine = create_async_engine(
    settings.database.url,
    echo=settings.database.echo,
    connect_args={
        "check_same_thread": False,  # SQLite-specific
    },
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an async database session."""
    async with async_session_factory() as session:
        try:
            # Enable WAL mode for this connection
            await session.execute(text("PRAGMA journal_mode=WAL"))
            await session.execute(text("PRAGMA busy_timeout=5000"))
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables (for development; use Alembic in production)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrate: add missing columns to existing tables
        await _migrate_add_columns(conn)


async def _migrate_add_columns(conn) -> None:
    """Add new columns to existing tables if they don't exist (SQLite safe)."""
    migrations = [
        ("projects", "image_width", "INTEGER"),
        ("projects", "image_height", "INTEGER"),
        ("projects", "image_quality", "VARCHAR(20) DEFAULT 'standard' NOT NULL"),
        ("projects", "image_style", "VARCHAR(20) DEFAULT 'natural' NOT NULL"),
        ("projects", "image_negative_prompt", "TEXT"),
        ("projects", "subtitle_enabled", "BOOLEAN DEFAULT 1 NOT NULL"),
        ("projects", "subtitle_font_size", "INTEGER DEFAULT 18 NOT NULL"),
        ("projects", "subtitle_font_color", "VARCHAR(20) DEFAULT '#FFFFFF' NOT NULL"),
        ("projects", "subtitle_outline_width", "INTEGER DEFAULT 1 NOT NULL"),
        ("projects", "subtitle_position", "VARCHAR(10) DEFAULT 'bottom' NOT NULL"),
        ("projects", "subtitle_margin_bottom", "INTEGER DEFAULT 30 NOT NULL"),
        ("projects", "portrait_composite_enabled", "BOOLEAN DEFAULT 1 NOT NULL"),
        ("projects", "portrait_bg_color", "VARCHAR(20) DEFAULT '#1A1A2E' NOT NULL"),
        ("projects", "portrait_title_text", "VARCHAR(255)"),
        ("video_outputs", "video_type", "VARCHAR(20) DEFAULT 'standard' NOT NULL"),
        ("projects", "tts_voice_id", "VARCHAR(100)"),
        ("projects", "tts_voice_clone_id", "VARCHAR(36)"),
        ("voice_clones", "speaker_id", "VARCHAR(100) DEFAULT '' NOT NULL"),
        ("voice_clones", "training_status", "INTEGER DEFAULT 0 NOT NULL"),
        ("projects", "portrait_title_font_size", "INTEGER DEFAULT 36 NOT NULL"),
        ("projects", "portrait_title_y", "INTEGER DEFAULT 82 NOT NULL"),
        ("projects", "portrait_video_y", "INTEGER DEFAULT 480 NOT NULL"),
        ("projects", "portrait_subtitle_font_size", "INTEGER DEFAULT 38 NOT NULL"),
        ("projects", "portrait_subtitle_margin_v", "INTEGER DEFAULT 550 NOT NULL"),
        ("projects", "cover_prompt", "TEXT"),
        ("publish_assets", "cover_status", "VARCHAR(20) DEFAULT 'pending' NOT NULL"),
    ]
    for table, column, col_type in migrations:
        try:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
        except Exception:
            pass  # Column already exists
