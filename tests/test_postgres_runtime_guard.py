import pytest

from plk_memory.app import create_app
from plk_memory.settings import Settings


def test_postgres_backend_fails_closed_until_runtime_cutover():
    settings = Settings(
        storage_backend="postgres",
        database_url="postgresql://plk:plk@localhost/plk",
    )

    with pytest.raises(RuntimeError, match="runtime cutover is not enabled"):
        create_app(settings=settings, graph=object())
