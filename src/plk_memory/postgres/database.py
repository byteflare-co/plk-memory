"""Async PostgreSQL lifecycle and transaction-scoped tenant context."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def normalize_async_database_url(url: str) -> str:
    """Accept common PostgreSQL URLs while always selecting asyncpg."""

    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    raise ValueError("database_url must use postgres:// or postgresql://")


class PostgresDatabase:
    """Owns the async engine and creates short-lived unit-of-work sessions."""

    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 10,
        application_name: str = "plk-memory",
    ) -> None:
        self.engine: AsyncEngine = create_async_engine(
            normalize_async_database_url(database_url),
            pool_size=pool_size,
            pool_pre_ping=True,
            connect_args={"server_settings": {"application_name": application_name}},
        )
        self.sessions = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def close(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def transaction(
        self,
        organization_id: UUID,
    ) -> AsyncIterator[AsyncSession]:
        """Open one transaction and apply the RLS organization context locally."""

        async with self.sessions() as session, session.begin():
            await set_organization_context(session, organization_id)
            yield session


async def set_organization_context(
    session: AsyncSession,
    organization_id: UUID,
) -> None:
    """Set the organization for RLS without leaking it through pooled connections."""

    await session.execute(
        text("SELECT set_config('app.current_organization_id', :value, true)"),
        {"value": str(organization_id)},
    )
