import base64
import json
from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from app.api.dependencies import get_current_actor, get_db_session
from app.domain.enums import AskStatus, AssignmentOrigin, QuestionState, ResponseVisibility
from app.models.identity import Actor, Initiative, Membership, Project
from app.models.outcomes import Decision, Response
from app.models.work import Ask, AskQuestion, Assignment, Question, QuestionOption

router = APIRouter(prefix="/api/projects", tags=["feed"])
CurrentActor = Annotated[Actor, Depends(get_current_actor)]
DatabaseSession = Annotated[Session, Depends(get_db_session)]


class FeedOption(BaseModel):
    id: UUID
    label: str


class FeedItem(BaseModel):
    kind: Literal["ask", "question", "option", "decision", "response"]
    source_id: UUID
    ask_id: UUID
    ask_title: str
    ask_status: AskStatus
    parent_ask_id: UUID | None
    initiative_id: UUID
    initiative_name: str
    asker_id: UUID
    asker_name: str
    question_id: UUID | None
    decision_id: UUID | None
    supersedes_decision_id: UUID | None = None
    successor_decision_id: UUID | None = None
    occurred_at: datetime
    rank: float
    snippet: str
    revision: int | None = None
    superseded: bool = False
    advisory: bool = False
    late: bool = False
    respondent_actor_id: UUID | None = None
    respondent_name: str | None = None


class FeedPage(BaseModel):
    items: list[FeedItem]
    next_cursor: str | None
    initiatives: list[FeedOption]
    askers: list[FeedOption]


