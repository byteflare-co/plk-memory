import pytest

from plk_memory.index_worker import run
from plk_memory.settings import Settings


async def test_worker_database_credentials_fail_closed():
    settings = Settings.model_construct(
        worker_database_url="",
        database_url="postgresql://api-role@localhost/plk",
    )

    with pytest.raises(RuntimeError, match="PLK_WORKER_DATABASE_URL"):
        await run(settings)
