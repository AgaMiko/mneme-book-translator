"""Async SQLAlchemy engine and session management."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass

from app.core.config import get_settings


class Base(MappedAsDataclass, DeclarativeBase, kw_only=True):
    """Base class for all ORM models.

    `MappedAsDataclass` gives us a real `__init__` and `__repr__`. The
    `kw_only=True` flag means subclasses don't have to worry about
    ordering required vs defaulted fields — every field is a keyword
    argument, which also makes call sites self-documenting.

    `eager_defaults=True` makes SQLAlchemy fetch server-computed values
    (``server_default``, ``onupdate=func.now()``) eagerly via Postgres
    ``RETURNING`` in the same flush, instead of marking the column
    expired and lazy-refreshing on next attribute access. Without this,
    reading e.g. ``voice.updated_at`` after a commit triggers a sync
    I/O refresh that crashes inside an async route with
    ``MissingGreenlet``. Subclasses inherit this via class-attribute
    lookup — none of our models override ``__mapper_args__``.
    """

    __mapper_args__ = {"eager_defaults": True}


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Yields a transaction-scoped session."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
