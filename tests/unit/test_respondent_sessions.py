from uuid import uuid4

import pytest

from app.auth.respondent_sessions import (
    InvalidInvitationSession,
    InvitationClaims,
    InvitationSessionCodec,
)


def test_invitation_session_is_signed_and_versioned() -> None:
    codec = InvitationSessionCodec("respondent-session-secret-at-least-32-characters")
    claims = InvitationClaims(recipient_id=uuid4(), session_version=4, expires_at=123456)

    encoded = codec.issue(claims)

    assert codec.verify(encoded) == claims
    with pytest.raises(InvalidInvitationSession):
        codec.verify(f"{encoded[:-1]}x")
