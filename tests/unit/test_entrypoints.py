from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.config import get_settings
from app.google_identity import get_google_identity_verifier
from app.jobs_main import create_app as create_jobs_app
from app.main import create_app as create_public_app
from app.operator_main import create_app as create_operator_app
from tests.fakes import FakeGoogleIdentityVerifier


def test_public_health_does_not_expose_operator_routes() -> None:
    app = create_public_app()
    client = TestClient(app)

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/admin/health").status_code == 404
    assert client.get("/admin/ask-recipients/not-a-uuid").status_code == 404
    assert client.get("/admin/inspect/actors").status_code == 404
    assert client.post("/admin/purges/request").status_code == 404


def test_identity_exchange_requires_login_csrf() -> None:
    client = TestClient(create_public_app())

    response = client.post("/api/auth/exchange", json={"id_token": "not-verified"})

    assert response.status_code == 403
    assert response.json() == {"detail": "invalid login CSRF token"}


def test_operator_entrypoint_mounts_only_operator_scaffold(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("FAQ_OPERATOR_AUDIENCE", "operator-audience")
    monkeypatch.setenv("FAQ_OPERATOR_ALLOWED_EMAILS", '["operator@example.com"]')
    verifier = FakeGoogleIdentityVerifier()
    app = create_operator_app()
    app.dependency_overrides[get_google_identity_verifier] = lambda: verifier
    client = TestClient(app)
    headers = {"Authorization": "Bearer valid-token"}

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/admin/health").json() == {"status": "ok"}
    assert client.get("/admin/ask-recipients/not-a-uuid", headers=headers).status_code == 422
    assert client.get("/admin/inspect/not-an-entity", headers=headers).status_code == 422
    assert client.get("/api/asks/not-a-uuid").status_code == 404
    assert client.get("/r/not-a-token").status_code == 404
    assert client.post("/jobs/tick").status_code == 404


def test_public_entrypoint_rejects_jobs_routes() -> None:
    client = TestClient(create_public_app())

    assert client.post("/jobs/tick").status_code == 404
    assert client.get("/jobs/anything").status_code == 404


def test_jobs_entrypoint_is_isolated_and_auth_fails_closed() -> None:
    app = create_jobs_app()
    client = TestClient(app)

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/asks/anything").status_code == 404
    assert client.get("/admin/health").status_code == 404
    assert client.post("/jobs/tick").status_code == 401
    assert client.post("/jobs/tick", headers={"Authorization": "Bearer secret"}).status_code == 401


def test_jobs_identity_verifier_receives_token_and_audience(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("FAQ_JOBS_AUDIENCE", "scheduler-audience")
    monkeypatch.setenv("FAQ_JOBS_CALLER_EMAIL", "scheduler@example.com")
    get_settings.cache_clear()
    verifier = FakeGoogleIdentityVerifier(email="scheduler@example.com", valid_token="wrong")
    app = create_jobs_app()
    app.dependency_overrides[get_google_identity_verifier] = lambda: verifier
    try:
        response = TestClient(app).post(
            "/jobs/tick", headers={"Authorization": "Bearer supplied-token"}
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 401
    assert verifier.calls == [("supplied-token", "scheduler-audience")]


def test_jobs_rejects_wrong_verified_caller(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("FAQ_JOBS_AUDIENCE", "scheduler-audience")
    monkeypatch.setenv("FAQ_JOBS_CALLER_EMAIL", "scheduler@example.com")
    app = create_jobs_app()
    verifier = FakeGoogleIdentityVerifier(email="attacker@example.com")
    app.dependency_overrides[get_google_identity_verifier] = lambda: verifier

    response = TestClient(app).post(
        "/jobs/tick", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "valid job identity required"}


def test_operator_requires_verified_allowlisted_bearer(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("FAQ_OPERATOR_AUDIENCE", "operator-audience")
    monkeypatch.setenv("FAQ_OPERATOR_ALLOWED_EMAILS", '["operator@example.com"]')
    app = create_operator_app()
    verifier = FakeGoogleIdentityVerifier(email="other@example.com")
    app.dependency_overrides[get_google_identity_verifier] = lambda: verifier
    client = TestClient(app)

    assert client.get("/admin/inspect/actors").status_code == 401
    response = client.get(
        "/admin/inspect/actors", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "operator is not authorized"}
    assert verifier.calls == [("valid-token", "operator-audience")]
