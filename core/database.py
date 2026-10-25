"""Async database engine, session factories and schema bootstrap."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)

import models  # noqa: F401  -- importing registers every ORM model on Base.metadata
from core.config import settings
from models.base import Base

engine: AsyncEngine = create_async_engine(settings.database_url, echo=False)

if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _enforce_sqlite_foreign_keys(
        dbapi_connection: Any, _record: Any
    ) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

ScopedSession = async_scoped_session(
    SessionFactory, scopefunc=asyncio.current_task
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one session per request."""
    async with SessionFactory() as session:
        yield session


async def init_db() -> None:
    """Create all tables declared by the ORM metadata (idempotent)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Close pooled connections on shutdown."""
    await engine.dispose()
