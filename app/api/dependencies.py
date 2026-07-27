from collections.abc import Generator
from datetime import timedelta
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.auth.firebase import FirebaseIdentityVerifier
from app.auth.sessions import InvalidSessionError, SessionClaims, SessionCodec, validate_csrf
from app.config import Settings, get_settings
from app.domain.enums import OrganizationRole
from app.domain.ports import IdentityVerifier, SystemClock, TokenGenerator
from app.domain.tokens import SecureTokenGenerator
from app.models.identity import Actor
from app.models.session import get_session_factory

SESSION_COOKIE = "faq_session"
CSRF_COOKIE = "faq_csrf"
LOGIN_CSRF_COOKIE = "faq_login_csrf"


def get_db_session() -> Generator[Session]:
    with get_session_factory()() as session:
        yield session


def get_identity_verifier(settings: Annotated[Settings, Depends(get_settings)]) -> IdentityVerifier:
    return FirebaseIdentityVerifier(settings.firebase_project_id)


def get_token_generator() -> TokenGenerator:
    return SecureTokenGenerator()


def get_session_codec(settings: Annotated[Settings, Depends(get_settings)]) -> SessionCodec:
    return SessionCodec(
        settings.session_secret.get_secret_value(),
        SystemClock(),
        SecureTokenGenerator(),
        timedelta(hours=settings.session_lifetime_hours),
    )


def get_session_claims(
    codec: Annotated[SessionCodec, Depends(get_session_codec)],
    encoded: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> SessionClaims:
    if encoded is None:
        raise HTTPException(status_code=401, detail="authentication required")
    try:
        return codec.verify(encoded)
    except InvalidSessionError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


def get_current_actor(
    claims: Annotated[SessionClaims, Depends(get_session_claims)],
    session: Annotated[Session, Depends(get_db_session)],
) -> Actor:
    actor = session.get(Actor, claims.actor_id)
    if actor is None or actor.deleted_at is not None or actor.firebase_uid is None:
        raise HTTPException(status_code=401, detail="actor is unavailable")
    return actor


def require_organization_admin(
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> Actor:
    if actor.organization_role != OrganizationRole.ADMIN:
        raise HTTPException(status_code=403, detail="organization admin required")
    return actor


def require_csrf(
    claims: Annotated[SessionClaims, Depends(get_session_claims)],
    cookie_token: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
    submitted_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    try:
        validate_csrf(claims, cookie_token, submitted_token)
    except InvalidSessionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
