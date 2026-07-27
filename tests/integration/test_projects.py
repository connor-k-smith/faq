from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_actor, get_db_session, require_csrf
from app.auth.provisioning import create_login_invitation, provision_identity
from app.domain.access import create_project, grant_membership, set_project_archived
from app.domain.enums import AskStatus, InitiativeKind
from app.domain.initiatives import (
    InitiativeMutationError,
    create_initiative,
    set_initiative_archived,
)
from app.domain.ports import IdentityClaims
from app.main import create_app
from app.models.identity import Actor
from app.models.outcomes import Event
from app.models.session import get_engine
from app.models.work import Ask
from tests.fakes import FixedClock

pytestmark = pytest.mark.integration


def test_project_navigation_is_member_scoped_and_archives_are_guarded() -> None:
    clock = FixedClock(datetime(2026, 7, 26, 9, 0, tzinfo=UTC))
    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(connection)
    app = create_app()

    def override_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[require_csrf] = lambda: None
    try:
        admin = _provision(session, clock, "projects-admin", "projects-admin@example.com", True)
        member = _invite_member(
            session, clock, admin, "projects-member", "projects-member@example.com"
        )
        outsider = _invite_member(
            session, clock, admin, "projects-outsider", "projects-outsider@example.com"
        )
        project = create_project(
            session, clock, acting_actor_id=admin.id, name="Atlas", description="Planning platform"
        )
        session.flush()
        grant_membership(
            session,
            clock,
            acting_actor_id=admin.id,
            project_id=project.id,
            actor_id=member.id,
        )
        initiative = create_initiative(
            session,
            clock,
            acting_actor_id=member.id,
            project_id=project.id,
            name="Pool matching",
            kind=InitiativeKind.FEATURE,
        )
        session.flush()
        with pytest.raises(InitiativeMutationError, match="already uses"):
            create_initiative(
                session,
                clock,
                acting_actor_id=member.id,
                project_id=project.id,
                name=" pool MATCHING ",
                kind=InitiativeKind.WORKSTREAM,
            )
        ask = Ask(
            id=uuid4(),
            project_id=project.id,
            initiative_id=initiative.id,
            parent_ask_id=None,
            title="Confirm desired state",
            intro=None,
            created_by=member.id,
            deadline=None,
            default_note=None,
            status=AskStatus.DRAFT,
            owner_id=member.id,
            sent_at=None,
            closed_at=None,
            share_message=None,
            critiques_overridden=[],
            created_at=clock.now(),
        )
        session.add(ask)
        session.flush()

        with pytest.raises(InitiativeMutationError, match="draft or sent Ask"):
            set_initiative_archived(
                session,
                clock,
                acting_actor_id=member.id,
                project_id=project.id,
                initiative_id=initiative.id,
                archived=True,
            )

        app.dependency_overrides[get_current_actor] = lambda: member
        with TestClient(app) as client:
            projects = client.get("/api/projects")
            landing = client.get(f"/api/projects/{project.id}")
        assert [item["name"] for item in projects.json()] == ["Atlas"]
        assert landing.status_code == 200
        assert landing.json()["initiatives"][0]["unresolved_count"] == 1
        assert landing.json()["initiatives"][0]["asks"][0]["title"] == ask.title

        app.dependency_overrides[get_current_actor] = lambda: outsider
        with TestClient(app) as client:
            assert client.get("/api/projects").json() == []
            assert client.get(f"/api/projects/{project.id}").status_code == 404

        ask.status = AskStatus.CLOSED
        ask.closed_at = clock.now()
        set_initiative_archived(
            session,
            clock,
            acting_actor_id=member.id,
            project_id=project.id,
            initiative_id=initiative.id,
            archived=True,
        )
        set_project_archived(
            session,
            clock,
            acting_actor_id=admin.id,
            project_id=project.id,
            archived=True,
        )
        app.dependency_overrides[get_current_actor] = lambda: member
        with TestClient(app) as client:
            archived_landing = client.get(f"/api/projects/{project.id}")
        assert archived_landing.json()["read_only"] is True
        assert archived_landing.json()["initiatives"][0]["read_only"] is True
        with pytest.raises(InitiativeMutationError, match="archived Project"):
            create_initiative(
                session,
                clock,
                acting_actor_id=member.id,
                project_id=project.id,
                name="Read only",
                kind=InitiativeKind.OTHER,
            )
        assert "initiative.archived" in set(session.scalars(select(Event.type)))
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _invite_member(
    session: Session, clock: FixedClock, admin: Actor, uid: str, email: str
) -> Actor:
    create_login_invitation(session, clock, acting_actor_id=admin.id, email=email)
    return _provision(session, clock, uid, email, False)


def _provision(
    session: Session, clock: FixedClock, uid: str, email: str, bootstrap: bool
) -> Actor:
    return provision_identity(
        session,
        clock,
        IdentityClaims(uid=uid, email=email, email_verified=True, display_name=uid),
        bootstrap_admin_email=email if bootstrap else "projects-admin@example.com",
    )
