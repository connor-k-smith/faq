import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.dependencies import derive_assignment_state
from app.domain.enums import (
    ActorKind,
    AskStatus,
    AssignmentOrigin,
    AssignmentState,
    ContactKind,
    OrganizationRole,
    QuestionClosePolicy,
    QuestionOpenTo,
    QuestionState,
    ResponseChannel,
    ResponseDisposition,
)
from app.domain.events import EventName, emit_event
from app.domain.expressions import parse_condition
from app.domain.ports import Clock
from app.domain.settlement import effective_close_policy, settle_question_locked
from app.domain.validation import validate_comment_requirement, validate_value
from app.models.identity import Actor, ContactMethod, Initiative, Membership, Project
from app.models.outcomes import Response
from app.models.work import Ask, AskQuestion, AskRecipient, Assignment, Question, QuestionOption


class ResponseSubmissionError(ValueError):
    pass


@dataclass(frozen=True)
class ResponseSubmission:
    disposition: ResponseDisposition
    value: JsonValue
    comment: str | None
    submission_id: UUID
    source_ip: str | None
    user_agent: str | None
    delegate_display_name: str | None = None
    delegate_email: str | None = None


def submit_response(
    session: Session,
    clock: Clock,
    *,
    recipient_id: UUID,
    assignment_id: UUID,
    submission: ResponseSubmission,
    grace: timedelta = timedelta(minutes=15),
) -> Response:
    row = session.execute(
        select(Assignment, AskRecipient, Ask, Question, Project, Actor)
        .join(AskRecipient, AskRecipient.id == Assignment.ask_recipient_id)
        .join(Ask, Ask.id == Assignment.ask_id)
        .join(Question, Question.id == Assignment.question_id)
        .join(Project, Project.id == Assignment.project_id)
        .join(Actor, Actor.id == Assignment.actor_id)
        .where(Assignment.id == assignment_id, AskRecipient.id == recipient_id)
        .with_for_update(of=(Assignment, Ask, Question))
    ).one_or_none()
    if row is None:
        raise ResponseSubmissionError("Question assignment not found")
    assignment, recipient, ask, question, project, actor = row
    existing = session.scalar(
        select(Response).where(
            Response.assignment_id == assignment.id,
            Response.submission_id == submission.submission_id,
        )
    )
    if existing is not None:
        return existing
    if assignment.child_ask_id is not None:
        raise ResponseSubmissionError("A delegated response cannot be revised")
    now = clock.now()
    settle_question_locked(session, clock, question.id, trigger="lazy")
    if question.state == QuestionState.CLOSED:
        session.flush()
        raise ResponseSubmissionError("This Question is no longer accepting responses")
    if (
        recipient.revoked_at is not None
        or recipient.access_expires_at is None
        or recipient.access_expires_at <= now
        or actor.deleted_at is not None
        or project.archived_at is not None
        or ask.status != AskStatus.SENT
        or question.state != QuestionState.OPEN
        or assignment.state
        not in (AssignmentState.PENDING, AssignmentState.RESPONDED, AssignmentState.DELEGATED)
    ):
        raise ResponseSubmissionError("This Question is no longer accepting responses")
    comment = submission.comment.strip() if submission.comment else None
    value = submission.value
    if submission.disposition == ResponseDisposition.ANSWERED:
        options = list(
            session.scalars(
                select(QuestionOption.value).where(QuestionOption.question_id == question.id)
            )
        )
        validate_value(
            question.primitive,
            value,
            validation=question.validation,
            option_values=options,
        )
        validate_comment_requirement(value, comment, question.require_comment_if)
    else:
        value = None
        if submission.disposition == ResponseDisposition.DELEGATED:
            delegate_name = (submission.delegate_display_name or "").strip()
            if not delegate_name:
                raise ResponseSubmissionError("Delegate display name is required")
            delegate_email = (submission.delegate_email or "").strip().lower() or None
            if delegate_email is not None and (
                "@" not in delegate_email
                or delegate_email.startswith("@")
                or delegate_email.endswith("@")
            ):
                raise ResponseSubmissionError("Delegate email is invalid")
    latest = session.scalar(
        select(func.coalesce(func.max(Response.version), 0)).where(
            Response.assignment_id == assignment.id
        )
    )
    response = Response(
        id=uuid4(),
        assignment_id=assignment.id,
        submission_id=submission.submission_id,
        version=int(latest or 0) + 1,
        disposition=submission.disposition,
        value=cast(object | None, value),
        comment=comment,
        delegated_to_actor_id=None,
        answered_via=ResponseChannel.WEB,
        provenance={
            "auth": "token",
            "ip": submission.source_ip,
            "ua": submission.user_agent,
        },
        created_at=now,
    )
    session.add(response)
    session.flush()
    if submission.disposition == ResponseDisposition.DELEGATED:
        _create_delegated_child(
            session,
            clock,
            parent=ask,
            source=question,
            parent_assignment=assignment,
            response=response,
            display_name=delegate_name,
            email=delegate_email,
        )
    assignment.state = (
        AssignmentState.DELEGATED
        if submission.disposition == ResponseDisposition.DELEGATED
        else AssignmentState.RESPONDED
    )
    emit_event(
        session,
        clock,
        EventName.RESPONSE_SUBMITTED,
        actor_id=assignment.actor_id,
        project_id=assignment.project_id,
        ask_id=assignment.ask_id,
        question_id=assignment.question_id,
        assignment_id=assignment.id,
        ask_recipient_id=recipient.id,
        data={"version": response.version, "disposition": response.disposition.value},
        ip=submission.source_ip,
        user_agent=submission.user_agent,
    )
    _evaluate_dependents(session, clock, ask, assignment, response, grace)
    _update_grace(session, clock, ask, question, grace)
    session.flush()
    return response


