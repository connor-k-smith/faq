from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.provisioning import create_login_invitation, provision_identity
from app.domain.access import (
    AccessMutationError,
    create_project,
    deactivate_actor,
    grant_membership,
    revoke_membership,
    set_organization_role,
    set_project_archived,
)
from app.domain.enums import ActorKind, AskStatus, InitiativeKind, OrganizationRole
from app.domain.ports import IdentityClaims
from app.models.identity import Actor, Initiative, Membership
from app.models.outcomes import Event
from app.models.session import get_engine
from app.models.work import Ask
from tests.fakes import FixedClock

pytestmark = pytest.mark.integration


def test_admin_access_and_live_ask_transfer_invariants() -> None:
    clock = FixedClock(datetime(2026, 7, 25, 17, 0, tzinfo=UTC))
    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(connection)
    try:
        admin = _provision(
            session, clock, "access-admin", "access-admin@example.com", bootstrap=True
        )
        first_member = _invited_member(
            session, clock, admin.id, "access-first", "access-first@example.com"
        )
        second_member = _invited_member(
            session, clock, admin.id, "access-second", "access-second@example.com"
        )
        project = create_project(
            session,
            clock,
            acting_actor_id=admin.id,
            name="Atlas",
        )
        session.flush()

        assert session.get(Membership, (project.id, admin.id)) is None
        respondent = Actor(
            id=uuid4(),
            kind=ActorKind.HUMAN,
            organization_role=OrganizationRole.MEMBER,
            display_name="Respondent",
            firebase_uid=None,
            avatar_url=None,
            timezone="UTC",
            deleted_at=None,
            created_at=clock.now(),
        )
        session.add(respondent)
        session.flush()
        with pytest.raises(AccessMutationError, match="authenticated human"):
            grant_membership(
                session,
                clock,
                acting_actor_id=admin.id,
                project_id=project.id,
                actor_id=respondent.id,
            )
        grant_membership(
            session,
            clock,
            acting_actor_id=admin.id,
            project_id=project.id,
            actor_id=first_member.id,
        )
        grant_membership(
            session,
            clock,
            acting_actor_id=admin.id,
            project_id=project.id,
            actor_id=second_member.id,
        )
        initiative = Initiative(
            id=uuid4(),
            project_id=project.id,
            name="Pool matching",
            kind=InitiativeKind.FEATURE,
            description=None,
            external_refs={},
            created_by=first_member.id,
            created_at=clock.now(),
            archived_at=None,
        )
        ask = Ask(
            id=uuid4(),
            project_id=project.id,
            initiative_id=initiative.id,
            parent_ask_id=None,
            title="Confirm desired state",
            intro=None,
            created_by=first_member.id,
            deadline=None,
            default_note=None,
            status=AskStatus.DRAFT,
            owner_id=first_member.id,
            sent_at=None,
            closed_at=None,
            share_message=None,
            critiques_overridden=[],
            created_at=clock.now(),
        )
        session.add_all([initiative, ask])
        session.flush()

        with pytest.raises(AccessMutationError, match="ownership must be transferred"):
            revoke_membership(
                session,
                clock,
                acting_actor_id=admin.id,
                project_id=project.id,
                actor_id=first_member.id,
            )
        revoke_membership(
            session,
            clock,
            acting_actor_id=admin.id,
            project_id=project.id,
            actor_id=first_member.id,
            transfer_to_actor_id=second_member.id,
        )
        assert ask.owner_id == second_member.id

        with pytest.raises(AccessMutationError, match="draft or sent Ask"):
            set_project_archived(
                session,
                clock,
                acting_actor_id=admin.id,
                project_id=project.id,
                archived=True,
            )
        with pytest.raises(AccessMutationError, match="final active"):
            set_organization_role(
                session,
                clock,
                acting_actor_id=admin.id,
                actor_id=admin.id,
                role=OrganizationRole.MEMBER,
            )
        set_organization_role(
            session,
            clock,
            acting_actor_id=admin.id,
            actor_id=second_member.id,
            role=OrganizationRole.ADMIN,
        )
        set_organization_role(
            session,
            clock,
            acting_actor_id=admin.id,
            actor_id=admin.id,
            role=OrganizationRole.MEMBER,
        )
        assert admin.organization_role == OrganizationRole.MEMBER
        with pytest.raises(AccessMutationError, match="final active"):
            deactivate_actor(
                session,
                clock,
                acting_actor_id=second_member.id,
                actor_id=second_member.id,
                transfer_to_actor_id=admin.id,
            )
        set_organization_role(
            session,
            clock,
            acting_actor_id=second_member.id,
            actor_id=admin.id,
            role=OrganizationRole.ADMIN,
        )
        grant_membership(
            session,
            clock,
            acting_actor_id=admin.id,
            project_id=project.id,
            actor_id=admin.id,
        )
        deactivate_actor(
            session,
            clock,
            acting_actor_id=admin.id,
            actor_id=second_member.id,
            transfer_to_actor_id=admin.id,
        )
        assert second_member.deleted_at == clock.now()
        assert ask.owner_id == admin.id
        deactivated_membership = session.get(Membership, (project.id, second_member.id))
        assert deactivated_membership is not None
        assert deactivated_membership.revoked_at == clock.now()
        event_types = set(session.scalars(select(Event.type)))
        assert {"actor.deactivated", "ask.ownership_transferred"} <= event_types
        assert (
            session.scalar(
                select(Membership.revoked_at).where(
                    Membership.project_id == project.id,
                    Membership.actor_id == first_member.id,
                )
            )
            == clock.now()
        )
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _invited_member(
    session: Session,
    clock: FixedClock,
    admin_id: UUID,
    uid: str,
    email: str,
) -> Actor:
    create_login_invitation(session, clock, acting_actor_id=admin_id, email=email)
    return _provision(session, clock, uid, email)


def _provision(
    session: Session, clock: FixedClock, uid: str, email: str, *, bootstrap: bool = False
) -> Actor:
    return provision_identity(
        session,
        clock,
        IdentityClaims(uid=uid, email=email, email_verified=True, display_name=uid),
        bootstrap_admin_email=email if bootstrap else "access-admin@example.com",
    )
