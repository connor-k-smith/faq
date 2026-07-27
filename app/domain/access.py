from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import ActorKind, AskStatus, AssignmentState, OrganizationRole
from app.domain.events import EventName, emit_event
from app.domain.ports import Clock
from app.models.identity import Actor, LoginInvitation, Membership, Organization, Project
from app.models.work import Ask, AskRecipient, Assignment


class AccessMutationError(ValueError):
    pass


def require_admin(session: Session, actor_id: UUID, *, lock: bool = False) -> Actor:
    statement = select(Actor).where(Actor.id == actor_id)
    if lock:
        statement = statement.with_for_update()
    actor = session.scalar(statement)
    if (
        actor is None
        or actor.deleted_at is not None
        or actor.kind != ActorKind.HUMAN
        or actor.firebase_uid is None
        or actor.organization_role != OrganizationRole.ADMIN
    ):
        raise AccessMutationError("active organization admin required")
    return actor


def create_project(
    session: Session,
    clock: Clock,
    *,
    acting_actor_id: UUID,
    name: str,
    description: str | None = None,
) -> Project:
    require_admin(session, acting_actor_id)
    normalized_name = name.strip()
    if not normalized_name:
        raise AccessMutationError("project name is required")
    project = Project(
        id=uuid4(),
        name=normalized_name,
        aliases=[],
        description=description.strip() if description else None,
        external_refs={},
        created_by=acting_actor_id,
        created_at=clock.now(),
        archived_at=None,
    )
    session.add(project)
    emit_event(
        session,
        clock,
        EventName.PROJECT_CREATED,
        actor_id=acting_actor_id,
        project_id=project.id,
        data={"name": normalized_name},
    )
    return project


def set_project_archived(
    session: Session,
    clock: Clock,
    *,
    acting_actor_id: UUID,
    project_id: UUID,
    archived: bool,
) -> Project:
    require_admin(session, acting_actor_id)
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise AccessMutationError("project not found")
    if archived:
        live_ask = session.scalar(
            select(Ask.id)
            .where(Ask.project_id == project_id, Ask.status.in_([AskStatus.DRAFT, AskStatus.SENT]))
            .limit(1)
        )
        if live_ask is not None:
            raise AccessMutationError("project with a draft or sent Ask cannot be archived")
        project.archived_at = clock.now()
        event_name = EventName.PROJECT_ARCHIVED
    else:
        project.archived_at = None
        event_name = EventName.PROJECT_REACTIVATED
    emit_event(
        session,
        clock,
        event_name,
        actor_id=acting_actor_id,
        project_id=project_id,
    )
    return project


def grant_membership(
    session: Session,
    clock: Clock,
    *,
    acting_actor_id: UUID,
    project_id: UUID,
    actor_id: UUID,
    role: str | None = None,
) -> Membership:
    require_admin(session, acting_actor_id)
    project = session.get(Project, project_id)
    target = session.scalar(select(Actor).where(Actor.id == actor_id).with_for_update())
    if project is None:
        raise AccessMutationError("project not found")
    if (
        target is None
        or target.deleted_at is not None
        or target.kind != ActorKind.HUMAN
        or target.firebase_uid is None
    ):
        raise AccessMutationError("membership requires an active authenticated human Actor")
    membership = session.scalar(
        select(Membership)
        .where(Membership.project_id == project_id, Membership.actor_id == actor_id)
        .with_for_update()
    )
    if membership is None:
        membership = Membership(
            project_id=project_id,
            actor_id=actor_id,
            role=role,
            revoked_at=None,
            created_at=clock.now(),
        )
        session.add(membership)
    else:
        membership.role = role
        membership.revoked_at = None
    emit_event(
        session,
        clock,
        EventName.MEMBERSHIP_GRANTED,
        actor_id=acting_actor_id,
        project_id=project_id,
        data={"member_actor_id": str(actor_id)},
    )
    return membership


