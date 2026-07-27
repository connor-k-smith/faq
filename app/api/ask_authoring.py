from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.ask_contracts import OptionWrite, QuestionWrite
from app.api.ask_recipients import _create_or_convert_assignment, _latest_response
from app.api.ask_support import DraftConflict, _ask_event, _optional, _required
from app.domain.dependencies import derive_assignment_state
from app.domain.enums import (
    AssignmentOrigin,
    AssignmentState,
    QuestionOrigin,
    QuestionPrimitive,
    QuestionState,
)
from app.domain.events import EventName, emit_event
from app.domain.expressions import validate_dependency_graph
from app.domain.ports import SystemClock
from app.models.work import (
    Ask,
    AskQuestion,
    AskRecipient,
    Assignment,
    Question,
    QuestionOption,
    QuestionTemplate,
)


def _question_template(session: Session, body: QuestionWrite) -> QuestionTemplate:
    template = session.get(QuestionTemplate, body.template_id)
    if (
        template is None
        or not template.builtin
        or template.primitive
        not in (
            QuestionPrimitive.SELECT_ONE,
            QuestionPrimitive.SELECT_MANY,
            QuestionPrimitive.TEXT,
            QuestionPrimitive.NUMBER,
            QuestionPrimitive.DATE,
        )
    ):
        raise DraftConflict("template must use a renderable v1 primitive")
    if template.renderer != "default":
        raise DraftConflict("template is not renderable")
    _required(body.prompt, "Question prompt")
    if (
        template.primitive
        in (
            QuestionPrimitive.TEXT,
            QuestionPrimitive.NUMBER,
            QuestionPrimitive.DATE,
        )
        and body.options
    ):
        raise DraftConflict(f"{template.primitive.value} questions cannot have options")
    if template.primitive in (QuestionPrimitive.SELECT_ONE, QuestionPrimitive.SELECT_MANY):
        if len(body.options) < 2:
            raise DraftConflict(
                f"{template.primitive.value} questions require at least two options"
            )
        values = [_required(option.value, "Option value") for option in body.options]
        labels = [_required(option.label, "Option label") for option in body.options]
        for option in body.options:
            if template.requires_consequence:
                _required(option.consequence or "", "Option consequence")
        if len(set(values)) != len(values):
            raise DraftConflict("option values must be unique")
        if len(set(labels)) != len(labels):
            raise DraftConflict("option labels must be unique")
    return template


def _new_question(
    ask: Ask,
    actor_id: UUID,
    template: QuestionTemplate,
    body: QuestionWrite,
    *,
    origin: QuestionOrigin = QuestionOrigin.AUTHOR,
) -> Question:
    return Question(
        id=uuid4(),
        project_id=ask.project_id,
        template_id=template.id,
        primitive=template.primitive,
        version=1,
        supersedes_question_id=None,
        copied_from_question_id=None,
        state=QuestionState.OPEN,
        origin=origin,
        prompt=_required(body.prompt, "Question prompt"),
        help_text=_optional(body.help_text),
        context_refs=[],
        open_to=body.open_to,
        allow_comment=body.allow_comment,
        validation=template.default_validation,
        require_comment_if=template.default_require_comment_if,
        depends_on=body.depends_on,
        response_visibility=body.response_visibility,
        anonymous=False,
        proposed_value=None,
        proposed_rationale=None,
        close_policy=body.close_policy,
        auto_commit=template.auto_commit,
        auto_commit_if=template.default_auto_commit_if,
        created_by=actor_id,
        critiques_overridden=body.critiques_overridden,
        close_eligible_at=None,
        closed_at=None,
        outcome_effect=None,
        outcome_effect_note=None,
        created_at=SystemClock().now(),
    )


def _initialize_sent_question(
    session: Session, ask: Ask, question: Question, actor_id: UUID
) -> None:
    recipients = list(
        session.scalars(
            select(AskRecipient)
            .where(AskRecipient.ask_id == ask.id, AskRecipient.revoked_at.is_(None))
            .order_by(AskRecipient.id)
            .with_for_update()
        )
    )
    questions = list(
        session.scalars(
            select(Question)
            .join(AskQuestion, AskQuestion.question_id == Question.id)
            .where(AskQuestion.ask_id == ask.id, AskQuestion.superseded_at.is_(None))
        )
    )
    assignees = {
        item.id: set(
            session.scalars(
                select(Assignment.actor_id).where(
                    Assignment.ask_id == ask.id,
                    Assignment.question_id == item.id,
                    Assignment.origin != AssignmentOrigin.UNSOLICITED,
                )
            )
        )
        for item in questions
    }
    assignees[question.id] = {recipient.actor_id for recipient in recipients}
    try:
        validate_dependency_graph({item.id: item.depends_on for item in questions}, assignees)
    except ValueError as error:
        raise DraftConflict(str(error)) from error
    for recipient in recipients:
        _create_or_convert_assignment(
            session, ask, question, recipient, recipient.actor_id, actor_id
        )
    question.close_eligible_at = None