def _create_delegated_child(
    session: Session,
    clock: Clock,
    *,
    parent: Ask,
    source: Question,
    parent_assignment: Assignment,
    response: Response,
    display_name: str,
    email: str | None,
) -> None:
    now = clock.now()
    actor = Actor(
        id=uuid4(),
        kind=ActorKind.HUMAN,
        organization_role=OrganizationRole.MEMBER,
        display_name=display_name,
        firebase_uid=None,
        avatar_url=None,
        timezone="UTC",
        deleted_at=None,
        created_at=now,
    )
    session.add(actor)
    if email is not None:
        session.add(
            ContactMethod(
                id=uuid4(), actor_id=actor.id, kind=ContactKind.EMAIL, value=email,
                verified_at=None, opted_in_at=None, priority=0, quiet_hours=None, created_at=now,
            )
        )
    child = Ask(
        id=uuid4(), project_id=parent.project_id, initiative_id=parent.initiative_id,
        parent_ask_id=parent.id, title=parent.title, intro=(
            "\n\n".join(filter(None, (
                parent.intro,
                "This delegated question was created after its prerequisite condition was "
                "satisfied in the original request." if source.depends_on is not None else None,
            ))) or None
        ), created_by=parent.created_by, deadline=None, default_note=parent.default_note,
        status=AskStatus.SENT, owner_id=parent.owner_id, sent_at=now, closed_at=None,
        share_message=parent.share_message, critiques_overridden=parent.critiques_overridden,
        created_at=now,
    )
    copied = Question(
        id=uuid4(), project_id=source.project_id, template_id=source.template_id,
        primitive=source.primitive, version=source.version, supersedes_question_id=None,
        copied_from_question_id=source.id, state=QuestionState.OPEN, origin=source.origin,
        prompt=source.prompt, help_text=source.help_text, context_refs=source.context_refs,
        open_to=source.open_to, allow_comment=source.allow_comment,
        validation=source.validation, require_comment_if=source.require_comment_if,
        depends_on=None, response_visibility=source.response_visibility,
        anonymous=source.anonymous, proposed_value=source.proposed_value,
        proposed_rationale=source.proposed_rationale, close_policy=source.close_policy,
        auto_commit=source.auto_commit, auto_commit_if=source.auto_commit_if,
        created_by=source.created_by, critiques_overridden=source.critiques_overridden,
        close_eligible_at=None, closed_at=None, outcome_effect=None,
        outcome_effect_note=None, created_at=now,
    )
    recipient = AskRecipient(
        id=uuid4(), project_id=parent.project_id, ask_id=child.id, actor_id=actor.id,
        display_name=display_name,
        token_hash=hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest(),
        token_issued_at=now, session_version=1, revoked_at=None,
        access_expires_at=now + timedelta(days=90), share_marked_sent_at=None, created_at=now,
    )
    child_assignment = Assignment(
        id=uuid4(), project_id=parent.project_id, ask_id=child.id, question_id=copied.id,
        actor_id=actor.id, ask_recipient_id=recipient.id, origin=AssignmentOrigin.DELEGATED,
        state=AssignmentState.PENDING, delegated_to_actor_id=None, child_ask_id=None,
        created_at=now,
    )
    session.add_all([child, copied])
    session.flush()
    session.add(AskQuestion(project_id=parent.project_id, ask_id=child.id, question_id=copied.id,
                            ordinal=1, superseded_at=None))
    session.add(recipient)
    session.flush()
    session.add(child_assignment)
    for option in session.scalars(
        select(QuestionOption)
        .where(QuestionOption.question_id == source.id)
        .order_by(QuestionOption.ordinal)
    ):
        session.add(QuestionOption(
            id=uuid4(), question_id=copied.id, ordinal=option.ordinal, value=option.value,
            label=option.label, consequence=option.consequence, triggers=option.triggers,
        ))
    parent_assignment.delegated_to_actor_id = actor.id
    parent_assignment.child_ask_id = child.id
    response.delegated_to_actor_id = actor.id
    lineage: dict[str, object] = {
        "parent_ask_id": str(parent.id),
        "child_ask_id": str(child.id),
        "source_question_id": str(source.id),
        "child_question_id": str(copied.id),
    }
    emit_event(session, clock, EventName.ASK_CREATED, actor_id=parent_assignment.actor_id,
               project_id=parent.project_id, ask_id=child.id, data=lineage)
    emit_event(session, clock, EventName.QUESTION_CREATED, actor_id=parent_assignment.actor_id,
               project_id=parent.project_id, ask_id=child.id, question_id=copied.id, data=lineage)
    emit_event(session, clock, EventName.RECIPIENT_ADDED, actor_id=parent_assignment.actor_id,
               project_id=parent.project_id, ask_id=child.id,
               ask_recipient_id=recipient.id, data=lineage)
    emit_event(session, clock, EventName.RECIPIENT_CREDENTIAL_ISSUED,
               actor_id=parent_assignment.actor_id, project_id=parent.project_id,
               ask_id=child.id, ask_recipient_id=recipient.id, data=lineage)
    emit_event(session, clock, EventName.ASSIGNMENT_CREATED, actor_id=parent_assignment.actor_id,
               project_id=parent.project_id, ask_id=child.id, question_id=copied.id,
               assignment_id=child_assignment.id, ask_recipient_id=recipient.id, data=lineage)
    emit_event(session, clock, EventName.ASK_SENT, actor_id=parent_assignment.actor_id,
               project_id=parent.project_id, ask_id=child.id, data=lineage)


