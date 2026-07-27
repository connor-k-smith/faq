from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.provisioning import (
    AdmissionDeniedError,
    create_login_invitation,
    provision_identity,
)
from app.domain.enums import OrganizationRole
from app.domain.events import EventName
from app.domain.ports import IdentityClaims
from app.models.outcomes import Event
from app.models.session import get_engine
from tests.fakes import FixedClock

pytestmark = pytest.mark.integration


def test_bootstrap_then_invitation_gated_provisioning_is_atomic() -> None:
    clock = FixedClock(datetime(2026, 7, 25, 17, 0, tzinfo=UTC))
    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(connection)
    try:
        admin = provision_identity(
            session,
            clock,
            IdentityClaims(
                uid="firebase-admin-test",
                email="Admin@Example.com",
                email_verified=True,
                display_name="Admin",
            ),
            bootstrap_admin_email="admin@example.com",
        )
        assert admin.organization_role == OrganizationRole.ADMIN

        invitation = create_login_invitation(
            session,
            clock,
            acting_actor_id=admin.id,
            email="Casey@Example.com ",
        )
        member = provision_identity(
            session,
            clock,
            IdentityClaims(
                uid="firebase-member-test",
                email="casey@example.com",
                email_verified=True,
                display_name="Casey",
            ),
            bootstrap_admin_email="admin@example.com",
        )
        session.flush()

        assert member.organization_role == OrganizationRole.MEMBER
        assert invitation.accepted_by == member.id
        assert invitation.accepted_at == clock.now()
        event_names = set(session.scalars(select(Event.type)))
        assert EventName.ACTOR_CREATED.value in event_names
        assert EventName.LOGIN_INVITATION_CONSUMED.value in event_names

        with pytest.raises(AdmissionDeniedError, match="no active login invitation"):
            provision_identity(
                session,
                clock,
                IdentityClaims(
                    uid="firebase-replay-test",
                    email="casey@example.com",
                    email_verified=True,
                ),
                bootstrap_admin_email="admin@example.com",
            )
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_unverified_identity_is_rejected_before_provisioning() -> None:
    with Session(get_engine()) as session, pytest.raises(
        AdmissionDeniedError, match="verified email"
    ):
        provision_identity(
            session,
            FixedClock(datetime(2026, 7, 25, tzinfo=UTC)),
            IdentityClaims(
                uid="unverified-test",
                email="person@example.com",
                email_verified=False,
            ),
            bootstrap_admin_email="person@example.com",
        )
