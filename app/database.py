"""Database engine and session construction."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    options: dict[str, Any] = {"pool_pre_ping": True}
    if settings.database_url.startswith("sqlite+"):
        options["poolclass"] = NullPool
    else:
        options.update(
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_command_timeout_seconds,
            connect_args={"command_timeout": settings.database_command_timeout_seconds},
        )
    return create_async_engine(settings.database_url, **options)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