@router.get("/{project_id}/feed", response_model=FeedPage)
def project_feed(
    project_id: UUID,
    actor: CurrentActor,
    session: DatabaseSession,
    q: str | None = None,
    initiative_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    asker_id: UUID | None = None,
    status: AskStatus | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> FeedPage:
    project = session.scalar(
        select(Project)
        .join(Membership, Membership.project_id == Project.id)
        .where(
            Project.id == project_id,
            Membership.actor_id == actor.id,
            Membership.revoked_at.is_(None),
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    offset = _decode_cursor(cursor)
    normalized = q.strip() if q else ""
    filters = [Ask.project_id == project.id]
    if initiative_id:
        filters.append(Ask.initiative_id == initiative_id)
    if date_from:
        filters.append(Ask.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        filters.append(Ask.created_at < datetime.combine(date_to, time.max))
    if asker_id:
        filters.append(Ask.created_by == asker_id)
    if status:
        filters.append(Ask.status == status)

    hits = _search_hits(session, actor.id, filters, normalized)
    hits.sort(
        key=lambda item: (-item.rank, -item.occurred_at.timestamp(), item.kind, str(item.source_id))
    )
    page = hits[offset : offset + limit]
    next_cursor = _encode_cursor(offset + limit) if offset + limit < len(hits) else None
    initiatives = list(
        session.scalars(
            select(Initiative)
            .where(Initiative.project_id == project.id)
            .order_by(Initiative.name, Initiative.id)
        )
    )
    askers = list(
        session.scalars(
            select(Actor)
            .join(Ask, Ask.created_by == Actor.id)
            .where(Ask.project_id == project.id)
            .distinct()
            .order_by(Actor.display_name, Actor.id)
        )
    )
    return FeedPage(
        items=page,
        next_cursor=next_cursor,
        initiatives=[FeedOption(id=item.id, label=item.name) for item in initiatives],
        askers=[FeedOption(id=item.id, label=item.display_name) for item in askers],
    )


def _search_hits(
    session: Session,
    actor_id: UUID,
    ask_filters: Sequence[ColumnElement[bool]],
    query: str,
) -> list[FeedItem]:
    if not query:
        rows = session.execute(
            select(Decision, Ask, Initiative, Actor, Question)
            .join(Ask, Ask.id == Decision.ask_id)
            .join(Initiative, Initiative.id == Ask.initiative_id)
            .join(Actor, Actor.id == Ask.created_by)
            .join(Question, Question.id == Decision.question_id)
            .where(*ask_filters, Decision.state.in_(["committed", "superseded"]))
        ).all()
        return [
            _hit(
                "decision",
                decision.id,
                ask,
                initiative,
                asker,
                question,
                decision.committed_at or decision.created_at,
                0,
                decision.statement or "",
                decision_id=decision.id,
                supersedes_decision_id=decision.supersedes_decision_id,
                successor_decision_id=session.scalar(
                    select(Decision.id).where(Decision.supersedes_decision_id == decision.id)
                ),
                superseded=decision.state.value == "superseded",
            )
            for decision, ask, initiative, asker, question in rows
        ]
    tsquery = func.websearch_to_tsquery("english", query)
    hits: list[FeedItem] = []
    base = (Ask, Initiative, Actor)
    ask_rows = session.execute(
        select(Ask, Initiative, Actor, func.ts_rank_cd(Ask.search_tsv, tsquery))
        .join(Initiative, Initiative.id == Ask.initiative_id)
        .join(Actor, Actor.id == Ask.created_by)
        .where(*ask_filters, Ask.search_tsv.op("@@")(tsquery))
    ).all()
    hits.extend(
        _hit(
            "ask",
            ask.id,
            ask,
            initiative,
            asker,
            None,
            ask.created_at,
            rank,
            f"{ask.title} {ask.intro or ''}",
        )
        for ask, initiative, asker, rank in ask_rows
    )
    vector = func.to_tsvector(
        "english", func.coalesce(Question.prompt, "") + " " + func.coalesce(Question.help_text, "")
    )
    question_rows = session.execute(
        select(Question, *base, func.ts_rank_cd(vector, tsquery))
        .join(AskQuestion, AskQuestion.question_id == Question.id)
        .join(Ask, Ask.id == AskQuestion.ask_id)
        .join(Initiative, Initiative.id == Ask.initiative_id)
        .join(Actor, Actor.id == Ask.created_by)
        .where(*ask_filters, vector.op("@@")(tsquery))
    ).all()
    hits.extend(
        _hit(
            "question",
            question.id,
            ask,
            initiative,
            asker,
            question,
            question.created_at,
            rank,
            f"{question.prompt} {question.help_text or ''}",
        )
        for question, ask, initiative, asker, rank in question_rows
    )
    option_rows = session.execute(
        select(QuestionOption, Question, *base, func.ts_rank_cd(QuestionOption.search_tsv, tsquery))
        .join(Question, Question.id == QuestionOption.question_id)
        .join(AskQuestion, AskQuestion.question_id == Question.id)
        .join(Ask, Ask.id == AskQuestion.ask_id)
        .join(Initiative, Initiative.id == Ask.initiative_id)
        .join(Actor, Actor.id == Ask.created_by)
        .where(*ask_filters, QuestionOption.search_tsv.op("@@")(tsquery))
    ).all()
    hits.extend(
        _hit(
            "option",
            option.id,
            ask,
            initiative,
            asker,
            question,
            question.created_at,
            rank,
            f"{option.label} {option.consequence or ''}",
        )
        for option, question, ask, initiative, asker, rank in option_rows
    )
    decision_rows = session.execute(
        select(Decision, Question, *base, func.ts_rank_cd(Decision.search_tsv, tsquery))
        .join(Question, Question.id == Decision.question_id)
        .join(Ask, Ask.id == Decision.ask_id)
        .join(Initiative, Initiative.id == Ask.initiative_id)
        .join(Actor, Actor.id == Ask.created_by)
        .where(
            *ask_filters,
            Decision.state.in_(["committed", "superseded"]),
            Decision.search_tsv.op("@@")(tsquery),
        )
    ).all()
    hits.extend(
        _hit(
            "decision",
            decision.id,
            ask,
            initiative,
            asker,
            question,
            decision.committed_at or decision.created_at,
            rank,
            decision.statement or "",
            decision_id=decision.id,
            supersedes_decision_id=decision.supersedes_decision_id,
            successor_decision_id=session.scalar(
                select(Decision.id).where(Decision.supersedes_decision_id == decision.id)
            ),
            superseded=decision.state.value == "superseded",
        )
        for decision, question, ask, initiative, asker, rank in decision_rows
    )

    own_assignment = aliased(Assignment)
    own_response = aliased(Response)
    own_exists = exists(
        select(own_response.id)
        .join(own_assignment, own_assignment.id == own_response.assignment_id)
        .where(own_assignment.question_id == Question.id, own_assignment.actor_id == actor_id)
    )
    visible = or_(
        Ask.owner_id == actor_id,
        Question.state != QuestionState.OPEN,
        Question.response_visibility == ResponseVisibility.IMMEDIATE,
        Assignment.actor_id == actor_id,
        and_(Question.response_visibility == ResponseVisibility.AFTER_OWN_RESPONSE, own_exists),
    )
    respondent = aliased(Actor)
    response_rows = session.execute(
        select(
            Response,
            Assignment,
            Question,
            *base,
            respondent,
            func.ts_rank_cd(Response.search_tsv, tsquery),
        )
        .join(Assignment, Assignment.id == Response.assignment_id)
        .join(Question, Question.id == Assignment.question_id)
        .join(Ask, Ask.id == Assignment.ask_id)
        .join(Initiative, Initiative.id == Ask.initiative_id)
        .join(Actor, Actor.id == Ask.created_by)
        .join(respondent, respondent.id == Assignment.actor_id)
        .where(*ask_filters, visible, Response.search_tsv.op("@@")(tsquery))
    ).all()
    hits.extend(
        _hit(
            "response",
            response.id,
            ask,
            initiative,
            asker,
            question,
            response.created_at,
            rank,
            f"{response.value} {response.comment or ''}",
            revision=response.version,
            advisory=assignment.origin == AssignmentOrigin.UNSOLICITED,
            late=bool(response.provenance.get("late")),
            respondent_actor_id=respondent.id,
            respondent_name=respondent.display_name,
        )
        for response, assignment, question, ask, initiative, asker, respondent, rank in (
            response_rows
        )
    )
    return hits


def _hit(
    kind: str,
    source_id: UUID,
    ask: Ask,
    initiative: Initiative,
    asker: Actor,
    question: Question | None,
    occurred_at: datetime,
    rank: float,
    snippet: str,
    *,
    decision_id: UUID | None = None,
    supersedes_decision_id: UUID | None = None,
    successor_decision_id: UUID | None = None,
    revision: int | None = None,
    superseded: bool = False,
    advisory: bool = False,
    late: bool = False,
    respondent_actor_id: UUID | None = None,
    respondent_name: str | None = None,
) -> FeedItem:
    return FeedItem(
        kind=kind,
        source_id=source_id,
        ask_id=ask.id,
        ask_title=ask.title,
        ask_status=ask.status,
        parent_ask_id=ask.parent_ask_id,
        initiative_id=initiative.id,
        initiative_name=initiative.name,
        asker_id=asker.id,
        asker_name=asker.display_name,
        question_id=question.id if question else None,
        decision_id=decision_id,
        supersedes_decision_id=supersedes_decision_id,
        successor_decision_id=successor_decision_id,
        occurred_at=occurred_at,
        rank=float(rank),
        snippet=" ".join(snippet.split())[:320],
        revision=revision,
        superseded=superseded,
        advisory=advisory,
        late=late,
        respondent_actor_id=respondent_actor_id,
        respondent_name=respondent_name,
    )


def _encode_cursor(offset: int) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps({"v": 1, "offset": offset}).encode())
        .decode()
        .rstrip("=")
    )


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if (
            payload.get("v") != 1
            or not isinstance(payload.get("offset"), int)
            or payload["offset"] < 0
        ):
            raise ValueError
        return int(payload["offset"])
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail="invalid feed cursor") from error
