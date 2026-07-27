from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_db_session,
    require_csrf,
    require_organization_admin,
)
from app.api.unit_of_work import run_command
from app.auth.provisioning import AdmissionDeniedError, create_login_invitation
from app.domain.access import (
    AccessMutationError,
    create_project,
    deactivate_actor,
    grant_membership,
    revoke_login_invitation,
    revoke_membership,
    set_organization_role,
    set_project_archived,
)
from app.domain.enums import ContactKind, OrganizationRole
from app.domain.ports import SystemClock
from app.models.identity import Actor, ContactMethod, LoginInvitation, Membership, Project

router = APIRouter(prefix="/api/admin", tags=["organization administration"])
AdminActor = Annotated[Actor, Depends(require_organization_admin)]
DatabaseSession = Annotated[Session, Depends(get_db_session)]


class InvitationCreate(BaseModel):
    email: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class MembershipCreate(BaseModel):
    actor_id: UUID
    role: str | None = Field(default=None, max_length=100)


class RoleUpdate(BaseModel):
    role: Literal["member", "admin"]


class AccessActor(BaseModel):
    id: UUID
    display_name: str
    email: str | None
    role: OrganizationRole
    authenticated: bool
    deactivated: bool


class AccessProject(BaseModel):
    id: UUID
    name: str
    archived: bool
    membership_count: int


class AccessInvitation(BaseModel):
    id: UUID
    email: str
    expires_at: datetime


class AccessMembership(BaseModel):
    project_id: UUID
    actor_id: UUID
    role: str | None


class AccessOverview(BaseModel):
    actors: list[AccessActor]
    projects: list[AccessProject]
    invitations: list[AccessInvitation]
    memberships: list[AccessMembership]


@router.get("/access", response_model=AccessOverview)
def access_overview(_admin: AdminActor, session: DatabaseSession) -> AccessOverview:
    actors = list(session.scalars(select(Actor).order_by(Actor.display_name, Actor.id)))
    projects = list(session.scalars(select(Project).order_by(Project.name, Project.id)))
    invitations = list(
        session.scalars(
            select(LoginInvitation)
            .where(LoginInvitation.accepted_at.is_(None), LoginInvitation.revoked_at.is_(None))
            .order_by(LoginInvitation.created_at.desc())
        )
    )
    membership_counts: dict[UUID, int] = dict(
        session.execute(
            select(Membership.project_id, func.count())
            .where(Membership.revoked_at.is_(None))
            .group_by(Membership.project_id)
        )
        .tuples()
        .all()
    )
    memberships = list(
        session.scalars(
            select(Membership)
            .where(Membership.revoked_at.is_(None))
            .order_by(Membership.project_id, Membership.created_at)
        )
    )
    emails: dict[UUID, str] = dict(
        session.execute(
            select(ContactMethod.actor_id, ContactMethod.value).where(
                ContactMethod.kind == ContactKind.EMAIL,
                ContactMethod.verified_at.is_not(None),
            )
        )
        .tuples()
        .all()
    )
    return AccessOverview(
        actors=[
            {
                "id": str(actor.id),
                "display_name": actor.display_name,
                "email": emails.get(actor.id),
                "role": actor.organization_role.value,
                "authenticated": actor.firebase_uid is not None,
                "deactivated": actor.deleted_at is not None,
            }
            for actor in actors
        ],
        projects=[
            {
                "id": str(project.id),
                "name": project.name,
                "archived": project.archived_at is not None,
                "membership_count": membership_counts.get(project.id, 0),
            }
            for project in projects
        ],
        invitations=[
            {
                "id": str(invitation.id),
                "email": invitation.email,
                "expires_at": invitation.expires_at,
            }
            for invitation in invitations
        ],
        memberships=[
            {
                "project_id": str(membership.project_id),
                "actor_id": str(membership.actor_id),
                "role": membership.role,
            }
            for membership in memberships
        ],
    )


