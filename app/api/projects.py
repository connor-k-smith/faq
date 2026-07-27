from collections.abc import Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_actor, get_db_session, require_csrf
from app.api.unit_of_work import run_command
from app.domain.enums import AskStatus, DecisionState, InitiativeKind
from app.domain.initiatives import (
    InitiativeMutationError,
    create_initiative,
    set_initiative_archived,
    update_initiative,
)
from app.domain.ports import SystemClock
from app.models.identity import Actor, Initiative, Membership, Project
from app.models.outcomes import Decision
from app.models.work import Ask

router = APIRouter(prefix="/api/projects", tags=["projects"])
CurrentActor = Annotated[Actor, Depends(get_current_actor)]
DatabaseSession = Annotated[Session, Depends(get_db_session)]


class ProjectSummary(BaseModel):
    id: UUID
    name: str
    description: str | None
    archived: bool


class AskSummary(BaseModel):
    id: UUID
    title: str
    status: AskStatus
    created_at: datetime


class DecisionSummary(BaseModel):
    id: UUID
    ask_id: UUID
    statement: str
    committed_at: datetime


class InitiativeSummary(BaseModel):
    id: UUID
    name: str
    kind: InitiativeKind
    description: str | None
    archived: bool
    read_only: bool
    unresolved_count: int
    latest_activity_at: datetime
    asks: list[AskSummary]
    recent_decisions: list[DecisionSummary]


class ProjectLanding(BaseModel):
    project: ProjectSummary
    read_only: bool
    initiatives: list[InitiativeSummary]


class InitiativeWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: InitiativeKind
    description: str | None = Field(default=None, max_length=2000)


@router.get("", response_model=list[ProjectSummary])
def list_projects(actor: CurrentActor, session: DatabaseSession) -> list[ProjectSummary]:
    projects = session.scalars(
        select(Project)
        .join(Membership, Membership.project_id == Project.id)
        .where(Membership.actor_id == actor.id, Membership.revoked_at.is_(None))
        .order_by(Project.archived_at.is_not(None), Project.name, Project.id)
    )
    return [_project_summary(project) for project in projects]


@router.get("/{project_id}", response_model=ProjectLanding)
def project_landing(
    project_id: UUID, actor: CurrentActor, session: DatabaseSession
) -> ProjectLanding:
    project = _project_for_member(session, project_id, actor.id)
    initiatives = list(
        session.scalars(
            select(Initiative)
            .where(Initiative.project_id == project.id)
            .order_by(Initiative.archived_at.is_not(None), Initiative.name, Initiative.id)
        )
    )
    return ProjectLanding(
        project=_project_summary(project),
        read_only=project.archived_at is not None,
        initiatives=_initiative_summaries(session, project, initiatives),
    )


@router.get(
    "/{project_id}/initiatives/{initiative_id}", response_model=InitiativeSummary
)
def initiative_history(
    project_id: UUID,
    initiative_id: UUID,
    actor: CurrentActor,
    session: DatabaseSession,
) -> InitiativeSummary:
    project = _project_for_member(session, project_id, actor.id)
    initiative = session.scalar(
        select(Initiative).where(
            Initiative.id == initiative_id, Initiative.project_id == project.id
        )
    )
    if initiative is None:
        raise HTTPException(status_code=404, detail="Initiative not found")
    return _initiative_summaries(session, project, [initiative])[0]


