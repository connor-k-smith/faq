import hashlib
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.unit_of_work import run_command
from app.domain.enums import AskStatus
from app.domain.events import EventName, emit_event
from app.domain.ports import SystemClock
from app.models.identity import Actor, Initiative, Membership, Project
from app.models.work import Ask, AskRecipient


class DraftConflict(ValueError):
    pass


def _authorize_ask_read(session: Session, ask_id: UUID, actor_id: UUID) -> None:
    allowed = session.scalar(
        select(Membership.actor_id)
        .join(Ask, Ask.project_id == Membership.project_id)
        .where(
            Ask.id == ask_id,
            Membership.actor_id == actor_id,
            Membership.revoked_at.is_(None),
        )
    )
    if allowed is None:
        raise HTTPException(status_code=404, detail="Ask not found")


def _mutable_parents(
    session: Session, project_id: UUID, initiative_id: UUID, actor_id: UUID
) -> tuple[Project, Initiative]:
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
        raise DraftConflict("active Project membership required")
    if project.archived_at is not None:
        raise DraftConflict("archived Project is read-only")
    initiative = session.scalar(
        select(Initiative)
        .where(Initiative.id == initiative_id, Initiative.project_id == project.id)
        .with_for_update()
    )
    if initiative is None:
        raise DraftConflict("Initiative not found")
    if initiative.archived_at is not None:
        raise DraftConflict("archived Initiative is read-only")
    return project, initiative


def _mutable_ask(
    session: Session,
    ask_id: UUID,
    actor_id: UUID,
    *,
    allowed_statuses: tuple[AskStatus, ...] = (AskStatus.DRAFT,),
) -> Ask:
    ask = session.scalar(select(Ask).where(Ask.id == ask_id).with_for_update())
    if ask is None:
        raise DraftConflict("Ask not found")
    _mutable_parents(session, ask.project_id, ask.initiative_id, actor_id)
    if ask.owner_id != actor_id:
        raise DraftConflict("only the Ask owner may edit this Ask")
    if ask.status not in allowed_statuses:
        raise DraftConflict("Ask is read-only in its current status")
    return ask


def _ask_event(
    session: Session,
    actor_id: UUID,
    ask: Ask,
    event_name: EventName,
    *,
    question_id: UUID | None = None,
    ask_recipient_id: UUID | None = None,
    data: dict[str, object] | None = None,
) -> None:
    emit_event(
        session,
        SystemClock(),
        event_name,
        actor_id=actor_id,
        project_id=ask.project_id,
        ask_id=ask.id,
        question_id=question_id,
        ask_recipient_id=ask_recipient_id,
        data=data,
    )


def _actor_timezone(actor: Actor, requested: str | None) -> ZoneInfo:
    timezone = requested or actor.timezone
    zone = _zone(timezone)
    if requested is not None:
        actor.timezone = requested
    return zone


def _zone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise DraftConflict("timezone must be a valid IANA timezone") from error


def _resolve_deadline(value: date | None, timezone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time(17), timezone).astimezone(UTC)


def _is_overdue(ask: Ask) -> bool:
    return bool(
        ask.status == AskStatus.SENT
        and ask.deadline is not None
        and ask.deadline < SystemClock().now()
    )


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DraftConflict(f"{label} is required")
    return normalized


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _share_message(ask: Ask, recipient: AskRecipient, url: str) -> str:
    deadline = f" Please respond by {ask.deadline:%Y-%m-%d}." if ask.deadline else ""
    return f"Hi {recipient.display_name}, your input is requested on: {ask.title}.{deadline} {url}"


def _mutate[Result](session: Session, operation: Callable[[], Result]) -> Result:
    return run_command(
        session,
        operation,
        conflict_errors=(DraftConflict,),
        integrity_detail="draft conflicts with current data",
    )