@router.post("/invitations", status_code=201, dependencies=[Depends(require_csrf)])
def invite_user(
    body: InvitationCreate, admin: AdminActor, session: DatabaseSession
) -> dict[str, str]:
    try:
        invitation = create_login_invitation(
            session,
            SystemClock(),
            acting_actor_id=admin.id,
            email=body.email,
        )
        session.commit()
        return {"id": str(invitation.id), "email": invitation.email}
    except AdmissionDeniedError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete(
    "/invitations/{invitation_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def revoke_invitation(invitation_id: UUID, admin: AdminActor, session: DatabaseSession) -> None:
    _mutate(
        session,
        lambda: revoke_login_invitation(
            session,
            SystemClock(),
            acting_actor_id=admin.id,
            invitation_id=invitation_id,
        ),
    )


@router.post("/projects", status_code=201, dependencies=[Depends(require_csrf)])
def add_project(body: ProjectCreate, admin: AdminActor, session: DatabaseSession) -> dict[str, str]:
    project: Project = _mutate(
        session,
        lambda: create_project(
            session,
            SystemClock(),
            acting_actor_id=admin.id,
            name=body.name,
            description=body.description,
        ),
    )
    return {"id": str(project.id), "name": project.name}


@router.post("/projects/{project_id}/archive", dependencies=[Depends(require_csrf)])
def archive_project(
    project_id: UUID, admin: AdminActor, session: DatabaseSession
) -> dict[str, bool]:
    _mutate(
        session,
        lambda: set_project_archived(
            session,
            SystemClock(),
            acting_actor_id=admin.id,
            project_id=project_id,
            archived=True,
        ),
    )
    return {"archived": True}


@router.post("/projects/{project_id}/reactivate", dependencies=[Depends(require_csrf)])
def reactivate_project(
    project_id: UUID, admin: AdminActor, session: DatabaseSession
) -> dict[str, bool]:
    _mutate(
        session,
        lambda: set_project_archived(
            session,
            SystemClock(),
            acting_actor_id=admin.id,
            project_id=project_id,
            archived=False,
        ),
    )
    return {"archived": False}


@router.post(
    "/projects/{project_id}/memberships", status_code=201, dependencies=[Depends(require_csrf)]
)
def add_membership(
    project_id: UUID,
    body: MembershipCreate,
    admin: AdminActor,
    session: DatabaseSession,
) -> dict[str, str]:
    membership: Membership = _mutate(
        session,
        lambda: grant_membership(
            session,
            SystemClock(),
            acting_actor_id=admin.id,
            project_id=project_id,
            actor_id=body.actor_id,
            role=body.role,
        ),
    )
    return {"project_id": str(membership.project_id), "actor_id": str(membership.actor_id)}


@router.delete(
    "/projects/{project_id}/memberships/{actor_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def remove_membership(
    project_id: UUID,
    actor_id: UUID,
    admin: AdminActor,
    session: DatabaseSession,
    transfer_to: Annotated[UUID | None, Query()] = None,
) -> None:
    _mutate(
        session,
        lambda: revoke_membership(
            session,
            SystemClock(),
            acting_actor_id=admin.id,
            project_id=project_id,
            actor_id=actor_id,
            transfer_to_actor_id=transfer_to,
        ),
    )


@router.patch("/actors/{actor_id}/role", dependencies=[Depends(require_csrf)])
def update_role(
    actor_id: UUID, body: RoleUpdate, admin: AdminActor, session: DatabaseSession
) -> dict[str, str]:
    actor: Actor = _mutate(
        session,
        lambda: set_organization_role(
            session,
            SystemClock(),
            acting_actor_id=admin.id,
            actor_id=actor_id,
            role=OrganizationRole(body.role),
        ),
    )
    return {"id": str(actor.id), "role": actor.organization_role.value}


@router.delete(
    "/actors/{actor_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def deactivate_user(
    actor_id: UUID,
    admin: AdminActor,
    session: DatabaseSession,
    transfer_to: Annotated[UUID | None, Query()] = None,
) -> None:
    _mutate(
        session,
        lambda: deactivate_actor(
            session,
            SystemClock(),
            acting_actor_id=admin.id,
            actor_id=actor_id,
            transfer_to_actor_id=transfer_to,
        ),
    )


def _mutate[Result](session: Session, operation: Callable[[], Result]) -> Result:
    return run_command(session, operation, conflict_errors=(AccessMutationError,))
