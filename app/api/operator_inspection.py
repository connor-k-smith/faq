from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.domain.enums import AskStatus, OrganizationRole
from app.domain.events import EventName, emit_event
from app.domain.ports import SystemClock
from app.models.identity import Actor, ContactMethod, Membership, Project
from app.models.outcomes import Decision, Event, Response
from app.models.work import Ask, AskRecipient, Assignment, Question
from app.operator_identity import OperatorPrincipal

router = APIRouter(prefix="/admin", tags=["operator"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]
_SENSITIVE_EVENT_FIELDS = {
    "authorization",
    "cookie",
    "csrf",
    "password",
    "secret",
    "session",
    "token",
    "token_hash",
}


class OperatorRecord(BaseModel):
    id: str
    label: str
    state: str
    detail: dict[str, object] = Field(default_factory=dict)


class ProjectOperation(BaseModel):
    name: str | None = None
    description: str | None = None
    archived: bool | None = None
    reason: str = Field(min_length=3, max_length=1000)


class MergeRequest(BaseModel):
    source_actor_id: UUID
    target_actor_id: UUID
    reason: str = Field(min_length=3, max_length=1000)


class PurgeRequest(BaseModel):
    scope: Literal["project", "actor"]
    scope_id: UUID
    reason: str = Field(min_length=3, max_length=1000)


@router.get("/inspect/{entity}", response_model=list[OperatorRecord])
def inspect_records(
    entity: Literal[
        "actors", "projects", "asks", "credentials", "responses", "decisions", "events"
    ],
    session: DatabaseSession,
    limit: int = 100,
) -> list[OperatorRecord]:
    limit = max(1, min(limit, 500))
    if entity == "actors":
        return [
            OperatorRecord(
                id=str(item.id),
                label=item.display_name,
                state="deleted" if item.deleted_at else item.organization_role.value,
                detail={"kind": item.kind.value, "timezone": item.timezone},
            )
            for item in session.scalars(
                select(Actor).order_by(Actor.created_at.desc()).limit(limit)
            )
        ]
    if entity == "projects":
        return [
            OperatorRecord(
                id=str(item.id),
                label=item.name,
                state="archived" if item.archived_at else "active",
                detail={"description": item.description or ""},
            )
            for item in session.scalars(
                select(Project).order_by(Project.created_at.desc()).limit(limit)
            )
        ]
    if entity == "asks":
        return [
            OperatorRecord(
                id=str(item.id),
                label=item.title,
                state=item.status.value,
                detail={"project_id": str(item.project_id), "owner_id": str(item.owner_id)},
            )
            for item in session.scalars(select(Ask).order_by(Ask.created_at.desc()).limit(limit))
        ]
    if entity == "credentials":
        return [
            OperatorRecord(
                id=str(item.id),
                label=item.display_name,
                state="revoked" if item.revoked_at else "active",
                detail={
                    "ask_id": str(item.ask_id),
                    "issued": item.token_issued_at is not None,
                    "session_version": item.session_version,
                },
            )
            for item in session.scalars(
                select(AskRecipient).order_by(AskRecipient.created_at.desc()).limit(limit)
            )
        ]
    if entity == "responses":
        return [
            OperatorRecord(
                id=str(item.id),
                label=f"Response v{item.version}",
                state=item.disposition.value,
                detail={
                    "assignment_id": str(item.assignment_id),
                    "created_at": item.created_at.isoformat(),
                },
            )
            for item in session.scalars(
                select(Response).order_by(Response.created_at.desc()).limit(limit)
            )
        ]
    if entity == "decisions":
        return [
            OperatorRecord(
                id=str(item.id),
                label=item.statement or "Uncommitted Decision",
                state=item.state.value,
                detail={"ask_id": str(item.ask_id), "question_id": str(item.question_id)},
            )
            for item in session.scalars(
                select(Decision).order_by(Decision.created_at.desc()).limit(limit)
            )
        ]
    return [
        OperatorRecord(
            id=str(item.id),
            label=item.type,
            state="recorded",
            detail={
                "at": item.at.isoformat(),
                "project_id": str(item.project_id) if item.project_id else "",
                "data": _redact_event_data(item.data),
            },
        )
        for item in session.scalars(
            select(Event).order_by(Event.at.desc(), Event.id.desc()).limit(limit)
        )
    ]


def _redact_event_data(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "[redacted]"
            if key.lower() in _SENSITIVE_EVENT_FIELDS
            else _redact_event_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_event_data(item) for item in value]
    return value


@router.post("/projects/{project_id}", response_model=OperatorRecord)
def emergency_project_operation(
    project_id: UUID,
    body: ProjectOperation,
    session: DatabaseSession,
    principal: OperatorPrincipal,
) -> OperatorRecord:
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if body.archived is True:
        live = session.scalar(
            select(func.count())
            .select_from(Ask)
            .where(Ask.project_id == project.id, Ask.status.in_([AskStatus.DRAFT, AskStatus.SENT]))
        )
        if live:
            raise HTTPException(status_code=409, detail="Project has live Asks")
    before = {
        "name": project.name,
        "description": project.description,
        "archived": project.archived_at is not None,
    }
    if body.name is not None:
        project.name = body.name.strip() or project.name
    if body.description is not None:
        project.description = body.description.strip() or None
    if body.archived is not None:
        project.archived_at = SystemClock().now() if body.archived else None
    emit_event(
        session,
        SystemClock(),
        EventName.PROJECT_UPDATED,
        project_id=project.id,
        data={
            "source": "operator_emergency",
            "operator": principal.email,
            "reason": body.reason,
            "before": before,
            "after": {
                "name": project.name,
                "description": project.description,
                "archived": project.archived_at is not None,
            },
        },
    )
    session.commit()
    return OperatorRecord(
        id=str(project.id),
        label=project.name,
        state="archived" if project.archived_at else "active",
    )


@router.post("/actors/merge", response_model=OperatorRecord)
def merge_actor(
    body: MergeRequest,
    session: DatabaseSession,
    principal: OperatorPrincipal,
) -> OperatorRecord:
    if body.source_actor_id == body.target_actor_id:
        raise HTTPException(status_code=409, detail="source and target must differ")
    actors = list(
        session.scalars(
            select(Actor)
            .where(Actor.id.in_([body.source_actor_id, body.target_actor_id]))
            .order_by(Actor.id)
            .with_for_update()
        )
    )
    if len(actors) != 2:
        raise HTTPException(status_code=404, detail="Actor not found")
    source = next(item for item in actors if item.id == body.source_actor_id)
    target = next(item for item in actors if item.id == body.target_actor_id)
    conflicts = sum(
        (session.scalar(select(func.count()).select_from(model).where(column == source.id)) or 0)
        for model, column in (
            (Membership, Membership.actor_id),
            (Ask, Ask.created_by),
            (Ask, Ask.owner_id),
            (Question, Question.created_by),
            (AskRecipient, AskRecipient.actor_id),
            (Assignment, Assignment.actor_id),
        )
    )
    if conflicts or source.deleted_at is not None or target.deleted_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Actor merge requires an inactive shell without Project activity",
        )
    if source.firebase_uid and target.firebase_uid:
        raise HTTPException(status_code=409, detail="both Actors have authenticated identities")
    if source.organization_role == OrganizationRole.ADMIN:
        raise HTTPException(
            status_code=409, detail="organization admins must be demoted before merge"
        )
    source_contacts = set(
        session.execute(
            select(ContactMethod.kind, ContactMethod.value).where(
                ContactMethod.actor_id == source.id
            )
        ).tuples()
    )
    target_contacts = set(
        session.execute(
            select(ContactMethod.kind, ContactMethod.value).where(
                ContactMethod.actor_id == target.id
            )
        ).tuples()
    )
    if source_contacts & target_contacts:
        raise HTTPException(status_code=409, detail="Actors have duplicate contact methods")
    if source.firebase_uid:
        target.firebase_uid = source.firebase_uid
        target.avatar_url = source.avatar_url or target.avatar_url
        source.firebase_uid = None
    session.execute(
        update(ContactMethod).where(ContactMethod.actor_id == source.id).values(actor_id=target.id)
    )
    source.deleted_at = SystemClock().now()
    emit_event(
        session,
        SystemClock(),
        EventName.ACTOR_MERGED,
        actor_id=target.id,
        data={
            "source_actor_id": str(source.id),
            "target_actor_id": str(target.id),
            "operator": principal.email,
            "reason": body.reason,
        },
    )
    session.commit()
    return OperatorRecord(
        id=str(target.id),
        label=target.display_name,
        state="merged",
        detail={"source_actor_id": str(source.id)},
    )


@router.post("/purges/request", response_model=OperatorRecord)
def request_purge(
    body: PurgeRequest,
    session: DatabaseSession,
    principal: OperatorPrincipal,
) -> OperatorRecord:
    project_id = body.scope_id if body.scope == "project" else None
    emit_event(
        session,
        SystemClock(),
        EventName.PURGE_REQUESTED,
        project_id=project_id,
        data={
            "scope": body.scope,
            "scope_id": str(body.scope_id),
            "operator": principal.email,
            "reason": body.reason,
            "backup_caveat": "Data may remain in backups and PITR logs until retention expiry",
            "execution": "requires separately privileged database path",
        },
    )
    session.commit()
    return OperatorRecord(
        id=str(body.scope_id),
        label=f"{body.scope} purge request",
        state="awaiting_separate_authorization",
    )
