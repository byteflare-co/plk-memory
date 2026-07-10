"""Async PostgreSQL lifecycle and transaction-scoped tenant context."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
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
        database_url: str | None,
        *,
        pool_size: int = 10,
        application_name: str = "plk-memory",
        async_creator: Callable[[], Awaitable[Any]] | None = None,
        allow_cross_organization: bool = False,
    ) -> None:
        if database_url is None and async_creator is None:
            raise ValueError("database_url or async_creator is required")
        engine_url = (
            normalize_async_database_url(database_url)
            if database_url is not None
            else "postgresql+asyncpg://"
        )
        engine_options: dict[str, Any] = {
            "pool_size": pool_size,
            "pool_pre_ping": True,
        }
        if async_creator is None:
            engine_options["connect_args"] = {
                "server_settings": {"application_name": application_name}
            }
        else:
            # The creator is called for every new physical connection, which
            # allows a fresh Aurora IAM token to be generated at that point.
            engine_options["async_creator"] = async_creator
        self.engine = create_async_engine(engine_url, **engine_options)
        self.allow_cross_organization = allow_cross_organization
        self.sessions = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def close(self) -> None:
        await self.engine.dispose()

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    @asynccontextmanager
    async def transaction(
        self,
        organization_id: UUID,
    ) -> AsyncIterator[AsyncSession]:
        """Open one transaction and apply the RLS organization context locally."""

        async with self.sessions() as session, session.begin():
            await set_organization_context(session, organization_id)
            yield session

    @asynccontextmanager
    async def worker_transaction(self) -> AsyncIterator[AsyncSession]:
        """Open a transaction for a dedicated worker role with ``BYPASSRLS``.

        API request paths must use :meth:`transaction`. This method exists for
        the cross-organization outbox/index worker and therefore requires a
        separately provisioned database role.
        """

        if not self.allow_cross_organization:
            raise RuntimeError(
                "cross-organization transaction requires a worker database"
            )
        async with self.sessions() as session, session.begin():
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
