"""Database engine and session dependencies."""

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models."""


def get_database_url() -> str:
    """Read the configured database URL."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/relivo",
    )


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the configured database engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_database_url(), pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the configured async sessionmaker."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def reset_database_engine() -> None:
    """Dispose the cached database engine."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield an async database session."""
    async with get_sessionmaker()() as session:
        yield session