def revoke_membership(
    session: Session,
    clock: Clock,
    *,
    acting_actor_id: UUID,
    project_id: UUID,
    actor_id: UUID,
    transfer_to_actor_id: UUID | None = None,
) -> None:
    require_admin(session, acting_actor_id)
    membership = session.scalar(
        select(Membership)
        .where(Membership.project_id == project_id, Membership.actor_id == actor_id)
        .with_for_update()
    )
    if membership is None or membership.revoked_at is not None:
        raise AccessMutationError("active membership not found")
    owned_asks = list(
        session.scalars(
            select(Ask)
            .where(
                Ask.project_id == project_id,
                Ask.owner_id == actor_id,
                Ask.status.in_([AskStatus.DRAFT, AskStatus.SENT]),
            )
            .with_for_update()
        )
    )
    if owned_asks:
        replacement = _active_membership(session, project_id, transfer_to_actor_id)
        if replacement is None:
            raise AccessMutationError("live Ask ownership must be transferred before revocation")
        for ask in owned_asks:
            ask.owner_id = replacement.actor_id
            emit_event(
                session,
                clock,
                EventName.ASK_OWNERSHIP_TRANSFERRED,
                actor_id=acting_actor_id,
                project_id=project_id,
                ask_id=ask.id,
                data={"from": str(actor_id), "to": str(replacement.actor_id)},
            )
    membership.revoked_at = clock.now()
    emit_event(
        session,
        clock,
        EventName.MEMBERSHIP_REVOKED,
        actor_id=acting_actor_id,
        project_id=project_id,
        data={"member_actor_id": str(actor_id)},
    )


def set_organization_role(
    session: Session,
    clock: Clock,
    *,
    acting_actor_id: UUID,
    actor_id: UUID,
    role: OrganizationRole,
) -> Actor:
    require_admin(session, acting_actor_id)
    session.execute(select(Organization).where(Organization.id == 1).with_for_update()).scalar_one()
    target = session.scalar(select(Actor).where(Actor.id == actor_id).with_for_update())
    if target is None or target.deleted_at is not None or target.firebase_uid is None:
        raise AccessMutationError("active authenticated Actor required")
    previous = target.organization_role
    if previous == OrganizationRole.ADMIN and role != OrganizationRole.ADMIN:
        active_admins = session.scalar(
            select(func.count())
            .select_from(Actor)
            .where(
                Actor.kind == ActorKind.HUMAN,
                Actor.organization_role == OrganizationRole.ADMIN,
                Actor.firebase_uid.is_not(None),
                Actor.deleted_at.is_(None),
            )
        )
        if active_admins is None or active_admins <= 1:
            raise AccessMutationError("the final active organization admin cannot be removed")
    target.organization_role = role
    emit_event(
        session,
        clock,
        EventName.ACTOR_ROLE_CHANGED,
        actor_id=acting_actor_id,
        data={"target_actor_id": str(actor_id), "from": previous.value, "to": role.value},
    )
    return target


