from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import AskStatus, InitiativeKind
from app.domain.events import EventName, emit_event
from app.domain.ports import Clock
from app.models.identity import Initiative, Membership, Project
from app.models.work import Ask


class InitiativeMutationError(ValueError):
    pass


def create_initiative(
    session: Session,
    clock: Clock,
    *,
    acting_actor_id: UUID,
    project_id: UUID,
    name: str,
    kind: InitiativeKind,
    description: str | None = None,
) -> Initiative:
    project = _mutable_project(session, project_id, acting_actor_id)
    normalized_name = _normalized_name(name)
    _require_available_name(session, project.id, normalized_name)
    initiative = Initiative(
        id=uuid4(),
        project_id=project.id,
        name=normalized_name,
        kind=kind,
        description=description.strip() if description and description.strip() else None,
        external_refs={},
        created_by=acting_actor_id,
        created_at=clock.now(),
        archived_at=None,
    )
    session.add(initiative)
    emit_event(
        session,
        clock,
        EventName.INITIATIVE_CREATED,
        actor_id=acting_actor_id,
        project_id=project.id,
        data={"initiative_id": str(initiative.id), "name": initiative.name},
    )
    return initiative


def update_initiative(
    session: Session,
    clock: Clock,
    *,
    acting_actor_id: UUID,
    project_id: UUID,
    initiative_id: UUID,
    name: str,
    kind: InitiativeKind,
    description: str | None = None,
) -> Initiative:
    _mutable_project(session, project_id, acting_actor_id)
    initiative = _locked_initiative(session, project_id, initiative_id)
    if initiative.archived_at is not None:
        raise InitiativeMutationError("archived Initiative is read-only")
    normalized_name = _normalized_name(name)
    _require_available_name(session, project_id, normalized_name, excluding=initiative.id)
    initiative.name = normalized_name
    initiative.kind = kind
    initiative.description = description.strip() if description and description.strip() else None
    emit_event(
        session,
        clock,
        EventName.INITIATIVE_UPDATED,
        actor_id=acting_actor_id,
        project_id=project_id,
        data={"initiative_id": str(initiative.id), "name": initiative.name},
    )
    return initiative


def set_initiative_archived(
    session: Session,
    clock: Clock,
    *,
    acting_actor_id: UUID,
    project_id: UUID,
    initiative_id: UUID,
    archived: bool,
) -> Initiative:
    _mutable_project(session, project_id, acting_actor_id)
    initiative = _locked_initiative(session, project_id, initiative_id)
    if archived:
        if initiative.archived_at is not None:
            return initiative
        live_ask = session.scalar(
            select(Ask.id)
            .where(
                Ask.initiative_id == initiative.id,
                Ask.status.in_([AskStatus.DRAFT, AskStatus.SENT]),
            )
            .limit(1)
        )
        if live_ask is not None:
            raise InitiativeMutationError(
                "Initiative with a draft or sent Ask cannot be archived"
            )
        initiative.archived_at = clock.now()
        event_name = EventName.INITIATIVE_ARCHIVED
    else:
        if initiative.archived_at is None:
            return initiative
        _require_available_name(session, project_id, initiative.name, excluding=initiative.id)
        initiative.archived_at = None
        event_name = EventName.INITIATIVE_REACTIVATED
    emit_event(
        session,
        clock,
        event_name,
        actor_id=acting_actor_id,
        project_id=project_id,
        data={"initiative_id": str(initiative.id)},
    )
    return initiative


def _mutable_project(session: Session, project_id: UUID, actor_id: UUID) -> Project:
    project = session.scalar(
        select(Project)
        .join(Membership, Membership.project_id == Project.id)
        .where(
            Project.id == project_id,
            Membership.actor_id == actor_id,
            Membership.revoked_at.is_(None),
        )
        .with_for_update(of=Project)
    )
    if project is None:
        raise InitiativeMutationError("active Project membership required")
    if project.archived_at is not None:
        raise InitiativeMutationError("archived Project is read-only")
    return project


def _locked_initiative(
    session: Session, project_id: UUID, initiative_id: UUID
) -> Initiative:
    initiative = session.scalar(
        select(Initiative)
        .where(Initiative.id == initiative_id, Initiative.project_id == project_id)
        .with_for_update()
    )
    if initiative is None:
        raise InitiativeMutationError("Initiative not found")
    return initiative


def _normalized_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise InitiativeMutationError("Initiative name is required")
    return normalized


def _require_available_name(
    session: Session, project_id: UUID, name: str, *, excluding: UUID | None = None
) -> None:
    statement = select(Initiative.id).where(
        Initiative.project_id == project_id,
        Initiative.archived_at.is_(None),
        func.lower(Initiative.name) == name.lower(),
    )
    if excluding is not None:
        statement = statement.where(Initiative.id != excluding)
    if session.scalar(statement.limit(1)) is not None:
        raise InitiativeMutationError("an active Initiative already uses that name")
