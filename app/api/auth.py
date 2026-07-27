import hmac
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import (
    CSRF_COOKIE,
    LOGIN_CSRF_COOKIE,
    SESSION_COOKIE,
    get_current_actor,
    get_db_session,
    get_identity_verifier,
    get_session_codec,
    require_csrf,
)
from app.auth.provisioning import AdmissionDeniedError, provision_identity
from app.auth.sessions import SessionCodec
from app.config import Settings, get_settings
from app.domain.ports import IdentityVerifier, SystemClock
from app.domain.tokens import SecureTokenGenerator
from app.models.identity import Actor

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class ExchangeRequest(BaseModel):
    id_token: str


class FirebaseWebConfig(BaseModel):
    api_key: str
    auth_domain: str
    project_id: str
    app_id: str


class AuthConfigResponse(BaseModel):
    provider: str
    firebase: FirebaseWebConfig


class ActorResponse(BaseModel):
    id: str
    display_name: str
    organization_role: str

    @classmethod
    def from_actor(cls, actor: Actor) -> "ActorResponse":
        return cls(
            id=str(actor.id),
            display_name=actor.display_name,
            organization_role=actor.organization_role.value,
        )


@router.get("/csrf", status_code=204)
def issue_login_csrf(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    token = SecureTokenGenerator().urlsafe()
    response.set_cookie(
        LOGIN_CSRF_COOKIE,
        token,
        secure=settings.environment == "production",
        httponly=False,
        samesite="lax",
        path="/",
        max_age=600,
    )


@router.get("/config", response_model=AuthConfigResponse)
def auth_config(settings: Annotated[Settings, Depends(get_settings)]) -> AuthConfigResponse:
    values = (
        settings.firebase_api_key,
        settings.firebase_auth_domain,
        settings.firebase_project_id,
        settings.firebase_app_id,
    )
    if any(value is None for value in values):
        raise HTTPException(status_code=503, detail="Firebase authentication is not configured")
    api_key, auth_domain, project_id, app_id = values
    assert api_key is not None
    assert auth_domain is not None
    assert project_id is not None
    assert app_id is not None
    return AuthConfigResponse(
        provider="password",
        firebase=FirebaseWebConfig(
            api_key=api_key, auth_domain=auth_domain, project_id=project_id, app_id=app_id
        ),
    )


@router.post("/exchange", response_model=ActorResponse)
async def exchange_identity(
    body: ExchangeRequest,
    response: Response,
    verifier: Annotated[IdentityVerifier, Depends(get_identity_verifier)],
    codec: Annotated[SessionCodec, Depends(get_session_codec)],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    login_csrf_cookie: Annotated[str | None, Cookie(alias=LOGIN_CSRF_COOKIE)] = None,
    login_csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ActorResponse:
    if not login_csrf_cookie or not login_csrf_header or not hmac.compare_digest(
        login_csrf_cookie, login_csrf_header
    ):
        raise HTTPException(status_code=403, detail="invalid login CSRF token")
    try:
        claims = await verifier.verify(body.id_token)
        with session.begin():
            actor = provision_identity(
                session,
                SystemClock(),
                claims,
                bootstrap_admin_email=settings.bootstrap_admin_email,
            )
    except (AdmissionDeniedError, ValueError) as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

    _set_session_cookies(response, actor, codec, settings)
    response.delete_cookie(LOGIN_CSRF_COOKIE, path="/")
    return ActorResponse.from_actor(actor)


@router.get("/session", response_model=ActorResponse)
def read_session(actor: Annotated[Actor, Depends(get_current_actor)]) -> ActorResponse:
    return ActorResponse.from_actor(actor)


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _set_session_cookies(
    response: Response, actor: Actor, codec: SessionCodec, settings: Settings
) -> None:
    encoded, session_claims = codec.issue(actor.id)
    secure = settings.environment == "production"
    response.set_cookie(
        SESSION_COOKIE,
        encoded,
        secure=secure,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=settings.session_lifetime_hours * 3600,
    )
    response.set_cookie(
        CSRF_COOKIE,
        session_claims.csrf_token,
        secure=secure,
        httponly=False,
        samesite="lax",
        path="/",
        max_age=settings.session_lifetime_hours * 3600,
    )
