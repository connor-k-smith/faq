from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.auth.sessions import InvalidSessionError, SessionCodec, validate_csrf
from tests.fakes import DeterministicTokenGenerator, FixedClock


def test_session_round_trip_and_csrf_binding() -> None:
    actor_id = uuid4()
    codec = SessionCodec(
        "x" * 32,
        FixedClock(datetime(2026, 7, 25, tzinfo=UTC)),
        DeterministicTokenGenerator("csrf"),
        timedelta(hours=12),
    )

    encoded, issued = codec.issue(actor_id)
    verified = codec.verify(encoded)

    assert verified == issued
    validate_csrf(verified, issued.csrf_token, issued.csrf_token)


def test_session_rejects_tampering_and_expiry() -> None:
    codec = SessionCodec(
        "x" * 32,
        FixedClock(datetime(2026, 7, 25, tzinfo=UTC)),
        DeterministicTokenGenerator(),
        timedelta(hours=-1),
    )
    encoded, _ = codec.issue(uuid4())

    with pytest.raises(InvalidSessionError, match="signature"):
        codec.verify(f"{encoded[:-1]}x")
    with pytest.raises(InvalidSessionError, match="expired"):
        codec.verify(encoded)


def test_csrf_requires_cookie_and_header_to_match_session() -> None:
    codec = SessionCodec(
        "x" * 32,
        FixedClock(datetime(2026, 7, 25, tzinfo=UTC)),
        DeterministicTokenGenerator("csrf"),
        timedelta(hours=1),
    )
    _, claims = codec.issue(uuid4())

    with pytest.raises(InvalidSessionError, match="invalid CSRF"):
        validate_csrf(claims, claims.csrf_token, "attacker")
