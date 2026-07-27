import pytest

from app.config import Settings


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql+psycopg://faq:secret@database/faq",
        "session_secret": "a-production-session-secret-long-enough",
        "public_base_url": "https://faq.example.com",
        "firebase_api_key": "public-api-key",
        "firebase_auth_domain": "faq.firebaseapp.com",
        "firebase_project_id": "faq-production",
        "firebase_app_id": "1:123:web:abc",
        "jobs_audience": "https://jobs.example.com",
        "jobs_caller_email": "scheduler@example.com",
        "operator_audience": "https://operator.example.com",
        "operator_allowed_emails": {"operator@example.com"},
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("validator", "override", "message"),
    [
        ("public", {"session_secret": "development-only-session-secret-key"}, "session_secret"),
        ("public", {"public_base_url": "http://faq.example.com"}, "HTTPS"),
        ("public", {"firebase_project_id": None}, "firebase_project_id"),
        ("jobs", {"jobs_audience": None}, "jobs_audience"),
        ("jobs", {"jobs_caller_email": None}, "jobs_caller_email"),
        ("operator", {"operator_audience": None}, "operator_audience"),
        ("operator", {"operator_allowed_emails": set()}, "operator_allowed_emails"),
    ],
)
def test_production_service_configuration_fails_closed(
    validator: str, override: dict[str, object], message: str
) -> None:
    settings = production_settings(**override)
    with pytest.raises(ValueError, match=message):
        getattr(settings, f"validate_{validator}_startup")()


@pytest.mark.parametrize("validator", ["public", "operator", "jobs", "migration"])
def test_every_production_service_rejects_development_database(validator: str) -> None:
    settings = production_settings(
        database_url="postgresql+psycopg://faq:faq@localhost:55433/faq"
    )
    with pytest.raises(ValueError, match="database_url"):
        getattr(settings, f"validate_{validator}_startup")()


def test_services_validate_only_their_own_configuration() -> None:
    settings = production_settings(jobs_audience=None, operator_audience=None)
    settings.validate_public_startup()


def test_development_defaults_remain_available() -> None:
    assert Settings().environment == "development"
