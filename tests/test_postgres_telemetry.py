import os
from contextlib import asynccontextmanager
from typing import cast
from uuid import uuid4

import pytest
from ulid import ULID

from plk_memory.postgres.database import PostgresDatabase
from plk_memory.postgres.telemetry import PostgresTelemetryStore

pytestmark = pytest.mark.postgres


class FailingMaintenanceDatabase:
    @asynccontextmanager
    async def worker_transaction(self):
        raise ConnectionError("temporary maintenance outage")
        yield

    async def close(self) -> None:
        return None


async def test_maintenance_failure_falls_back_to_hash_only():
    database_url = os.environ.get("PLK_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PLK_TEST_DATABASE_URL is not configured")
    organization_id = uuid4()
    database = PostgresDatabase(database_url, pool_size=2)
    telemetry = PostgresTelemetryStore(
        database,
        organization_provider=lambda: organization_id,
        raw_query_retention_days=30,
        maintenance_database=cast(
            PostgresDatabase,
            FailingMaintenanceDatabase(),
        ),
    )
    search_id = str(ULID())
    try:
        await telemetry.start()
        await telemetry.record_search(
            client="service:test",
            search_id=search_id,
            query="preview survives a transient sweeper outage",
            hits=0,
            latency_ms=1,
            reason="auto-guideline",
            fact_refs=[],
            outcome="ok",
        )
        usage = await telemetry.list_usage()
        recorded = next(row for row in usage if row.get("search_id") == search_id)
        assert recorded["query"] is None
        assert len(recorded["query_hash"]) == 64
    finally:
        await telemetry.close()
        await database.close()
