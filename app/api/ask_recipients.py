from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.ask_contracts import RecipientWrite
from app.api.ask_support import DraftConflict, _required
from app.domain.dependencies import derive_assignment_state
from app.domain.enums import (
    ActorKind,
    AssignmentOrigin,
    AssignmentState,
    OrganizationRole,
    QuestionState,
)
from app.domain.events import EventName, emit_event
from app.domain.expressions import parse_condition, validate_dependency_graph
from app.domain.ports import SystemClock
from app.models.identity import Actor, Membership
from app.models.outcomes import Response as Answer
from app.models.work import Ask, AskQuestion, AskRecipient, Assignment, Question


def _recipient_actor(session: Session, ask: Ask, body: RecipientWrite, now: datetime) -> Actor:
    if body.actor_id is not None:
        actor = session.scalar(
            select(Actor)
            .join(Membership, Membership.actor_id == Actor.id)
            .where(
                Membership.project_id == ask.project_id,
                Membership.actor_id == body.actor_id,
                Membership.revoked_at.is_(None),
                Actor.deleted_at.is_(None),
            )
        )
        if actor is None:
            raise DraftConflict("actor_id must be an active member of this Project")
        return actor
    if body.display_name is None:
        raise DraftConflict("display_name is required when actor_id is omitted")
    return Actor(
        id=uuid4(),
        kind=ActorKind.HUMAN,
        organization_role=OrganizationRole.MEMBER,
        display_name=_required(body.display_name, "Recipient display name"),
        firebase_uid=None,
        avatar_url=None,
        timezone="UTC",
        deleted_at=None,
        created_at=now,
    )


def _selected_open_questions(
    session: Session, ask: Ask, selected_ids: list[UUID] | None
) -> list[Question]:
    statement = (
        select(Question)
        .join(AskQuestion, AskQuestion.question_id == Question.id)
        .where(
            AskQuestion.ask_id == ask.id,
            AskQuestion.superseded_at.is_(None),
            Question.state == QuestionState.OPEN,
        )
        .order_by(AskQuestion.ordinal, Question.id)
        .with_for_update(of=Question)
    )
    questions = list(session.scalars(statement))
    if selected_ids is None:
        raise DraftConflict("question_ids is required when adding a recipient to a sent Ask")
    if len(set(selected_ids)) != len(selected_ids):
        raise DraftConflict("question_ids must be unique")
    by_id = {question.id: question for question in questions}
    if any(question_id not in by_id for question_id in selected_ids):
        raise DraftConflict("question_ids must select current open Questions")
    return [by_id[question_id] for question_id in selected_ids]


def _assignment_initial_state(
    session: Session, ask: Ask, question: Question, actor_id: UUID
) -> AssignmentState:
    condition = (
        parse_condition(question.depends_on, require_question_id=True)
        if question.depends_on is not None
        else None
    )
    prerequisite = None
    prerequisite_response = None
    if condition is not None:
        prerequisite = session.scalar(
            select(Assignment).where(
                Assignment.ask_id == ask.id,
                Assignment.question_id == condition.question_id,
                Assignment.actor_id == actor_id,
            )
        )
        if prerequisite is not None:
            prerequisite_response = _latest_response(session, prerequisite.id)
    own = session.scalar(
        select(Assignment).where(
            Assignment.ask_id == ask.id,
            Assignment.question_id == question.id,
            Assignment.actor_id == actor_id,
        )
    )
    own_response = _latest_response(session, own.id) if own is not None else None
    try:
        return derive_assignment_state(
            condition,
            prerequisite.state if prerequisite is not None else None,
            prerequisite_response.value if prerequisite_response is not None else None,
            prerequisite_response.disposition if prerequisite_response is not None else None,
            own_response.disposition if own_response is not None else None,
        )
    except ValueError as error:
        raise DraftConflict(str(error)) from error


def _latest_response(session: Session, assignment_id: UUID) -> Answer | None:
    return session.scalar(
        select(Answer)
        .where(Answer.assignment_id == assignment_id)
        .order_by(Answer.version.desc())
        .limit(1)
    )


def _create_or_convert_assignment(
    session: Session,
    ask: Ask,
    question: Question,
    recipient: AskRecipient,
    actor_id: UUID,
    event_actor_id: UUID,
) -> Assignment:
    assignment = session.scalar(
        select(Assignment)
        .where(
            Assignment.ask_id == ask.id,
            Assignment.question_id == question.id,
            Assignment.actor_id == actor_id,
        )
        .with_for_update()
    )
    state = _assignment_initial_state(session, ask, question, actor_id)
    if assignment is not None:
        if assignment.origin != AssignmentOrigin.UNSOLICITED:
            raise DraftConflict("recipient already has an Assignment for a selected Question")
        assignment.origin = AssignmentOrigin.ASSIGNED
        assignment.ask_recipient_id = recipient.id
        if assignment.state not in (AssignmentState.RESPONDED, AssignmentState.DELEGATED):
            assignment.state = state
        reason = "unsolicited_converted"
    else:
        assignment = Assignment(
            id=uuid4(),
            project_id=ask.project_id,
            ask_id=ask.id,
            question_id=question.id,
            actor_id=actor_id,
            ask_recipient_id=recipient.id,
            origin=AssignmentOrigin.ASSIGNED,
            state=state,
            delegated_to_actor_id=None,
            child_ask_id=None,
            created_at=SystemClock().now(),
        )
        session.add(assignment)
        reason = "recipient_added"
    session.flush()
    emit_event(
        session,
        SystemClock(),
        EventName.ASSIGNMENT_CREATED,
        actor_id=event_actor_id,
        project_id=ask.project_id,
        ask_id=ask.id,
        question_id=question.id,
        assignment_id=assignment.id,
        ask_recipient_id=recipient.id,
        data={"state": assignment.state.value, "reason": reason},
    )
    return assignment


def _initialize_sent_recipient(
    session: Session, ask: Ask, recipient: AskRecipient, questions: list[Question], actor_id: UUID
) -> None:
    all_questions = list(
        session.scalars(
            select(Question)
            .join(AskQuestion, AskQuestion.question_id == Question.id)
            .where(AskQuestion.ask_id == ask.id, AskQuestion.superseded_at.is_(None))
        )
    )
    assignees = {
        question.id: set(
            session.scalars(
                select(Assignment.actor_id).where(
                    Assignment.ask_id == ask.id,
                    Assignment.question_id == question.id,
                    Assignment.origin != AssignmentOrigin.UNSOLICITED,
                )
            )
        )
        for question in all_questions
    }
    for question in questions:
        assignees[question.id].add(recipient.actor_id)
    try:
        validate_dependency_graph(
            {question.id: question.depends_on for question in all_questions}, assignees
        )
    except ValueError as error:
        raise DraftConflict(str(error)) from error
    ordered = sorted(questions, key=lambda item: item.depends_on is not None)
    for question in ordered:
        _create_or_convert_assignment(
            session, ask, question, recipient, recipient.actor_id, actor_id
        )
        question.close_eligible_at = None


def _active_recipient(session: Session, ask_id: UUID, recipient_id: UUID) -> AskRecipient:
    recipient = session.scalar(
        select(AskRecipient)
        .where(
            AskRecipient.id == recipient_id,
            AskRecipient.ask_id == ask_id,
            AskRecipient.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if recipient is None:
        raise DraftConflict("Recipient not found")
    return recipient
