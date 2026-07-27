from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.ask_authoring import (
    _new_question,
    _question_template,
    _replace_options,
)
from app.api.ask_contracts import OptionWrite, QuestionWrite
from app.api.ask_projections import _aggregate
from app.api.ask_response_models import AskAggregate
from app.api.ask_support import DraftConflict, _ask_event, _mutable_ask
from app.api.dependencies import get_current_actor, get_db_session, require_csrf
from app.assistant.schemas import NeedsClarification, ProductCritique, QuestionDraft
from app.assistant.service import PROMPT_VERSION, DraftAssistant, get_draft_assistant, parse_history
from app.domain.enums import QuestionOrigin
from app.domain.events import EventName
from app.domain.ports import SystemClock
from app.models.identity import Actor
from app.models.work import Ask, AskQuestion, AuthoringSession

router = APIRouter(prefix="/api/asks", tags=["assistant"])
CurrentActor = Annotated[Actor, Depends(get_current_actor)]
DatabaseSession = Annotated[Session, Depends(get_db_session)]
Assistant = Annotated[DraftAssistant, Depends(get_draft_assistant)]


class DraftRequest(BaseModel):
    source: str = Field(min_length=1, max_length=50_000)
    authoring_session_id: UUID | None = None


class AssistantResponse(BaseModel):
    kind: Literal["draft", "clarification"]
    authoring_session_id: UUID
    prompt_version: str
    clarification: NeedsClarification | None = None
    draft: AskAggregate | None = None
    critiques: list[ProductCritique] = Field(default_factory=list)


@router.post(
    "/{ask_id}/assistant",
    response_model=AssistantResponse,
    dependencies=[Depends(require_csrf)],
)
def draft_with_assistant(
    ask_id: UUID,
    body: DraftRequest,
    actor: CurrentActor,
    session: DatabaseSession,
    assistant: Assistant,
) -> AssistantResponse:
    try:
        if not body.source.strip():
            raise DraftConflict("Source material is required")
        ask = _mutable_ask(session, ask_id, actor.id)
        question_ids = tuple(
            session.scalars(
                select(AskQuestion.question_id)
                .where(AskQuestion.ask_id == ask.id, AskQuestion.superseded_at.is_(None))
                .order_by(AskQuestion.ordinal, AskQuestion.question_id)
            )
        )
        ask_snapshot = (ask.title, ask.intro, question_ids)
        if body.authoring_session_id is None:
            authoring_id = uuid4()
            messages: list[dict[str, object]] = []
            conversation_id = None
            authoring_updated_at = None
        else:
            existing = _authoring_session(
                session, ask.id, actor.id, body.authoring_session_id, lock=False
            )
            authoring_id = existing.id
            messages = existing.messages
            conversation_id = existing.conversation_id
            authoring_updated_at = existing.updated_at
        session.rollback()
        turn = assistant.run(
            body.source.strip(),
            history=parse_history(messages),
            conversation_id=conversation_id,
        )
        ask = _mutable_ask(session, ask_id, actor.id)
        current_question_ids = tuple(
            session.scalars(
                select(AskQuestion.question_id)
                .where(AskQuestion.ask_id == ask.id, AskQuestion.superseded_at.is_(None))
                .order_by(AskQuestion.ordinal, AskQuestion.question_id)
            )
        )
        if (ask.title, ask.intro, current_question_ids) != ask_snapshot:
            raise DraftConflict("Ask changed while the assistant was running; retry")
        if body.authoring_session_id is None:
            now = SystemClock().now()
            authoring = AuthoringSession(
                id=authoring_id,
                project_id=ask.project_id,
                actor_id=actor.id,
                ask_id=ask.id,
                conversation_id=None,
                messages=[],
                created_at=now,
                updated_at=now,
            )
            session.add(authoring)
            session.flush()
        else:
            authoring = _authoring_session(
                session, ask.id, actor.id, body.authoring_session_id, lock=True
            )
            if authoring.updated_at != authoring_updated_at:
                raise DraftConflict(
                    "Authoring session changed while the assistant was running; retry"
                )
        authoring.messages = turn.messages
        authoring.conversation_id = turn.conversation_id
        authoring.updated_at = SystemClock().now()
        if isinstance(turn.output, NeedsClarification):
            _ask_event(
                session,
                actor.id,
                ask,
                EventName.AUTHORING_CLARIFICATION_REQUESTED,
            )
            session.commit()
            return AssistantResponse(
                kind="clarification",
                authoring_session_id=authoring.id,
                prompt_version=PROMPT_VERSION,
                clarification=turn.output,
            )
        critiques = _apply_draft(session, ask, actor.id, turn.output)
        _ask_event(
            session,
            actor.id,
            ask,
            EventName.AUTHORING_DRAFT_APPLIED,
        )
        session.commit()
        return AssistantResponse(
            kind="draft",
            authoring_session_id=authoring.id,
            prompt_version=PROMPT_VERSION,
            draft=_aggregate(session, ask.id, actor.id),
            critiques=critiques,
        )
    except DraftConflict as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception:
        session.rollback()
        raise