def _validate_and_recompute_sent_assignments(session: Session, ask: Ask) -> None:
    questions = list(
        session.scalars(
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
    )
    assignments = list(
        session.scalars(
            select(Assignment)
            .where(Assignment.ask_id == ask.id, Assignment.origin != AssignmentOrigin.UNSOLICITED)
            .order_by(Assignment.id)
            .with_for_update()
        )
    )
    active_ids = {question.id for question in questions}
    assignees = {
        question.id: {
            assignment.actor_id
            for assignment in assignments
            if assignment.question_id == question.id
        }
        for question in questions
    }
    try:
        dependencies = validate_dependency_graph(
            {question.id: question.depends_on for question in questions}, assignees
        )
    except ValueError as error:
        raise DraftConflict(str(error)) from error
    current = {
        (assignment.actor_id, assignment.question_id): assignment
        for assignment in assignments
        if assignment.question_id in active_ids
    }
    responses = {
        assignment.id: _latest_response(session, assignment.id) for assignment in assignments
    }
    remaining = set(active_ids)
    while remaining:
        ready = [
            question_id
            for question_id in remaining
            if question_id not in dependencies
            or dependencies[question_id].question_id not in remaining
        ]
        if not ready:
            raise DraftConflict("Question dependency graph contains a cycle")
        for question_id in ready:
            condition = dependencies.get(question_id)
            for assignment in assignments:
                if assignment.question_id != question_id:
                    continue
                prerequisite = (
                    current.get((assignment.actor_id, cast(UUID, condition.question_id)))
                    if condition is not None
                    else None
                )
                prerequisite_response = (
                    responses[prerequisite.id] if prerequisite is not None else None
                )
                own_response = responses[assignment.id]
                assignment.state = derive_assignment_state(
                    condition,
                    prerequisite.state if prerequisite is not None else None,
                    prerequisite_response.value if prerequisite_response is not None else None,
                    (
                        prerequisite_response.disposition
                        if prerequisite_response is not None
                        else None
                    ),
                    own_response.disposition if own_response is not None else None,
                )
            remaining.remove(question_id)


def _supersede_question(
    session: Session,
    ask: Ask,
    predecessor: Question,
    assignments: list[Assignment],
    template: QuestionTemplate,
    body: QuestionWrite,
    actor_id: UUID,
) -> None:
    link = session.scalar(
        select(AskQuestion)
        .where(
            AskQuestion.ask_id == ask.id,
            AskQuestion.question_id == predecessor.id,
            AskQuestion.superseded_at.is_(None),
        )
        .with_for_update()
    )
    if link is None or predecessor.state != QuestionState.OPEN:
        raise DraftConflict("Question is no longer open for correction")
    now = SystemClock().now()
    successor = _new_question(ask, actor_id, template, body)
    successor.version = predecessor.version + 1
    successor.supersedes_question_id = predecessor.id
    session.add(successor)
    session.flush()
    _replace_options(session, successor.id, template, body.options)
    link.superseded_at = now
    predecessor.state = QuestionState.SUPERSEDED
    predecessor.close_eligible_at = None
    session.flush()
    session.add(
        AskQuestion(
            project_id=ask.project_id,
            ask_id=ask.id,
            question_id=successor.id,
            ordinal=link.ordinal,
            superseded_at=None,
        )
    )
    session.flush()
    for assignment in assignments:
        assignment.state = AssignmentState.WITHDRAWN
        emit_event(
            session,
            SystemClock(),
            EventName.ASSIGNMENT_WITHDRAWN,
            actor_id=actor_id,
            project_id=ask.project_id,
            ask_id=ask.id,
            question_id=predecessor.id,
            assignment_id=assignment.id,
            ask_recipient_id=assignment.ask_recipient_id,
            data={"reason": "question_superseded", "successor_question_id": str(successor.id)},
        )
        replacement = Assignment(
            id=uuid4(),
            project_id=ask.project_id,
            ask_id=ask.id,
            question_id=successor.id,
            actor_id=assignment.actor_id,
            ask_recipient_id=assignment.ask_recipient_id,
            origin=assignment.origin,
            state=AssignmentState.PENDING,
            delegated_to_actor_id=None,
            child_ask_id=None,
            created_at=now,
        )
        session.add(replacement)
        session.flush()
        emit_event(
            session,
            SystemClock(),
            EventName.ASSIGNMENT_CREATED,
            actor_id=actor_id,
            project_id=ask.project_id,
            ask_id=ask.id,
            question_id=successor.id,
            assignment_id=replacement.id,
            ask_recipient_id=replacement.ask_recipient_id,
            data={"reason": "question_superseded", "predecessor_question_id": str(predecessor.id)},
        )
    _validate_and_recompute_sent_assignments(session, ask)
    _ask_event(
        session,
        actor_id,
        ask,
        EventName.QUESTION_SUPERSEDED,
        question_id=predecessor.id,
        data={
            "successor_question_id": str(successor.id),
            "prior_version": predecessor.version,
            "successor_version": successor.version,
            "ordinal": link.ordinal,
        },
    )


def _replace_options(
    session: Session,
    question_id: UUID,
    template: QuestionTemplate,
    options: list[OptionWrite],
) -> None:
    session.execute(delete(QuestionOption).where(QuestionOption.question_id == question_id))
    if template.primitive in (
        QuestionPrimitive.TEXT,
        QuestionPrimitive.NUMBER,
        QuestionPrimitive.DATE,
    ):
        return
    for ordinal, option in enumerate(options):
        session.add(
            QuestionOption(
                id=uuid4(),
                question_id=question_id,
                ordinal=ordinal,
                value=option.value.strip(),
                label=option.label.strip(),
                consequence=_optional(option.consequence),
                triggers=[trigger.model_dump() for trigger in option.triggers],
            )
        )


def _active_question(
    session: Session, ask_id: UUID, question_id: UUID, *, lock: bool = False
) -> Question:
    statement = (
        select(Question)
        .join(AskQuestion, AskQuestion.question_id == Question.id)
        .where(
            Question.id == question_id,
            AskQuestion.ask_id == ask_id,
            AskQuestion.superseded_at.is_(None),
        )
    )
    if lock:
        statement = statement.with_for_update(of=Question)
    question = session.scalar(statement)
    if question is None:
        raise DraftConflict("Question not found")
    return question