def submit_unsolicited_response(
    session: Session,
    clock: Clock,
    *,
    actor_id: UUID,
    ask_id: UUID,
    question_id: UUID,
    submission: ResponseSubmission,
) -> Response:
    row = session.execute(
        select(Ask, Question, Project, Initiative, Actor)
        .join(AskQuestion, AskQuestion.ask_id == Ask.id)
        .join(Question, Question.id == AskQuestion.question_id)
        .join(Project, Project.id == Ask.project_id)
        .join(Initiative, Initiative.id == Ask.initiative_id)
        .join(Actor, Actor.id == actor_id)
        .where(
            Ask.id == ask_id,
            Question.id == question_id,
            AskQuestion.superseded_at.is_(None),
        )
        .with_for_update(of=Question)
    ).unique().one_or_none()
    if row is None:
        raise ResponseSubmissionError("Question not found")
    ask, question, project, initiative, actor = row
    membership = session.scalar(
        select(Membership).where(
            Membership.project_id == ask.project_id,
            Membership.actor_id == actor_id,
            Membership.revoked_at.is_(None),
        )
    )
    if membership is None or actor.deleted_at is not None:
        raise ResponseSubmissionError("active Project membership required")
    if question.open_to != QuestionOpenTo.PROJECT_MEMBERS:
        raise ResponseSubmissionError("Question only accepts assigned Responses")
    if (
        project.archived_at is not None
        or initiative.archived_at is not None
        or ask.status not in (AskStatus.SENT, AskStatus.CLOSED)
        or question.state == QuestionState.SUPERSEDED
    ):
        raise ResponseSubmissionError("This Question is not accepting advisory Responses")

    assignment = session.scalar(
        select(Assignment)
        .where(
            Assignment.ask_id == ask.id,
            Assignment.question_id == question.id,
            Assignment.actor_id == actor_id,
        )
        .with_for_update()
    )
    if assignment is not None and assignment.origin != AssignmentOrigin.UNSOLICITED:
        raise ResponseSubmissionError("Assigned respondents must use their assigned response link")
    if assignment is not None:
        existing = session.scalar(
            select(Response).where(
                Response.assignment_id == assignment.id,
                Response.submission_id == submission.submission_id,
            )
        )
        if existing is not None:
            return existing

    now = clock.now()
    late = question.state == QuestionState.CLOSED or ask.status == AskStatus.CLOSED
    comment = submission.comment.strip() if submission.comment else None
    value = submission.value
    if submission.disposition == ResponseDisposition.ANSWERED:
        options = list(
            session.scalars(
                select(QuestionOption.value).where(QuestionOption.question_id == question.id)
            )
        )
        validate_value(
            question.primitive, value, validation=question.validation, option_values=options
        )
        validate_comment_requirement(value, comment, question.require_comment_if)
    else:
        value = None
        if submission.disposition == ResponseDisposition.DELEGATED:
            raise ResponseSubmissionError("Advisory Responses cannot delegate")
    if assignment is None:
        assignment = Assignment(
            id=uuid4(),
            project_id=ask.project_id,
            ask_id=ask.id,
            question_id=question.id,
            actor_id=actor_id,
            ask_recipient_id=None,
            origin=AssignmentOrigin.UNSOLICITED,
            state=AssignmentState.RESPONDED,
            delegated_to_actor_id=None,
            child_ask_id=None,
            created_at=now,
        )
        session.add(assignment)
        session.flush()
    latest = session.scalar(
        select(func.coalesce(func.max(Response.version), 0)).where(
            Response.assignment_id == assignment.id
        )
    )
    response = Response(
        id=uuid4(),
        assignment_id=assignment.id,
        submission_id=submission.submission_id,
        version=int(latest or 0) + 1,
        disposition=submission.disposition,
        value=cast(object | None, value),
        comment=comment,
        delegated_to_actor_id=None,
        answered_via=ResponseChannel.WEB,
        provenance={
            "auth": "session",
            "actor_id": str(actor_id),
            "advisory": True,
            "late": late,
            "ip": submission.source_ip,
            "ua": submission.user_agent,
        },
        created_at=now,
    )
    assignment.state = AssignmentState.RESPONDED
    session.add(response)
    session.flush()
    emit_event(
        session,
        clock,
        EventName.RESPONSE_SUBMITTED,
        actor_id=actor_id,
        project_id=ask.project_id,
        ask_id=ask.id,
        question_id=question.id,
        assignment_id=assignment.id,
        ask_recipient_id=None,
        data={
            "version": response.version,
            "disposition": response.disposition.value,
            "origin": AssignmentOrigin.UNSOLICITED.value,
            "advisory": True,
            "late": late,
        },
        ip=submission.source_ip,
        user_agent=submission.user_agent,
    )
    session.flush()
    return response


