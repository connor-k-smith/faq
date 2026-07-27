from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.health import router


def health_client() -> TestClient:
    application = FastAPI()
    application.include_router(router)
    return TestClient(application)


def test_liveness_does_not_access_database() -> None:
    with patch("app.api.health.get_engine") as get_engine:
        response = health_client().get("/healthz")
    assert response.json() == {"status": "ok"}
    get_engine.assert_not_called()


def test_readiness_checks_database_and_migration_head() -> None:
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = "0002"
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    with (
        patch("app.api.health.get_engine", return_value=engine),
        patch("app.api.health.ScriptDirectory.from_config") as scripts,
    ):
        scripts.return_value.get_current_head.return_value = "0002"
        response = health_client().get("/readyz")
    assert response.json() == {"status": "ok"}


def test_readiness_fails_without_leaking_database_details() -> None:
    with patch("app.api.health.get_engine", side_effect=RuntimeError("secret host")):
        response = health_client().get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"detail": "service not ready"}
