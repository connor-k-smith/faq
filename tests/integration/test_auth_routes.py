from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import CSRF_COOKIE, SESSION_COOKIE, get_db_session, get_identity_verifier
from app.config import Settings, get_settings
from app.domain.ports import IdentityClaims
from app.main import create_app
from app.models.session import get_engine
from tests.fakes import FakeIdentityVerifier

pytestmark = pytest.mark.integration


def test_exchange_creates_session_and_logout_requires_bound_csrf() -> None:
    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(connection)
    app = create_app()

    def override_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_identity_verifier] = lambda: FakeIdentityVerifier(
        IdentityClaims(
            uid="route-admin-test",
            email="route-admin@example.com",
            email_verified=True,
            display_name="Route Admin",
        )
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        bootstrap_admin_email="route-admin@example.com",
        session_secret="route-test-session-secret-is-long-enough",
        firebase_api_key="public-key",
        firebase_auth_domain="faq.firebaseapp.com",
        firebase_project_id="faq-test",
        firebase_app_id="1:test:web:test",
    )

    try:
        with TestClient(app) as client:
            csrf_response = client.get("/api/auth/csrf")
            login_csrf = csrf_response.cookies["faq_login_csrf"]
            exchange = client.post(
                "/api/auth/exchange",
                json={"id_token": "verified-by-fake"},
                headers={"X-CSRF-Token": login_csrf},
            )

            assert exchange.status_code == 200
            assert exchange.json()["organization_role"] == "admin"
            assert SESSION_COOKIE in client.cookies
            assert CSRF_COOKIE in client.cookies
            assert client.get("/api/auth/session").json()["display_name"] == "Route Admin"
            config = client.get("/api/auth/config")
            assert config.json() == {
                "provider": "password",
                "firebase": {
                    "api_key": "public-key",
                    "auth_domain": "faq.firebaseapp.com",
                    "project_id": "faq-test",
                    "app_id": "1:test:web:test",
                },
            }
            assert client.get("/api/auth/development-identities").status_code == 404
            assert client.post("/api/auth/development-session", json={}).status_code == 404

            rejected_logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"})
            assert rejected_logout.status_code == 403
            accepted_logout = client.post(
                "/api/auth/logout",
                headers={"X-CSRF-Token": client.cookies[CSRF_COOKIE]},
            )
            assert accepted_logout.status_code == 204
            assert SESSION_COOKIE not in client.cookies

    finally:
        session.close()
        transaction.rollback()
        connection.close()
