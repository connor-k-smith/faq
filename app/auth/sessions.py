import base64
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import timedelta
from uuid import UUID

from app.domain.ports import Clock, TokenGenerator


class InvalidSessionError(ValueError):
    pass


@dataclass(frozen=True)
class SessionClaims:
    actor_id: UUID
    expires_at: int
    csrf_token: str


class SessionCodec:
    def __init__(
        self,
        secret: str,
        clock: Clock,
        tokens: TokenGenerator,
        lifetime: timedelta,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("session secret must contain at least 32 characters")
        self._secret = secret.encode()
        self._clock = clock
        self._tokens = tokens
        self._lifetime = lifetime

    def issue(self, actor_id: UUID) -> tuple[str, SessionClaims]:
        claims = SessionClaims(
            actor_id=actor_id,
            expires_at=int((self._clock.now() + self._lifetime).timestamp()),
            csrf_token=self._tokens.urlsafe(),
        )
        payload = _encode(json.dumps(asdict(claims), separators=(",", ":"), default=str).encode())
        signature = _encode(hmac.digest(self._secret, payload.encode(), hashlib.sha256))
        return f"{payload}.{signature}", claims

    def verify(self, encoded: str) -> SessionClaims:
        try:
            payload, supplied_signature = encoded.split(".", 1)
            expected_signature = _encode(
                hmac.digest(self._secret, payload.encode(), hashlib.sha256)
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise InvalidSessionError("invalid session signature")
            raw = json.loads(_decode(payload))
            claims = SessionClaims(
                actor_id=UUID(raw["actor_id"]),
                expires_at=int(raw["expires_at"]),
                csrf_token=str(raw["csrf_token"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            if isinstance(error, InvalidSessionError):
                raise
            raise InvalidSessionError("malformed session") from error
        if claims.expires_at <= int(self._clock.now().timestamp()):
            raise InvalidSessionError("session expired")
        return claims


def validate_csrf(
    claims: SessionClaims,
    cookie_token: str | None,
    submitted_token: str | None,
) -> None:
    if not cookie_token or not submitted_token:
        raise InvalidSessionError("missing CSRF token")
    if not hmac.compare_digest(claims.csrf_token, cookie_token) or not hmac.compare_digest(
        cookie_token, submitted_token
    ):
        raise InvalidSessionError("invalid CSRF token")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
