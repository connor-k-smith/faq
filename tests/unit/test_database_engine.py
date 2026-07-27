from unittest.mock import patch

from app.config import Settings, get_settings
from app.models.session import get_engine


def test_engine_uses_typed_pool_configuration_without_connecting() -> None:
    settings = Settings(
        database_pool_size=7,
        database_max_overflow=2,
        database_pool_timeout=3.5,
        database_pool_recycle=900,
    )
    get_settings.cache_clear()
    get_engine.cache_clear()
    with (
        patch("app.models.session.get_settings", return_value=settings),
        patch("app.models.session.create_engine") as create_engine,
    ):
        get_engine()

    create_engine.assert_called_once_with(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=7,
        max_overflow=2,
        pool_timeout=3.5,
        pool_recycle=900,
        connect_args={"connect_timeout": 3},
    )
    get_engine.cache_clear()