def deactivate_actor(
    session: Session,
    clock: Clock,
    *,
    acting_actor_id: UUID,
    actor_id: UUID,
    transfer_to_actor_id: UUID | None = None,
) -> Actor:
    require_admin(session, acting_actor_id)
    target = session.scalar(select(Actor).where(Actor.id == actor_id).with_for_update())
    if target is None or target.deleted_at is not None:
        raise AccessMutationError("active Actor not found")
    if target.organization_role == OrganizationRole.ADMIN:
        session.execute(
            select(Organization).where(Organization.id == 1).with_for_update()
        ).scalar_one()
        active_admins = session.scalar(
            select(func.count())
            .select_from(Actor)
            .where(
                Actor.kind == ActorKind.HUMAN,
                Actor.organization_role == OrganizationRole.ADMIN,
                Actor.firebase_uid.is_not(None),
                Actor.deleted_at.is_(None),
            )
        )
        if active_admins is None or active_admins <= 1:
            raise AccessMutationError("the final active organization admin cannot be deactivated")

    memberships = list(
        session.scalars(
            select(Membership)
            .where(Membership.actor_id == actor_id, Membership.revoked_at.is_(None))
            .order_by(Membership.project_id)
            .with_for_update()
        )
    )
    live_asks = list(
        session.scalars(
            select(Ask)
            .where(
                Ask.owner_id == actor_id,
                Ask.status.in_([AskStatus.DRAFT, AskStatus.SENT]),
            )
            .order_by(Ask.project_id, Ask.id)
            .with_for_update()
        )
    )
    replacements: dict[UUID, Membership] = {}
    for ask in live_asks:
        replacement = replacements.get(ask.project_id)
        if replacement is None:
            replacement = _active_membership(session, ask.project_id, transfer_to_actor_id)
            if replacement is None or replacement.actor_id == actor_id:
                raise AccessMutationError(
                    "live Ask ownership must be transferred before deactivation"
                )
            replacements[ask.project_id] = replacement
        ask.owner_id = replacement.actor_id
        emit_event(
            session,
            clock,
            EventName.ASK_OWNERSHIP_TRANSFERRED,
            actor_id=acting_actor_id,
            project_id=ask.project_id,
            ask_id=ask.id,
            data={"from": str(actor_id), "to": str(replacement.actor_id)},
        )

    now = clock.now()
    for membership in memberships:
        membership.revoked_at = now
        emit_event(
            session,
            clock,
            EventName.MEMBERSHIP_REVOKED,
            actor_id=acting_actor_id,
            project_id=membership.project_id,
            data={"member_actor_id": str(actor_id), "reason": "actor_deactivated"},
        )
    recipients = list(
        session.scalars(
            select(AskRecipient)
            .where(AskRecipient.actor_id == actor_id, AskRecipient.revoked_at.is_(None))
            .with_for_update()
        )
    )
    for recipient in recipients:
        recipient.revoked_at = now
        recipient.session_version += 1
        pending = list(
            session.scalars(
                select(Assignment).where(
                    Assignment.ask_recipient_id == recipient.id,
                    Assignment.state.in_([AssignmentState.PENDING, AssignmentState.BLOCKED]),
                )
            )
        )
        for assignment in pending:
            assignment.state = AssignmentState.WITHDRAWN
        emit_event(
            session,
            clock,
            EventName.RECIPIENT_REVOKED,
            actor_id=acting_actor_id,
            project_id=recipient.project_id,
            ask_id=recipient.ask_id,
            ask_recipient_id=recipient.id,
            data={"reason": "actor_deactivated"},
        )
    target.deleted_at = now
    emit_event(
        session,
        clock,
        EventName.ACTOR_DEACTIVATED,
        actor_id=acting_actor_id,
        data={"target_actor_id": str(actor_id)},
    )
    return target


def revoke_login_invitation(
    session: Session,
    clock: Clock,
    *,
    acting_actor_id: UUID,
    invitation_id: UUID,
) -> LoginInvitation:
    require_admin(session, acting_actor_id)
    invitation = session.scalar(
        select(LoginInvitation).where(LoginInvitation.id == invitation_id).with_for_update()
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
    ):
        raise AccessMutationError("active invitation not found")
    invitation.revoked_at = clock.now()
    emit_event(
        session,
        clock,
        EventName.LOGIN_INVITATION_REVOKED,
        actor_id=acting_actor_id,
        data={"invitation_id": str(invitation_id)},
    )
    return invitation


def _active_membership(
    session: Session, project_id: UUID, actor_id: UUID | None
) -> Membership | None:
    if actor_id is None:
        return None
    return session.scalar(
        select(Membership)
        .join(Actor, Actor.id == Membership.actor_id)
        .where(
            Membership.project_id == project_id,
            Membership.actor_id == actor_id,
            Membership.revoked_at.is_(None),
            Actor.deleted_at.is_(None),
            Actor.firebase_uid.is_not(None),
            Actor.kind == ActorKind.HUMAN,
        )
        .with_for_update()
    )