def _authoring_session(
    session: Session,
    ask_id: UUID,
    actor_id: UUID,
    authoring_session_id: UUID | None,
    *,
    lock: bool = True,
) -> AuthoringSession:
    ask = session.get(Ask, ask_id)
    if ask is None:
        raise DraftConflict("Ask not found")
    if authoring_session_id is not None:
        statement = select(AuthoringSession).where(
            AuthoringSession.id == authoring_session_id,
            AuthoringSession.ask_id == ask_id,
            AuthoringSession.actor_id == actor_id,
        )
        if lock:
            statement = statement.with_for_update()
        value = session.scalar(statement)
        if value is None:
            raise DraftConflict("Authoring session not found")
        return value
    now = SystemClock().now()
    value = AuthoringSession(
        id=uuid4(),
        project_id=ask.project_id,
        actor_id=actor_id,
        ask_id=ask.id,
        conversation_id=None,
        messages=[],
        created_at=now,
        updated_at=now,
    )
    session.add(value)
    session.flush()
    return value


def _apply_draft(
    session: Session, ask: Ask, actor_id: UUID, draft: QuestionDraft
) -> list[ProductCritique]:
    # The assistant may start an empty draft or add to manually authored work; it never replaces it.
    ask.title = draft.title.strip()
    ask.intro = draft.intro.strip() if draft.intro else None
    next_ordinal = session.scalar(
        select(AskQuestion.ordinal)
        .where(AskQuestion.ask_id == ask.id, AskQuestion.superseded_at.is_(None))
        .order_by(AskQuestion.ordinal.desc())
        .limit(1)
    )
    ordinal = (next_ordinal if next_ordinal is not None else -1) + 1
    critiques = list(draft.critiques)
    created_questions = []
    for index, item in enumerate(draft.questions):
        body = QuestionWrite(
            template_id=item.template_id,
            prompt=item.prompt,
            help_text=item.help_text,
            allow_comment=item.allow_comment,
            options=[OptionWrite(**option.model_dump()) for option in item.options],
        )
        template = _question_template(session, body)
        question = _new_question(
            ask, actor_id, template, body, origin=QuestionOrigin.AGENT_SURFACED
        )
        session.add(question)
        session.flush()
        created_questions.append(question)
        session.add(
            AskQuestion(
                project_id=ask.project_id,
                ask_id=ask.id,
                question_id=question.id,
                ordinal=ordinal + index,
                superseded_at=None,
            )
        )
        _replace_options(session, question.id, template, body.options)
        _ask_event(
            session,
            actor_id,
            ask,
            EventName.QUESTION_CREATED,
            question_id=question.id,
        )
        if item.template_id != "open_question" and not any(
            option.value.lower() in {"other", "unsure", "none", "need_context"}
            for option in item.options
        ):
            critiques.append(
                ProductCritique(
                    code="missing_escape_hatch",
                    message="This select-one question has no obvious escape hatch.",
                    question_index=index,
                )
            )
    for index, item in enumerate(draft.questions):
        prerequisite_index = item.depends_on_question_index
        if prerequisite_index is not None:
            created_questions[index].depends_on = {
                "question_id": str(created_questions[prerequisite_index].id),
                "op": "answered",
            }
    if ask.deadline is None:
        critiques.append(
            ProductCritique(
                code="missing_deadline",
                message="This Ask has no deadline.",
            )
        )
    return critiques
