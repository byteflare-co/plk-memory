import pytest

from plk_memory.app import create_app
from plk_memory.settings import Settings


def test_postgres_backend_requires_database_url():
    settings = Settings(storage_backend="postgres", database_url="")

    with pytest.raises(RuntimeError, match="PLK_DATABASE_URL"):
        create_app(settings=settings, graph=object())


def test_postgres_backend_builds_runtime_when_configured():
    settings = Settings(
        storage_backend="postgres",
        database_url="postgresql://plk:plk@localhost/plk",
    )

    app = create_app(settings=settings, graph=object())

    assert app.state.services.settings.storage_backend == "postgres"
