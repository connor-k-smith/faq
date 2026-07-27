import base64
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from uuid import UUID


class InvalidInvitationSession(ValueError):
    pass


@dataclass(frozen=True)
class InvitationClaims:
    recipient_id: UUID
    session_version: int
    expires_at: int


class InvitationSessionCodec:
    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("session secret must contain at least 32 characters")
        self._secret = secret.encode()

    def issue(self, claims: InvitationClaims) -> str:
        payload = _encode(json.dumps(asdict(claims), separators=(",", ":"), default=str).encode())
        signature = _encode(hmac.digest(self._secret, payload.encode(), hashlib.sha256))
        return f"{payload}.{signature}"

    def verify(self, encoded: str) -> InvitationClaims:
        try:
            payload, supplied_signature = encoded.split(".", 1)
            expected_signature = _encode(
                hmac.digest(self._secret, payload.encode(), hashlib.sha256)
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise InvalidInvitationSession("invalid invitation session")
            raw = json.loads(_decode(payload))
            return InvitationClaims(
                recipient_id=UUID(raw["recipient_id"]),
                session_version=int(raw["session_version"]),
                expires_at=int(raw["expires_at"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            if isinstance(error, InvalidInvitationSession):
                raise
            raise InvalidInvitationSession("malformed invitation session") from error


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
