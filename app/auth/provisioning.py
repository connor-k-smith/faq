from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import ActorKind, ContactKind, OrganizationRole
from app.domain.events import EventName, emit_event
from app.domain.ports import Clock, IdentityClaims
from app.models.identity import Actor, ContactMethod, LoginInvitation, Organization


class AdmissionDeniedError(ValueError):
    pass


def provision_identity(
    session: Session,
    clock: Clock,
    claims: IdentityClaims,
    *,
    bootstrap_admin_email: str | None,
) -> Actor:
    if not claims.email_verified:
        raise AdmissionDeniedError("a verified email is required")

    existing = session.scalar(
        select(Actor).where(Actor.firebase_uid == claims.uid).with_for_update()
    )
    if existing is not None:
        if existing.deleted_at is not None:
            raise AdmissionDeniedError("actor is deactivated")
        return existing

    session.execute(select(Organization).where(Organization.id == 1).with_for_update()).scalar_one()
    normalized_email = normalize_email(claims.email)
    has_admin = session.scalar(
        select(func.count())
        .select_from(Actor)
        .where(
            Actor.kind == ActorKind.HUMAN,
            Actor.organization_role == OrganizationRole.ADMIN,
            Actor.firebase_uid.is_not(None),
            Actor.deleted_at.is_(None),
        )
    )

    invitation: LoginInvitation | None = None
    role = OrganizationRole.MEMBER
    if not has_admin:
        if not bootstrap_admin_email or normalized_email != normalize_email(bootstrap_admin_email):
            raise AdmissionDeniedError("identity is not the configured bootstrap administrator")
        role = OrganizationRole.ADMIN
    else:
        invitation = session.scalar(
            select(LoginInvitation)
            .where(
                func.lower(LoginInvitation.email) == normalized_email,
                LoginInvitation.accepted_at.is_(None),
                LoginInvitation.revoked_at.is_(None),
                LoginInvitation.expires_at > clock.now(),
            )
            .with_for_update()
        )
        if invitation is None:
            raise AdmissionDeniedError("no active login invitation matches this identity")

    actor = Actor(
        id=uuid4(),
        kind=ActorKind.HUMAN,
        organization_role=role,
        display_name=claims.display_name or normalized_email.split("@", 1)[0],
        firebase_uid=claims.uid,
        avatar_url=claims.avatar_url,
        timezone="UTC",
        deleted_at=None,
        created_at=clock.now(),
    )
    session.add(actor)
    session.flush()
    session.add(
        ContactMethod(
            id=uuid4(),
            actor_id=actor.id,
            kind=ContactKind.EMAIL,
            value=normalized_email,
            verified_at=clock.now(),
            opted_in_at=None,
            priority=0,
            quiet_hours=None,
            created_at=clock.now(),
        )
    )
    emit_event(
        session,
        clock,
        EventName.ACTOR_CREATED,
        actor_id=actor.id,
        data={"admission": "bootstrap" if invitation is None else "invitation"},
    )

    if invitation is not None:
        invitation.accepted_by = actor.id
        invitation.accepted_at = clock.now()
        emit_event(
            session,
            clock,
            EventName.LOGIN_INVITATION_CONSUMED,
            actor_id=actor.id,
            data={"invitation_id": str(invitation.id)},
        )
    return actor


def create_login_invitation(
    session: Session,
    clock: Clock,
    *,
    acting_actor_id: UUID,
    email: str,
) -> LoginInvitation:
    session.execute(select(Organization).where(Organization.id == 1).with_for_update()).scalar_one()
    actor = session.scalar(select(Actor).where(Actor.id == acting_actor_id).with_for_update())
    if (
        actor is None
        or actor.deleted_at is not None
        or actor.kind != ActorKind.HUMAN
        or actor.firebase_uid is None
        or actor.organization_role != OrganizationRole.ADMIN
    ):
        raise AdmissionDeniedError("active organization admin required")

    normalized_email = normalize_email(email)
    outstanding = list(
        session.scalars(
            select(LoginInvitation)
            .where(
                func.lower(LoginInvitation.email) == normalized_email,
                LoginInvitation.accepted_at.is_(None),
                LoginInvitation.revoked_at.is_(None),
            )
            .with_for_update()
        )
    )
    for invitation in outstanding:
        if invitation.expires_at > clock.now():
            raise AdmissionDeniedError("an active invitation already exists for this email")
        invitation.revoked_at = clock.now()

    invitation = LoginInvitation(
        id=uuid4(),
        email=normalized_email,
        invited_by=acting_actor_id,
        accepted_by=None,
        expires_at=clock.now() + timedelta(days=7),
        accepted_at=None,
        revoked_at=None,
        created_at=clock.now(),
    )
    session.add(invitation)
    emit_event(
        session,
        clock,
        EventName.LOGIN_INVITATION_CREATED,
        actor_id=acting_actor_id,
        data={"invitation_id": str(invitation.id)},
    )
    return invitation


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    local, separator, domain = normalized.partition("@")
    if not separator or not local or not domain:
        raise AdmissionDeniedError("valid email required")
    return normalized
