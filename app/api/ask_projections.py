from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.ask_response_models import (
    AskAggregate,
    InitiativeRef,
    OptionDto,
    ProjectRef,
    QuestionDto,
    RecipientDto,
    RecipientPreview,
)
from app.api.ask_support import _is_overdue, _zone
from app.domain.enums import AskStatus, AssignmentOrigin, AssignmentState, ContactKind
from app.domain.ports import SystemClock
from app.models.identity import Actor, ContactMethod, Initiative, Membership, Project
from app.models.work import Ask, AskQuestion, AskRecipient, Assignment, Question, QuestionOption


def _aggregate(session: Session, ask_id: UUID, actor_id: UUID) -> AskAggregate:
    row = session.execute(
        select(Ask, Project, Initiative)
        .join(Project, Project.id == Ask.project_id)
        .join(Initiative, Initiative.id == Ask.initiative_id)
        .join(
            Membership,
            (Membership.project_id == Ask.project_id)
            & (Membership.actor_id == actor_id)
            & Membership.revoked_at.is_(None),
        )
        .where(Ask.id == ask_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Ask not found")
    ask, project, initiative = row
    owner = session.get(Actor, ask.owner_id)
    if owner is None:
        raise RuntimeError("Ask owner not found")
    questions = _question_dtos(session, ask.id)
    recipient_ids = list(
        session.scalars(
            select(AskRecipient.id)
            .where(AskRecipient.ask_id == ask.id, AskRecipient.revoked_at.is_(None))
            .order_by(AskRecipient.created_at, AskRecipient.id)
        )
    )
    recipients = _recipient_dtos(session, recipient_ids)
    read_only = (
        project.archived_at is not None
        or initiative.archived_at is not None
        or ask.status != AskStatus.DRAFT
        or ask.owner_id != actor_id
    )
    return AskAggregate(
        id=ask.id,
        project_id=ask.project_id,
        initiative_id=ask.initiative_id,
        parent_ask_id=ask.parent_ask_id,
        title=ask.title,
        intro=ask.intro,
        deadline=ask.deadline,
        deadline_date=(
            ask.deadline.astimezone(_zone(owner.timezone)).date() if ask.deadline else None
        ),
        owner_timezone=owner.timezone,
        overdue=_is_overdue(ask),
        default_note=ask.default_note,
        status=ask.status,
        owner_id=ask.owner_id,
        critiques_overridden=ask.critiques_overridden,
        created_at=ask.created_at,
        read_only=read_only,
        can_edit_questions=(
            project.archived_at is None
            and initiative.archived_at is None
            and ask.owner_id == actor_id
            and ask.status in (AskStatus.DRAFT, AskStatus.SENT)
        ),
        can_add_questions=(
            project.archived_at is None
            and initiative.archived_at is None
            and ask.owner_id == actor_id
            and ask.status in (AskStatus.DRAFT, AskStatus.SENT)
        ),
        can_add_recipients=(
            project.archived_at is None
            and initiative.archived_at is None
            and ask.owner_id == actor_id
            and ask.status in (AskStatus.DRAFT, AskStatus.SENT)
        ),
        can_create_successor=(
            project.archived_at is None
            and initiative.archived_at is None
            and ask.owner_id == actor_id
            and ask.status == AskStatus.CLOSED
        ),
        project=ProjectRef(id=project.id, name=project.name),
        initiative=InitiativeRef(id=initiative.id, name=initiative.name),
        questions=questions,
        recipients=recipients,
        recipient_previews=_recipient_previews(session, ask, recipients, questions),
    )


def _recipient_previews(
    session: Session,
    ask: Ask,
    recipients: list[RecipientDto],
    questions: list[QuestionDto],
) -> list[RecipientPreview]:
    if ask.status == AskStatus.DRAFT:
        return [RecipientPreview(recipient_id=item.id, questions=questions) for item in recipients]
    question_ids = {question.id for question in questions}
    selected = set(
        session.execute(
            select(Assignment.ask_recipient_id, Assignment.question_id).where(
                Assignment.ask_id == ask.id,
                Assignment.ask_recipient_id.in_([recipient.id for recipient in recipients]),
                Assignment.question_id.in_(question_ids),
                Assignment.origin != AssignmentOrigin.UNSOLICITED,
            )
        ).all()
    )
    return [
        RecipientPreview(
            recipient_id=recipient.id,
            questions=[
                question for question in questions if (recipient.id, question.id) in selected
            ],
        )
        for recipient in recipients
    ]


def _question_dtos(session: Session, ask_id: UUID) -> list[QuestionDto]:
    rows = session.execute(
        select(Question, AskQuestion.ordinal)
        .join(AskQuestion, AskQuestion.question_id == Question.id)
        .where(AskQuestion.ask_id == ask_id, AskQuestion.superseded_at.is_(None))
        .order_by(AskQuestion.ordinal, Question.id)
    ).all()
    result: list[QuestionDto] = []
    for question, ordinal in rows:
        options = list(
            session.scalars(
                select(QuestionOption)
                .where(QuestionOption.question_id == question.id)
                .order_by(QuestionOption.ordinal, QuestionOption.id)
            )
        )
        result.append(
            QuestionDto(
                id=question.id,
                template_id=question.template_id,
                primitive=question.primitive,
                version=question.version,
                supersedes_question_id=question.supersedes_question_id,
                copied_from_question_id=question.copied_from_question_id,
                ordinal=ordinal,
                prompt=question.prompt,
                help_text=question.help_text,
                allow_comment=question.allow_comment,
                depends_on=question.depends_on,
                options=[
                    OptionDto(
                        id=option.id,
                        ordinal=option.ordinal,
                        value=option.value,
                        label=option.label,
                        consequence=option.consequence,
                        triggers=option.triggers,
                    )
                    for option in options
                ],
                critiques_overridden=question.critiques_overridden,
                response_visibility=question.response_visibility,
                close_policy=question.close_policy,
                open_to=question.open_to,
            )
        )
    return result


def _recipient_dto(session: Session, recipient_id: UUID) -> RecipientDto:
    recipients = _recipient_dtos(session, [recipient_id])
    if not recipients:
        raise HTTPException(status_code=404, detail="Recipient not found")
    return recipients[0]


def _recipient_dtos(session: Session, recipient_ids: list[UUID]) -> list[RecipientDto]:
    if not recipient_ids:
        return []
    rows = session.execute(
        select(AskRecipient, ContactMethod.value)
        .outerjoin(
            ContactMethod,
            (ContactMethod.actor_id == AskRecipient.actor_id)
            & (ContactMethod.kind == ContactKind.EMAIL),
        )
        .where(AskRecipient.id.in_(recipient_ids))
    ).all()
    recipients_by_id = {recipient.id: (recipient, email) for recipient, email in rows}
    actor_ids = {recipient.actor_id for recipient, _email in recipients_by_id.values()}
    project_ids = {recipient.project_id for recipient, _email in recipients_by_id.values()}
    now = SystemClock().now()
    recent_since = now - timedelta(days=7)
    workload_rows = session.execute(
        select(
            Assignment.project_id,
            Assignment.actor_id,
            func.count(Assignment.id)
            .filter(
                Assignment.state.in_((AssignmentState.PENDING, AssignmentState.BLOCKED)),
                Ask.status == AskStatus.SENT,
            )
            .label("open_assignments"),
            func.count(Assignment.id)
            .filter(Assignment.created_at.between(recent_since, now))
            .label("recent_assignments"),
            func.count(func.distinct(Assignment.ask_id))
            .filter(Assignment.created_at.between(recent_since, now))
            .label("recent_asks"),
        )
        .join(Ask, Ask.id == Assignment.ask_id)
        .where(
            Assignment.actor_id.in_(actor_ids),
            Assignment.project_id.in_(project_ids),
            Assignment.origin != AssignmentOrigin.UNSOLICITED,
        )
        .group_by(Assignment.project_id, Assignment.actor_id)
    ).all()
    workloads = {
        (project_id, actor_id): (open_assignments, recent_assignments, recent_asks)
        for project_id, actor_id, open_assignments, recent_assignments, recent_asks in workload_rows
    }
    result: list[RecipientDto] = []
    for recipient_id in recipient_ids:
        recipient, email = recipients_by_id[recipient_id]
        open_assignments, recent_assignments, recent_asks = workloads.get(
            (recipient.project_id, recipient.actor_id), (0, 0, 0)
        )
        result.append(
            RecipientDto(
                id=recipient.id,
                actor_id=recipient.actor_id,
                display_name=recipient.display_name,
                email=email,
                created_at=recipient.created_at,
                credential_active=(
                    recipient.token_hash is not None
                    and recipient.access_expires_at is not None
                    and recipient.access_expires_at > now
                ),
                share_marked_sent_at=recipient.share_marked_sent_at,
                open_assignments=open_assignments,
                recent_assignments=recent_assignments,
                recent_asks=recent_asks,
                window_days=7,
                workload_warning=open_assignments > 0 or recent_assignments > 0,
            )
        )
    return result
