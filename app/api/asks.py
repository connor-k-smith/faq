from datetime import timedelta
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.ask_authoring import (
    _active_question,
    _initialize_sent_question,
    _new_question,
    _question_template,
    _replace_options,
    _supersede_question,
    _validate_and_recompute_sent_assignments,
)
from app.api.ask_contracts import (
    AdvisoryResponseWrite,
    AskCreate,
    AskUpdate,
    ChecklistWrite,
    DecisionWrite,
    OutcomeEffectWrite,
    QuestionWrite,
    RecipientWrite,
)
from app.api.ask_projections import _aggregate, _recipient_dto
from app.api.ask_recipients import (
    _active_recipient,
    _initialize_sent_recipient,
    _recipient_actor,
    _selected_open_questions,
)
from app.api.ask_response_models import (
    AskAggregate,
    AskResults,
    RecipientAddResult,
    RecipientDto,
    ResponseRevisionDto,
    SendResult,
    ShareArtifact,
)
from app.api.ask_results import _results
from app.api.ask_support import (
    DraftConflict,
    _actor_timezone,
    _ask_event,
    _authorize_ask_read,
    _mutable_ask,
    _mutable_parents,
    _mutate,
    _optional,
    _required,
    _resolve_deadline,
    _share_message,
    _token_hash,
)
from app.api.dependencies import (
    get_current_actor,
    get_db_session,
    get_token_generator,
    require_csrf,
)
from app.config import Settings, get_settings
from app.domain.decisions import (
    DecisionCommit,
    DecisionCommitError,
    DecisionEvidence,
    commit_decision,
)
from app.domain.enums import (
    AskStatus,
    AssignmentOrigin,
    AssignmentState,
    ContactKind,
    DecisionState,
    QuestionState,
)
from app.domain.events import EventName, emit_event
from app.domain.expressions import validate_dependency_graph
from app.domain.ports import SystemClock, TokenGenerator
from app.domain.responding import (
    ResponseSubmission,
    ResponseSubmissionError,
    submit_unsolicited_response,
)
from app.domain.settlement import (
    OutcomeRecordingError,
    record_outcome_effect,
    settle_ask,
)
from app.domain.validation import DomainValidationError
from app.models.identity import Actor, ContactMethod
from app.models.outcomes import Decision
from app.models.outcomes import Response as Answer
from app.models.work import (
    Ask,
    AskQuestion,
    AskRecipient,
    Assignment,
    Question,
    QuestionOption,
)

