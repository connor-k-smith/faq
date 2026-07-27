from dataclasses import dataclass
from typing import Any, Protocol, cast

from google.auth.transport.requests import Request
from google.oauth2 import id_token


class GoogleIdentityError(ValueError):
    pass


@dataclass(frozen=True)
class GooglePrincipal:
    email: str


class GoogleIdentityVerifier(Protocol):
    def verify(self, bearer_token: str, audience: str) -> GooglePrincipal: ...


class GoogleOIDCIdentityVerifier:
    def verify(self, bearer_token: str, audience: str) -> GooglePrincipal:
        try:
            claims = cast(
                dict[str, Any],
                id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
                    bearer_token, Request(), audience
                ),
            )
        except (ValueError, TypeError) as error:
            raise GoogleIdentityError("invalid Google identity") from error

        email = claims.get("email")
        if claims.get("email_verified") is not True or not isinstance(email, str) or not email:
            raise GoogleIdentityError("invalid Google identity")
        return GooglePrincipal(email=email)


def get_google_identity_verifier() -> GoogleIdentityVerifier:
    return GoogleOIDCIdentityVerifier()