def _deadline_has_precedence(ask: Ask, question: Question, now: datetime) -> bool:
    return bool(
        ask.deadline is not None
        and ask.deadline <= now
        and question.close_policy in (QuestionClosePolicy.DEADLINE, QuestionClosePolicy.EITHER)
    )


def _update_grace(
    session: Session, clock: Clock, ask: Ask, question: Question, grace: timedelta
) -> None:
    if effective_close_policy(ask, question) == QuestionClosePolicy.DEADLINE:
        question.close_eligible_at = None
        return
    unresolved = session.scalar(
        select(func.count())
        .select_from(Assignment)
        .where(
            Assignment.ask_id == ask.id,
            Assignment.question_id == question.id,
            Assignment.origin != AssignmentOrigin.UNSOLICITED,
            Assignment.state.in_((AssignmentState.PENDING, AssignmentState.BLOCKED)),
        )
    )
    eligible = session.scalar(
        select(func.count())
        .select_from(Assignment)
        .where(
            Assignment.ask_id == ask.id,
            Assignment.question_id == question.id,
            Assignment.origin != AssignmentOrigin.UNSOLICITED,
            Assignment.state.in_((AssignmentState.RESPONDED, AssignmentState.DELEGATED)),
        )
    )
    question.close_eligible_at = clock.now() + grace if eligible and not unresolved else None