router = APIRouter(prefix="/api/asks", tags=["asks"])
CurrentActor = Annotated[Actor, Depends(get_current_actor)]
DatabaseSession = Annotated[Session, Depends(get_db_session)]
Tokens = Annotated[TokenGenerator, Depends(get_token_generator)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@router.post(
    "",
    response_model=AskAggregate,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def create_ask(body: AskCreate, actor: CurrentActor, session: DatabaseSession) -> AskAggregate:
    def operation() -> UUID:
        project, initiative = _mutable_parents(
            session, body.project_id, body.initiative_id, actor.id
        )
        timezone = _actor_timezone(actor, body.timezone)
        ask = Ask(
            id=uuid4(),
            project_id=project.id,
            initiative_id=initiative.id,
            parent_ask_id=None,
            title=_required(body.title, "Ask title"),
            intro=_optional(body.intro),
            created_by=actor.id,
            deadline=_resolve_deadline(body.deadline, timezone),
            default_note=_optional(body.default_note),
            status=AskStatus.DRAFT,
            owner_id=actor.id,
            sent_at=None,
            closed_at=None,
            share_message=None,
            critiques_overridden=[],
            created_at=SystemClock().now(),
        )
        session.add(ask)
        session.flush()
        emit_event(
            session,
            SystemClock(),
            EventName.ASK_CREATED,
            actor_id=actor.id,
            project_id=project.id,
            ask_id=ask.id,
            data={"initiative_id": str(initiative.id), "title": ask.title},
        )
        return ask.id

    ask_id = _mutate(session, operation)
    return _aggregate(session, ask_id, actor.id)


@router.get("/{ask_id}", response_model=AskAggregate)
def get_ask(ask_id: UUID, actor: CurrentActor, session: DatabaseSession) -> AskAggregate:
    _authorize_ask_read(session, ask_id, actor.id)
    # PRD lazy settlement makes this read an explicit side-effecting transaction boundary.
    if settle_ask(session, SystemClock(), ask_id, trigger="lazy"):
        session.commit()
    return _aggregate(session, ask_id, actor.id)


@router.put("/{ask_id}", response_model=AskAggregate, dependencies=[Depends(require_csrf)])
def update_ask(
    ask_id: UUID, body: AskUpdate, actor: CurrentActor, session: DatabaseSession
) -> AskAggregate:
    def operation() -> None:
        ask = _mutable_ask(session, ask_id, actor.id)
        timezone = _actor_timezone(actor, body.timezone)
        ask.title = _required(body.title, "Ask title")
        ask.intro = _optional(body.intro)
        ask.deadline = _resolve_deadline(body.deadline, timezone)
        ask.default_note = _optional(body.default_note)
        ask.critiques_overridden = body.critiques_overridden
        _ask_event(session, actor.id, ask, EventName.ASK_UPDATED)

    _mutate(session, operation)
    return _aggregate(session, ask_id, actor.id)


@router.post(
    "/{ask_id}/questions",
    response_model=AskAggregate,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def add_question(
    ask_id: UUID, body: QuestionWrite, actor: CurrentActor, session: DatabaseSession
) -> AskAggregate:
    def operation() -> None:
        ask = _mutable_ask(
            session, ask_id, actor.id, allowed_statuses=(AskStatus.DRAFT, AskStatus.SENT)
        )
        template = _question_template(session, body)
        question = _new_question(ask, actor.id, template, body)
        ordinal = session.scalar(
            select(func.coalesce(func.max(AskQuestion.ordinal), -1)).where(
                AskQuestion.ask_id == ask.id, AskQuestion.superseded_at.is_(None)
            )
        )
        session.add(question)
        session.flush()
        session.add(
            AskQuestion(
                project_id=ask.project_id,
                ask_id=ask.id,
                question_id=question.id,
                ordinal=int(ordinal or 0) + 1,
                superseded_at=None,
            )
        )
        _replace_options(session, question.id, template, body.options)
        session.flush()
        if ask.status == AskStatus.SENT:
            _initialize_sent_question(session, ask, question, actor.id)
        _ask_event(session, actor.id, ask, EventName.QUESTION_CREATED, question_id=question.id)

    _mutate(session, operation)
    return _aggregate(session, ask_id, actor.id)


@router.put(
    "/{ask_id}/questions/{question_id}",
    response_model=AskAggregate,
    dependencies=[Depends(require_csrf)],
)
def update_question(
    ask_id: UUID,
    question_id: UUID,
    body: QuestionWrite,
    actor: CurrentActor,
    session: DatabaseSession,
) -> AskAggregate:
    def operation() -> None:
        ask = _mutable_ask(
            session, ask_id, actor.id, allowed_statuses=(AskStatus.DRAFT, AskStatus.SENT)
        )
        question = _active_question(session, ask_id, question_id, lock=ask.status == AskStatus.SENT)
        template = _question_template(session, body)
        if ask.status == AskStatus.SENT:
            assignments = list(
                session.scalars(
                    select(Assignment)
                    .where(
                        Assignment.ask_id == ask.id,
                        Assignment.question_id == question.id,
                    )
                    .order_by(Assignment.id)
                    .with_for_update()
                )
            )
            response_count = (
                session.scalar(
                    select(func.count())
                    .select_from(Answer)
                    .where(Answer.assignment_id.in_([item.id for item in assignments]))
                )
                or 0
            )
            if response_count:
                _supersede_question(session, ask, question, assignments, template, body, actor.id)
                return
        question.template_id = template.id
        question.primitive = template.primitive
        question.prompt = _required(body.prompt, "Question prompt")
        question.help_text = _optional(body.help_text)
        question.allow_comment = body.allow_comment
        question.depends_on = body.depends_on
        question.response_visibility = body.response_visibility
        question.close_policy = body.close_policy
        question.open_to = body.open_to
        question.validation = template.default_validation
        question.require_comment_if = template.default_require_comment_if
        question.auto_commit = template.auto_commit
        question.auto_commit_if = template.default_auto_commit_if
        question.critiques_overridden = body.critiques_overridden
        _replace_options(session, question.id, template, body.options)
        if ask.status == AskStatus.SENT:
            _validate_and_recompute_sent_assignments(session, ask)
        _ask_event(
            session,
            actor.id,
            ask,
            EventName.QUESTION_UPDATED,
            question_id=question.id,
            data={"mode": "in_place", "version": question.version},
        )

    _mutate(session, operation)
    return _aggregate(session, ask_id, actor.id)


@router.delete(
    "/{ask_id}/questions/{question_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def delete_question(
    ask_id: UUID,
    question_id: UUID,
    actor: CurrentActor,
    session: DatabaseSession,
) -> Response:
    def operation() -> None:
        ask = _mutable_ask(session, ask_id, actor.id)
        question = _active_question(session, ask.id, question_id)
        link = session.scalar(
            select(AskQuestion).where(
                AskQuestion.ask_id == ask.id,
                AskQuestion.question_id == question.id,
                AskQuestion.superseded_at.is_(None),
            )
        )
        if link is None:
            raise DraftConflict("Question not found")
        link.superseded_at = SystemClock().now()
        question.state = QuestionState.SUPERSEDED
        session.flush()
        links = list(
            session.scalars(
                select(AskQuestion)
                .where(AskQuestion.ask_id == ask.id, AskQuestion.superseded_at.is_(None))
                .order_by(AskQuestion.ordinal, AskQuestion.question_id)
            )
        )
        for position, remaining in enumerate(links):
            remaining.ordinal = position + len(links) + 1
        session.flush()
        for position, remaining in enumerate(links):
            remaining.ordinal = position
        _ask_event(session, actor.id, ask, EventName.QUESTION_DELETED, question_id=question.id)

    _mutate(session, operation)
    return Response(status_code=204)


@router.post(
    "/{ask_id}/send",
    response_model=SendResult,
    dependencies=[Depends(require_csrf)],
)
def send_ask(
    ask_id: UUID,
    actor: CurrentActor,
    session: DatabaseSession,
    tokens: Tokens,
    settings: AppSettings,
) -> SendResult:
    artifacts: list[ShareArtifact] = []

    def operation() -> None:
        ask = _mutable_ask(session, ask_id, actor.id)
        questions = list(
            session.scalars(
                select(Question)
                .join(AskQuestion, AskQuestion.question_id == Question.id)
                .where(
                    AskQuestion.ask_id == ask.id,
                    AskQuestion.superseded_at.is_(None),
                    Question.state == QuestionState.OPEN,
                )
                .order_by(AskQuestion.ordinal)
            )
        )
        recipients = list(
            session.scalars(
                select(AskRecipient)
                .where(AskRecipient.ask_id == ask.id, AskRecipient.revoked_at.is_(None))
                .order_by(AskRecipient.created_at, AskRecipient.id)
                .with_for_update()
            )
        )
        if not questions:
            raise DraftConflict("at least one Question is required before send")
        if not recipients:
            raise DraftConflict("at least one stakeholder is required before send")
        try:
            validate_dependency_graph(
                {question.id: question.depends_on for question in questions},
                {
                    question.id: {recipient.actor_id for recipient in recipients}
                    for question in questions
                },
            )
        except ValueError as error:
            raise DraftConflict(str(error)) from error
        now = SystemClock().now()
        expires_at = now + timedelta(days=90)
        for recipient in recipients:
            if any(
                value is not None
                for value in (
                    recipient.token_hash,
                    recipient.token_issued_at,
                    recipient.access_expires_at,
                )
            ):
                raise DraftConflict("recipient already has credential state")
            raw_token = tokens.urlsafe(32)
            recipient.token_hash = _token_hash(raw_token)
            recipient.token_issued_at = now
            recipient.access_expires_at = expires_at
            for question in questions:
                assignment = Assignment(
                    id=uuid4(),
                    project_id=ask.project_id,
                    ask_id=ask.id,
                    question_id=question.id,
                    actor_id=recipient.actor_id,
                    ask_recipient_id=recipient.id,
                    origin=AssignmentOrigin.ASSIGNED,
                    state=AssignmentState.PENDING,
                    delegated_to_actor_id=None,
                    child_ask_id=None,
                    created_at=now,
                )
                session.add(assignment)
                session.flush()
                emit_event(
                    session,
                    SystemClock(),
                    EventName.ASSIGNMENT_CREATED,
                    actor_id=actor.id,
                    project_id=ask.project_id,
                    ask_id=ask.id,
                    question_id=question.id,
                    assignment_id=assignment.id,
                    ask_recipient_id=recipient.id,
                    data={"state": assignment.state.value},
                )
            _ask_event(
                session,
                actor.id,
                ask,
                EventName.RECIPIENT_CREDENTIAL_ISSUED,
                ask_recipient_id=recipient.id,
            )
            url = f"{settings.public_base_url.rstrip('/')}/r/{raw_token}"
            message = _share_message(ask, recipient, url)
            artifacts.append(
                ShareArtifact(
                    recipient_id=recipient.id,
                    display_name=recipient.display_name,
                    url=url,
                    message=message,
                )
            )
        _validate_and_recompute_sent_assignments(session, ask)
        ask.share_message = f"{ask.title} — response requested"
        ask.status = AskStatus.SENT
        ask.sent_at = now
        _ask_event(session, actor.id, ask, EventName.ASK_SENT)

    _mutate(session, operation)
    return SendResult(ask=_aggregate(session, ask_id, actor.id), artifacts=artifacts)


@router.post(
    "/{ask_id}/recipients/{recipient_id}/reissue",
    response_model=ShareArtifact,
    dependencies=[Depends(require_csrf)],
)
def reissue_recipient(
    ask_id: UUID,
    recipient_id: UUID,
    actor: CurrentActor,
    session: DatabaseSession,
    tokens: Tokens,
    settings: AppSettings,
) -> ShareArtifact:
    artifact: ShareArtifact | None = None

    def operation() -> None:
        nonlocal artifact
        ask = _mutable_ask(
            session, ask_id, actor.id, allowed_statuses=(AskStatus.DRAFT, AskStatus.SENT)
        )
        recipient = _active_recipient(session, ask.id, recipient_id)
        if recipient.token_hash is None:
            raise DraftConflict("recipient credential has not been issued")
        raw_token = tokens.urlsafe(32)
        now = SystemClock().now()
        recipient.token_hash = _token_hash(raw_token)
        recipient.token_issued_at = now
        recipient.access_expires_at = now + timedelta(days=90)
        recipient.session_version += 1
        recipient.share_marked_sent_at = None
        _ask_event(
            session,
            actor.id,
            ask,
            EventName.RECIPIENT_CREDENTIAL_ISSUED,
            ask_recipient_id=recipient.id,
        )
        url = f"{settings.public_base_url.rstrip('/')}/r/{raw_token}"
        artifact = ShareArtifact(
            recipient_id=recipient.id,
            display_name=recipient.display_name,
            url=url,
            message=_share_message(ask, recipient, url),
        )

    _mutate(session, operation)
    if artifact is None:
        raise HTTPException(status_code=500, detail="credential was not issued")
    return artifact


@router.put(
    "/{ask_id}/recipients/{recipient_id}/checklist",
    response_model=RecipientDto,
    dependencies=[Depends(require_csrf)],
)
def update_recipient_checklist(
    ask_id: UUID,
    recipient_id: UUID,
    body: ChecklistWrite,
    actor: CurrentActor,
    session: DatabaseSession,
) -> RecipientDto:
    def operation() -> None:
        ask = _mutable_ask(session, ask_id, actor.id, allowed_statuses=(AskStatus.SENT,))
        recipient = _active_recipient(session, ask.id, recipient_id)
        recipient.share_marked_sent_at = SystemClock().now() if body.sent else None
        _ask_event(
            session,
            actor.id,
            ask,
            EventName.RECIPIENT_SHARE_MARKED_SENT,
            ask_recipient_id=recipient.id,
        )

    _mutate(session, operation)
    return _recipient_dto(session, recipient_id)


@router.post(
    "/{ask_id}/recipients",
    response_model=RecipientDto | RecipientAddResult,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def add_recipient(
    ask_id: UUID,
    body: RecipientWrite,
    actor: CurrentActor,
    session: DatabaseSession,
    tokens: Tokens,
    settings: AppSettings,
) -> RecipientDto | RecipientAddResult:
    recipient_id: UUID
    artifact: ShareArtifact | None = None

    def operation() -> UUID:
        nonlocal artifact
        ask = _mutable_ask(
            session, ask_id, actor.id, allowed_statuses=(AskStatus.DRAFT, AskStatus.SENT)
        )
        now = SystemClock().now()
        recipient_actor = _recipient_actor(session, ask, body, now)
        name = recipient_actor.display_name
        recipient = AskRecipient(
            id=uuid4(),
            project_id=ask.project_id,
            ask_id=ask.id,
            actor_id=recipient_actor.id,
            display_name=name,
            token_hash=None,
            token_issued_at=None,
            session_version=1,
            revoked_at=None,
            access_expires_at=None,
            share_marked_sent_at=None,
            created_at=now,
        )
        if body.actor_id is None:
            session.add(recipient_actor)
            session.flush()
        session.add(recipient)
        if body.email is not None:
            session.add(
                ContactMethod(
                    id=uuid4(),
                    actor_id=recipient_actor.id,
                    kind=ContactKind.EMAIL,
                    value=_required(body.email, "Recipient email"),
                    verified_at=None,
                    opted_in_at=None,
                    priority=0,
                    quiet_hours=None,
                    created_at=now,
                )
            )
        session.flush()
        if ask.status == AskStatus.SENT:
            questions = _selected_open_questions(session, ask, body.question_ids)
            if not questions:
                raise DraftConflict("at least one current open Question must be selected")
            if ask.deadline is not None and ask.deadline <= now:
                if body.replacement_deadline is None:
                    raise DraftConflict(
                        "a future replacement_deadline is required for an overdue Ask"
                    )
                replacement = _resolve_deadline(
                    body.replacement_deadline, _actor_timezone(actor, body.timezone)
                )
                if replacement is None or replacement <= now:
                    raise DraftConflict("replacement_deadline must be in the future")
                old_deadline = ask.deadline
                ask.deadline = replacement
                _ask_event(
                    session,
                    actor.id,
                    ask,
                    EventName.ASK_DEADLINE_REPLACED,
                    data={"old": old_deadline.isoformat(), "new": replacement.isoformat()},
                )
            _initialize_sent_recipient(session, ask, recipient, questions, actor.id)
            raw_token = tokens.urlsafe(32)
            recipient.token_hash = _token_hash(raw_token)
            recipient.token_issued_at = now
            recipient.access_expires_at = now + timedelta(days=90)
            url = f"{settings.public_base_url.rstrip('/')}/r/{raw_token}"
            artifact = ShareArtifact(
                recipient_id=recipient.id,
                display_name=recipient.display_name,
                url=url,
                message=_share_message(ask, recipient, url),
            )
            _ask_event(
                session,
                actor.id,
                ask,
                EventName.RECIPIENT_CREDENTIAL_ISSUED,
                ask_recipient_id=recipient.id,
            )
        _ask_event(
            session,
            actor.id,
            ask,
            EventName.RECIPIENT_ADDED,
            ask_recipient_id=recipient.id,
        )
        return recipient.id

    recipient_id = _mutate(session, operation)
    recipient_dto = _recipient_dto(session, recipient_id)
    if artifact is None:
        return recipient_dto
    return RecipientAddResult(recipient=recipient_dto, artifact=artifact)


@router.delete(
    "/{ask_id}/recipients/{recipient_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def revoke_recipient(
    ask_id: UUID,
    recipient_id: UUID,
    actor: CurrentActor,
    session: DatabaseSession,
) -> Response:
    def operation() -> None:
        ask = _mutable_ask(
            session, ask_id, actor.id, allowed_statuses=(AskStatus.DRAFT, AskStatus.SENT)
        )
        recipient = _active_recipient(session, ask.id, recipient_id)
        recipient.revoked_at = SystemClock().now()
        recipient.session_version += 1
        assignments = list(
            session.scalars(
                select(Assignment).where(
                    Assignment.ask_recipient_id == recipient.id,
                    Assignment.state.in_([AssignmentState.PENDING, AssignmentState.BLOCKED]),
                )
            )
        )
        for assignment in assignments:
            assignment.state = AssignmentState.WITHDRAWN
        _ask_event(
            session,
            actor.id,
            ask,
            EventName.RECIPIENT_REVOKED,
            ask_recipient_id=recipient.id,
        )

    _mutate(session, operation)
    return Response(status_code=204)


@router.post(
    "/{ask_id}/cancel",
    response_model=AskAggregate,
    dependencies=[Depends(require_csrf)],
)
def cancel_ask(ask_id: UUID, actor: CurrentActor, session: DatabaseSession) -> AskAggregate:
    def operation() -> None:
        ask = _mutable_ask(
            session, ask_id, actor.id, allowed_statuses=(AskStatus.DRAFT, AskStatus.SENT)
        )
        now = SystemClock().now()
        assignments = list(
            session.scalars(
                select(Assignment).where(
                    Assignment.ask_id == ask.id,
                    Assignment.state.in_([AssignmentState.PENDING, AssignmentState.BLOCKED]),
                )
            )
        )
        for assignment in assignments:
            assignment.state = (
                AssignmentState.EXPIRED
                if assignment.state == AssignmentState.PENDING
                else AssignmentState.WITHDRAWN
            )
        questions = list(
            session.scalars(
                select(Question)
                .join(AskQuestion, AskQuestion.question_id == Question.id)
                .where(
                    AskQuestion.ask_id == ask.id,
                    AskQuestion.superseded_at.is_(None),
                    Question.state == QuestionState.OPEN,
                )
            )
        )
        for question in questions:
            question.state = QuestionState.CLOSED
            question.closed_at = now
        recipients = list(
            session.scalars(
                select(AskRecipient).where(
                    AskRecipient.ask_id == ask.id, AskRecipient.revoked_at.is_(None)
                )
            )
        )
        for recipient in recipients:
            recipient.revoked_at = now
            recipient.session_version += 1
            _ask_event(
                session,
                actor.id,
                ask,
                EventName.RECIPIENT_REVOKED,
                ask_recipient_id=recipient.id,
            )
        ask.status = AskStatus.CANCELLED
        ask.closed_at = now
        _ask_event(session, actor.id, ask, EventName.ASK_CANCELLED)

    _mutate(session, operation)
    return _aggregate(session, ask_id, actor.id)


@router.get("/{ask_id}/results", response_model=AskResults)
def get_results(ask_id: UUID, actor: CurrentActor, session: DatabaseSession) -> AskResults:
    _authorize_ask_read(session, ask_id, actor.id)
    # PRD lazy settlement makes this read an explicit side-effecting transaction boundary.
    if settle_ask(session, SystemClock(), ask_id, trigger="lazy"):
        session.commit()
    return _results(session, ask_id, actor.id)


@router.post(
    "/{ask_id}/questions/{question_id}/advisory-responses",
    response_model=ResponseRevisionDto,
    dependencies=[Depends(require_csrf)],
)
def submit_advisory_response(
    ask_id: UUID,
    question_id: UUID,
    body: AdvisoryResponseWrite,
    request: Request,
    actor: CurrentActor,
    session: DatabaseSession,
) -> ResponseRevisionDto:
    try:
        response = submit_unsolicited_response(
            session,
            SystemClock(),
            actor_id=actor.id,
            ask_id=ask_id,
            question_id=question_id,
            submission=ResponseSubmission(
                disposition=body.disposition,
                value=body.value,
                comment=body.comment,
                submission_id=body.submission_id,
                source_ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            ),
        )
        session.commit()
    except (ResponseSubmissionError, DomainValidationError) as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="advisory Response conflicted; retry"
        ) from error
    return ResponseRevisionDto(
        id=response.id,
        version=response.version,
        disposition=response.disposition.value,
        value=cast(JsonValue, response.value),
        comment=response.comment,
        created_at=response.created_at,
    )


@router.post(
    "/{ask_id}/questions/{question_id}/decision",
    response_model=AskResults,
    dependencies=[Depends(require_csrf)],
)
def decide_question(
    ask_id: UUID,
    question_id: UUID,
    body: DecisionWrite,
    actor: CurrentActor,
    session: DatabaseSession,
) -> AskResults:
    try:
        commit_decision(
            session,
            SystemClock(),
            actor_id=actor.id,
            ask_id=ask_id,
            question_id=question_id,
            commit=DecisionCommit(
                statement=body.statement,
                value=body.value,
                evidence=tuple(
                    DecisionEvidence(response_id=item.response_id, role=item.role)
                    for item in body.evidence
                ),
                outcome_effect=body.outcome_effect,
                outcome_effect_note=body.outcome_effect_note,
                share_with_recipients=body.share_with_recipients,
                proposal_id=body.proposal_id,
            ),
        )
        session.commit()
    except DecisionCommitError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="Question already has a Decision") from error
    return _results(session, ask_id, actor.id)


@router.post(
    "/{ask_id}/questions/{question_id}/outcome-effect",
    response_model=AskResults,
    dependencies=[Depends(require_csrf)],
)
def record_question_outcome_effect(
    ask_id: UUID,
    question_id: UUID,
    body: OutcomeEffectWrite,
    actor: CurrentActor,
    session: DatabaseSession,
) -> AskResults:
    try:
        record_outcome_effect(
            session,
            SystemClock(),
            actor_id=actor.id,
            ask_id=ask_id,
            question_id=question_id,
            effect=body.outcome_effect,
            note=body.outcome_effect_note,
        )
        session.commit()
    except OutcomeRecordingError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _results(session, ask_id, actor.id)


@router.post(
    "/{ask_id}/questions/{question_id}/successor",
    response_model=AskAggregate,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def create_successor_ask(
    ask_id: UUID, question_id: UUID, actor: CurrentActor, session: DatabaseSession
) -> AskAggregate:
    def operation() -> UUID:
        prior_ask = session.scalar(select(Ask).where(Ask.id == ask_id).with_for_update())
        prior_question = session.scalar(
            select(Question)
            .join(AskQuestion, AskQuestion.question_id == Question.id)
            .where(AskQuestion.ask_id == ask_id, Question.id == question_id)
            .with_for_update(of=Question)
        )
        if prior_ask is None or prior_question is None:
            raise DraftConflict("closed Question not found")
        _mutable_parents(session, prior_ask.project_id, prior_ask.initiative_id, actor.id)
        if prior_ask.owner_id != actor.id:
            raise DraftConflict("only the Ask owner may create a successor")
        prior_decision = session.scalar(
            select(Decision).where(
                Decision.question_id == prior_question.id,
                Decision.state == DecisionState.COMMITTED,
            )
        )
        if (
            prior_ask.status != AskStatus.CLOSED
            or prior_question.state != QuestionState.CLOSED
            or prior_decision is None
        ):
            raise DraftConflict("successors require a closed Question with a committed Decision")
        if session.scalar(
            select(Question.id).where(
                Question.supersedes_question_id == prior_question.id,
                Question.id != prior_question.id,
            )
        ):
            raise DraftConflict("Question already has a successor")
        now = SystemClock().now()
        successor_ask = Ask(
            id=uuid4(),
            project_id=prior_ask.project_id,
            initiative_id=prior_ask.initiative_id,
            parent_ask_id=prior_ask.id,
            title=prior_ask.title,
            intro=prior_ask.intro,
            created_by=prior_ask.created_by,
            deadline=None,
            default_note=prior_ask.default_note,
            status=AskStatus.DRAFT,
            owner_id=prior_ask.owner_id,
            sent_at=None,
            closed_at=None,
            share_message=None,
            critiques_overridden=[],
            created_at=now,
        )
        successor = Question(
            id=uuid4(),
            project_id=prior_question.project_id,
            template_id=prior_question.template_id,
            primitive=prior_question.primitive,
            version=prior_question.version + 1,
            supersedes_question_id=prior_question.id,
            copied_from_question_id=None,
            state=QuestionState.OPEN,
            origin=prior_question.origin,
            prompt=prior_question.prompt,
            help_text=prior_question.help_text,
            context_refs=prior_question.context_refs,
            open_to=prior_question.open_to,
            allow_comment=prior_question.allow_comment,
            validation=prior_question.validation,
            require_comment_if=prior_question.require_comment_if,
            depends_on=None,
            response_visibility=prior_question.response_visibility,
            anonymous=prior_question.anonymous,
            proposed_value=prior_question.proposed_value,
            proposed_rationale=prior_question.proposed_rationale,
            close_policy=prior_question.close_policy,
            auto_commit=prior_question.auto_commit,
            auto_commit_if=prior_question.auto_commit_if,
            created_by=prior_ask.created_by,
            critiques_overridden=[],
            close_eligible_at=None,
            closed_at=None,
            outcome_effect=None,
            outcome_effect_note=None,
            created_at=now,
        )
        session.add_all([successor_ask, successor])
        session.flush()
        session.add(
            AskQuestion(
                project_id=prior_ask.project_id,
                ask_id=successor_ask.id,
                question_id=successor.id,
                ordinal=0,
                superseded_at=None,
            )
        )
        for option in session.scalars(
            select(QuestionOption).where(QuestionOption.question_id == prior_question.id)
        ):
            session.add(
                QuestionOption(
                    id=uuid4(),
                    question_id=successor.id,
                    ordinal=option.ordinal,
                    value=option.value,
                    label=option.label,
                    consequence=option.consequence,
                    triggers=option.triggers,
                )
            )
        _ask_event(
            session,
            actor.id,
            successor_ask,
            EventName.SUCCESSOR_ASK_CREATED,
            question_id=successor.id,
            data={
                "prior_ask_id": str(prior_ask.id),
                "prior_question_id": str(prior_question.id),
                "prior_decision_id": str(prior_decision.id),
            },
        )
        return successor_ask.id

    successor_id = _mutate(session, operation)
    return _aggregate(session, successor_id, actor.id)
