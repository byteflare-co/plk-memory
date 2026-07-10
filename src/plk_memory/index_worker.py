"""Standalone PostgreSQL outbox → Graphiti projection worker."""

from __future__ import annotations

import asyncio
import signal

from plk_memory.graphindex import GraphIndex
from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.graph_adapter import PostgresGraphSearchIndex
from plk_memory.postgres.outbox import (
    PostgresChangeFeed,
    PostgresIndexStateRepository,
)
from plk_memory.postgres.repository import PostgresFactRepository
from plk_memory.postgres.worker import PostgresIndexWorker
from plk_memory.settings import Settings


async def run(settings: Settings | None = None) -> None:
    settings = settings or Settings()
    database_url = settings.worker_database_url
    if not database_url:
        raise RuntimeError("PLK_WORKER_DATABASE_URL is required")
    database = PostgresDatabase(
        database_url,
        pool_size=settings.database_pool_size,
        application_name="plk-index-worker",
        allow_cross_organization=True,
    )
    graph = GraphIndex(settings)
    search_index = PostgresGraphSearchIndex(
        graph=graph,
        api_database=database,
        worker_database=database,
        settings=settings,
    )
    worker = PostgresIndexWorker(
        repository=PostgresFactRepository(database),
        change_feed=PostgresChangeFeed(
            database, max_attempts=settings.outbox_max_attempts
        ),
        index_state=PostgresIndexStateRepository(database, backend="graphiti"),
        search_index=search_index,
        settings=settings,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:  # pragma: no cover - Windows event loop
            pass
    try:
        await search_index.start()
        await worker.run_forever(stop)
    finally:
        await graph.close()
        await database.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
