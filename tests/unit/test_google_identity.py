from typing import Any

import pytest
from pytest import MonkeyPatch

from app.google_identity import GoogleIdentityError, GoogleOIDCIdentityVerifier


def test_google_verifier_returns_verified_email(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def verify(token: str, request: object, audience: str) -> dict[str, Any]:
        del request
        calls.append((token, audience))
        return {"email": "caller@example.com", "email_verified": True}

    monkeypatch.setattr("app.google_identity.id_token.verify_oauth2_token", verify)

    principal = GoogleOIDCIdentityVerifier().verify("token", "expected-audience")

    assert principal.email == "caller@example.com"
    assert calls == [("token", "expected-audience")]


@pytest.mark.parametrize(
    "claims",
    [
        {"email": "caller@example.com", "email_verified": False},
        {"email_verified": True},
    ],
)
def test_google_verifier_rejects_unverified_or_missing_email(
    monkeypatch: MonkeyPatch, claims: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "app.google_identity.id_token.verify_oauth2_token",
        lambda token, request, audience: claims,
    )

    with pytest.raises(GoogleIdentityError):
        GoogleOIDCIdentityVerifier().verify("token", "audience")


def test_google_verifier_normalizes_malformed_or_wrong_audience(
    monkeypatch: MonkeyPatch,
) -> None:
    def reject(token: str, request: object, audience: str) -> dict[str, Any]:
        raise ValueError("Token has wrong audience or is malformed")

    monkeypatch.setattr("app.google_identity.id_token.verify_oauth2_token", reject)

    with pytest.raises(GoogleIdentityError, match="invalid Google identity"):
        GoogleOIDCIdentityVerifier().verify("raw-secret-token", "audience")