@router.post(
    "/{project_id}/initiatives",
    response_model=InitiativeSummary,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def add_initiative(
    project_id: UUID,
    body: InitiativeWrite,
    actor: CurrentActor,
    session: DatabaseSession,
) -> InitiativeSummary:
    initiative = _mutate(
        session,
        lambda: create_initiative(
            session,
            SystemClock(),
            acting_actor_id=actor.id,
            project_id=project_id,
            name=body.name,
            kind=body.kind,
            description=body.description,
        ),
    )
    project = _project_for_member(session, project_id, actor.id)
    return _initiative_summaries(session, project, [initiative])[0]


@router.put(
    "/{project_id}/initiatives/{initiative_id}",
    response_model=InitiativeSummary,
    dependencies=[Depends(require_csrf)],
)
def edit_initiative(
    project_id: UUID,
    initiative_id: UUID,
    body: InitiativeWrite,
    actor: CurrentActor,
    session: DatabaseSession,
) -> InitiativeSummary:
    initiative = _mutate(
        session,
        lambda: update_initiative(
            session,
            SystemClock(),
            acting_actor_id=actor.id,
            project_id=project_id,
            initiative_id=initiative_id,
            name=body.name,
            kind=body.kind,
            description=body.description,
        ),
    )
    project = _project_for_member(session, project_id, actor.id)
    return _initiative_summaries(session, project, [initiative])[0]


@router.post(
    "/{project_id}/initiatives/{initiative_id}/archive",
    dependencies=[Depends(require_csrf)],
)
def archive_initiative(
    project_id: UUID,
    initiative_id: UUID,
    actor: CurrentActor,
    session: DatabaseSession,
) -> dict[str, bool]:
    _set_archived(session, actor.id, project_id, initiative_id, archived=True)
    return {"archived": True}


@router.post(
    "/{project_id}/initiatives/{initiative_id}/reactivate",
    dependencies=[Depends(require_csrf)],
)
def reactivate_initiative(
    project_id: UUID,
    initiative_id: UUID,
    actor: CurrentActor,
    session: DatabaseSession,
) -> dict[str, bool]:
    _set_archived(session, actor.id, project_id, initiative_id, archived=False)
    return {"archived": False}


def _set_archived(
    session: Session,
    actor_id: UUID,
    project_id: UUID,
    initiative_id: UUID,
    *,
    archived: bool,
) -> None:
    _mutate(
        session,
        lambda: set_initiative_archived(
            session,
            SystemClock(),
            acting_actor_id=actor_id,
            project_id=project_id,
            initiative_id=initiative_id,
            archived=archived,
        ),
    )


def _project_for_member(session: Session, project_id: UUID, actor_id: UUID) -> Project:
    project = session.scalar(
        select(Project)
        .join(Membership, Membership.project_id == Project.id)
        .where(
            Project.id == project_id,
            Membership.actor_id == actor_id,
            Membership.revoked_at.is_(None),
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _initiative_summaries(
    session: Session, project: Project, initiatives: list[Initiative]
) -> list[InitiativeSummary]:
    if not initiatives:
        return []
    initiative_ids = [initiative.id for initiative in initiatives]
    asks = list(
        session.scalars(
            select(Ask)
            .where(Ask.initiative_id.in_(initiative_ids))
            .order_by(Ask.created_at.desc(), Ask.id)
        )
    )
    decisions = list(
        session.execute(
            select(Decision, Ask.initiative_id)
            .join(Ask, Ask.id == Decision.ask_id)
            .where(
                Ask.initiative_id.in_(initiative_ids),
                Decision.state == DecisionState.COMMITTED,
            )
            .order_by(Decision.committed_at.desc(), Decision.id)
        ).tuples()
    )
    return [
        _initiative_summary(project, initiative, asks, decisions)
        for initiative in initiatives
    ]


def _initiative_summary(
    project: Project,
    initiative: Initiative,
    asks: list[Ask],
    decisions: list[tuple[Decision, UUID]],
) -> InitiativeSummary:
    initiative_asks = [ask for ask in asks if ask.initiative_id == initiative.id]
    initiative_decisions = [decision for decision, id_ in decisions if id_ == initiative.id]
    activity = [initiative.created_at]
    activity.extend(ask.created_at for ask in initiative_asks)
    activity.extend(
        decision.committed_at
        for decision in initiative_decisions
        if decision.committed_at is not None
    )
    return InitiativeSummary(
        id=initiative.id,
        name=initiative.name,
        kind=initiative.kind,
        description=initiative.description,
        archived=initiative.archived_at is not None,
        read_only=project.archived_at is not None or initiative.archived_at is not None,
        unresolved_count=sum(
            ask.status in (AskStatus.DRAFT, AskStatus.SENT) for ask in initiative_asks
        ),
        latest_activity_at=max(activity),
        asks=[
            AskSummary(
                id=ask.id, title=ask.title, status=ask.status, created_at=ask.created_at
            )
            for ask in initiative_asks
        ],
        recent_decisions=[
            DecisionSummary(
                id=decision.id,
                ask_id=decision.ask_id,
                statement=decision.statement or "",
                committed_at=decision.committed_at or decision.created_at,
            )
            for decision in initiative_decisions[:3]
        ],
    )


def _project_summary(project: Project) -> ProjectSummary:
    return ProjectSummary(
        id=project.id,
        name=project.name,
        description=project.description,
        archived=project.archived_at is not None,
    )


def _mutate[Result](session: Session, operation: Callable[[], Result]) -> Result:
    return run_command(
        session,
        operation,
        conflict_errors=(InitiativeMutationError,),
        integrity_detail="an active Initiative already uses that name",
    )
