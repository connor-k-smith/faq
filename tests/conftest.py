import os
from collections.abc import Generator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.models.session import get_engine, get_session_factory

TEST_DATABASE_NAME = "faq_test"
_DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://faq:faq@localhost:55433/faq_test"
)
_LOCK_ID = 0x46415154
_lock_connection: psycopg.Connection[tuple[object, ...]] | None = None


def _database_urls() -> tuple[str, str]:
    database_url = os.environ.get("FAQ_TEST_DATABASE_URL", _DEFAULT_TEST_DATABASE_URL)
    url = make_url(database_url)
    if url.database != TEST_DATABASE_NAME:
        raise pytest.UsageError(
            "FAQ_TEST_DATABASE_URL must target exactly "
            f"{TEST_DATABASE_NAME!r}, got {url.database!r}"
        )
    if "production" in database_url.lower():
        raise pytest.UsageError("refusing a test database URL containing 'production'")
    if not url.drivername.startswith("postgresql"):
        raise pytest.UsageError("FAQ_TEST_DATABASE_URL must be a PostgreSQL URL")
    admin_url = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    return database_url, admin_url


def _clear_database_caches() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


def _recreate_database() -> None:
    database_url, _ = _database_urls()
    assert _lock_connection is not None
    _clear_database_caches()
    _lock_connection.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}" WITH (FORCE)')
    _lock_connection.execute(f'CREATE DATABASE "{TEST_DATABASE_NAME}"')
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    _clear_database_caches()


def pytest_configure(config: pytest.Config) -> None:
    global _lock_connection
    database_url, admin_url = _database_urls()
    os.environ["FAQ_DATABASE_URL"] = database_url
    _lock_connection = psycopg.connect(admin_url, autocommit=True)
    locked = _lock_connection.execute(
        "SELECT pg_try_advisory_lock(%s)", (_LOCK_ID,)
    ).fetchone()
    if locked != (True,):
        _lock_connection.close()
        _lock_connection = None
        raise pytest.UsageError(
            "another pytest process owns faq_test; parallel independent runs are unsupported"
        )


def pytest_unconfigure(config: pytest.Config) -> None:
    global _lock_connection
    _clear_database_caches()
    if _lock_connection is not None:
        _lock_connection.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_ID,))
        _lock_connection.close()
        _lock_connection = None


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Generator[None]:
    _recreate_database()
    yield
    _clear_database_caches()