def _evaluate_dependents(
    session: Session,
    clock: Clock,
    ask: Ask,
    prerequisite: Assignment,
    response: Response,
    grace: timedelta,
) -> None:
    rows = session.execute(
        select(Assignment, Question)
        .join(Question, Question.id == Assignment.question_id)
        .where(
            Assignment.ask_id == prerequisite.ask_id,
            Assignment.ask_recipient_id == prerequisite.ask_recipient_id,
            Question.depends_on.is_not(None),
        )
        .order_by(Assignment.id)
        .with_for_update(of=Assignment)
    ).all()
    for dependent, question in rows:
        if question.depends_on is None:
            continue
        condition = parse_condition(question.depends_on, require_question_id=True)
        if condition.question_id != prerequisite.question_id:
            continue
        latest_dependent = session.scalar(
            select(Response)
            .where(Response.assignment_id == dependent.id)
            .order_by(Response.version.desc())
            .limit(1)
        )
        next_state = derive_assignment_state(
            condition,
            prerequisite.state,
            response.value,
            response.disposition,
            latest_dependent.disposition if latest_dependent is not None else None,
        )
        if next_state in (
            AssignmentState.PENDING,
            AssignmentState.RESPONDED,
            AssignmentState.DELEGATED,
        ) and dependent.state in (AssignmentState.BLOCKED, AssignmentState.WITHDRAWN):
            dependent.state = next_state
            emit_event(
                session,
                clock,
                EventName.ASSIGNMENT_ACTIVATED,
                actor_id=dependent.actor_id,
                project_id=dependent.project_id,
                ask_id=dependent.ask_id,
                question_id=dependent.question_id,
                assignment_id=dependent.id,
                ask_recipient_id=dependent.ask_recipient_id,
                data={"prerequisite_question_id": str(prerequisite.question_id)},
            )
        elif next_state == AssignmentState.WITHDRAWN and dependent.state in (
            AssignmentState.BLOCKED,
            AssignmentState.PENDING,
            AssignmentState.RESPONDED,
            AssignmentState.DELEGATED,
        ):
            prior_state = dependent.state
            dependent.state = AssignmentState.WITHDRAWN
            emit_event(
                session,
                clock,
                EventName.ASSIGNMENT_WITHDRAWN,
                actor_id=dependent.actor_id,
                project_id=dependent.project_id,
                ask_id=dependent.ask_id,
                question_id=dependent.question_id,
                assignment_id=dependent.id,
                ask_recipient_id=dependent.ask_recipient_id,
                data={
                    "reason": "dependency_false",
                    "prior_state": prior_state.value,
                    "prerequisite_question_id": str(prerequisite.question_id),
                },
            )
        _update_grace(session, clock, ask, question, grace)
