import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_actor, get_db_session
from app.domain.enums import AskStatus, DecisionState, QuestionState
from app.models.identity import Actor, Initiative, Membership, Project
from app.models.outcomes import Decision
from app.models.work import Ask, AskQuestion, Question

router = APIRouter(prefix="/api/inbox", tags=["inbox"])
CurrentActor = Annotated[Actor, Depends(get_current_actor)]
DatabaseSession = Annotated[Session, Depends(get_db_session)]
InboxKind = Literal["proposed_decision", "outcome_effect", "collecting"]


class InboxCounts(BaseModel):
    total: int
    proposed_decision: int
    outcome_effect: int
    collecting: int


class InboxItem(BaseModel):
    kind: InboxKind
    project_id: UUID
    project_name: str
    initiative_id: UUID
    initiative_name: str
    ask_id: UUID
    ask_title: str
    ask_status: str
    question_id: UUID
    question_ordinal: int
    question_prompt: str
    question_status: str
    decision_id: UUID | None
    decision_basis: str | None
    deadline: datetime | None
    overdue: bool
    close_policy: str
    occurred_at: datetime


class InboxPage(BaseModel):
    counts: InboxCounts
    items: list[InboxItem]
    next_cursor: str | None


@router.get("", response_model=InboxPage)
def owner_inbox(
    actor: CurrentActor,
    session: DatabaseSession,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> InboxPage:
    rows = session.execute(
        select(Ask, Question, AskQuestion, Initiative, Project)
        .select_from(Ask)
        .distinct()
        .join(AskQuestion, AskQuestion.ask_id == Ask.id)
        .join(Question, Question.id == AskQuestion.question_id)
        .join(Initiative, Initiative.id == Ask.initiative_id)
        .join(Project, Project.id == Ask.project_id)
        .join(
            Membership,
            (Membership.project_id == Ask.project_id) & (Membership.actor_id == actor.id),
        )
        .where(
            Ask.owner_id == actor.id,
            Ask.status == AskStatus.SENT,
            Membership.revoked_at.is_(None),
            AskQuestion.superseded_at.is_(None),
            Question.state != QuestionState.SUPERSEDED,
        )
    ).all()

    now = datetime.now(UTC)
    ask_ids = {row[0].id for row in rows}
    decisions = {
        decision.question_id: decision
        for decision in session.scalars(
            select(Decision).where(
                Decision.ask_id.in_(ask_ids),
                Decision.state.in_([DecisionState.PROPOSED, DecisionState.COMMITTED]),
            )
        )
    }
    items: list[InboxItem] = []
    counts = {"proposed_decision": 0, "outcome_effect": 0, "collecting": 0}
    seen: set[tuple[str, UUID]] = set()
    for ask, question, ask_question, initiative, project in rows:
        decision = decisions.get(question.id)
        kind: InboxKind | None = None
        if decision is not None and decision.state == DecisionState.PROPOSED:
            kind = "proposed_decision"
        elif (
            decision is not None
            and decision.state == DecisionState.COMMITTED
            and question.outcome_effect is None
        ):
            kind = "outcome_effect"
        elif question.state == QuestionState.OPEN and decision is None:
            kind = "collecting"
        if kind is None:
            continue
        identity = (kind, question.id)
        if identity in seen:
            continue
        seen.add(identity)
        counts[kind] += 1
        occurred_at = (
            decision.committed_at or decision.created_at if decision is not None else ask.sent_at
        ) or question.created_at
        items.append(
            InboxItem(
                kind=kind,
                project_id=project.id,
                project_name=project.name,
                initiative_id=initiative.id,
                initiative_name=initiative.name,
                ask_id=ask.id,
                ask_title=ask.title,
                ask_status=ask.status.value,
                question_id=question.id,
                question_ordinal=ask_question.ordinal,
                question_prompt=question.prompt,
                question_status=question.state.value,
                decision_id=decision.id if decision else None,
                decision_basis=decision.basis.value if decision else None,
                deadline=ask.deadline,
                overdue=ask.deadline is not None and ask.deadline < now,
                close_policy=question.close_policy.value,
                occurred_at=occurred_at,
            )
        )

    priority = {"proposed_decision": 0, "outcome_effect": 1, "collecting": 2}
    items.sort(
        key=lambda item: (
            priority[item.kind],
            -item.occurred_at.timestamp(),
            str(item.question_id),
        )
    )
    after = _decode_cursor(cursor)
    if after is not None:
        items = [item for item in items if _key(item, priority) > after]
    page = items[:limit]
    next_cursor = _encode_cursor(_key(page[-1], priority)) if len(items) > limit else None
    return InboxPage(
        counts=InboxCounts(total=sum(counts.values()), **counts),
        items=page,
        next_cursor=next_cursor,
    )


def _key(item: InboxItem, priority: dict[str, int]) -> tuple[int, float, str]:
    return (priority[item.kind], -item.occurred_at.timestamp(), str(item.question_id))


def _encode_cursor(key: tuple[int, float, str]) -> str:
    payload = json.dumps({"v": 1, "key": key}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[int, float, str] | None:
    if cursor is None:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        key = payload["key"]
        if payload.get("v") != 1 or len(key) != 3:
            raise ValueError
        return int(key[0]), float(key[1]), str(UUID(key[2]))
    except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="invalid inbox cursor") from error
