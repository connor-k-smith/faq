from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import (
    AskStatus,
    AssignmentOrigin,
    AssignmentState,
    DecisionBasis,
    DecisionResponseRole,
    DecisionState,
    DecisionStatementSource,
    OutcomeEffect,
    QuestionPrimitive,
    QuestionState,
    ResponseDisposition,
)
from app.domain.events import EventName, emit_event
from app.domain.expressions import parse_condition
from app.domain.integration_triggers import dispatch_committed_option_triggers
from app.domain.ports import Clock
from app.domain.validation import DomainValidationError, validate_value
from app.models.identity import Initiative, Membership, Project
from app.models.outcomes import Decision, DecisionResponse, Response
from app.models.work import (
    Ask,
    AskQuestion,
    AskRecipient,
    Assignment,
    Question,
    QuestionOption,
)


class DecisionCommitError(ValueError):
    pass


@dataclass(frozen=True)
class DecisionEvidence:
    response_id: UUID
    role: DecisionResponseRole


@dataclass(frozen=True)
class DecisionCommit:
    statement: str
    value: JsonValue
    evidence: tuple[DecisionEvidence, ...]
    outcome_effect: OutcomeEffect
    outcome_effect_note: str | None
    share_with_recipients: bool
    proposal_id: UUID | None = None


def commit_decision(
    session: Session,
    clock: Clock,
    *,
    actor_id: UUID,
    ask_id: UUID,
    question_id: UUID,
    commit: DecisionCommit,
) -> Decision:
    question = session.scalar(
        select(Question)
        .join(AskQuestion, AskQuestion.question_id == Question.id)
        .where(
            Question.id == question_id,
            AskQuestion.ask_id == ask_id,
            AskQuestion.superseded_at.is_(None),
        )
        .with_for_update(of=Question)
    )
    if question is None:
        raise DecisionCommitError("Question not found")
    ask = session.scalar(select(Ask).where(Ask.id == ask_id).with_for_update())
    if ask is None:
        raise DecisionCommitError("Ask not found")
    active_member = session.scalar(
        select(Membership.actor_id).where(
            Membership.project_id == ask.project_id,
            Membership.actor_id == actor_id,
            Membership.revoked_at.is_(None),
        )
    )
    project = session.get(Project, ask.project_id)
    initiative = session.get(Initiative, ask.initiative_id)
    if active_member is None or project is None or initiative is None:
        raise DecisionCommitError("active Project membership required")
    if project.archived_at is not None or initiative.archived_at is not None:
        raise DecisionCommitError("archived work is read-only")
    if ask.owner_id != actor_id:
        raise DecisionCommitError("only the Ask owner may commit a Decision")
    if ask.status != AskStatus.SENT or question.state not in (
        QuestionState.OPEN,
        QuestionState.CLOSED,
    ):
        raise DecisionCommitError("Question is not open for resolution")
    existing_decision = session.scalar(
        select(Decision)
        .where(
            Decision.question_id == question.id,
            Decision.state.in_((DecisionState.PROPOSED, DecisionState.COMMITTED)),
        )
        .with_for_update()
    )
    if existing_decision is not None and existing_decision.state == DecisionState.COMMITTED:
        raise DecisionCommitError("Question already has a Decision")
    if commit.proposal_id is not None and (
        existing_decision is None or existing_decision.id != commit.proposal_id
    ):
        raise DecisionCommitError("Decision proposal is stale")
    was_closed = question.state == QuestionState.CLOSED

    statement = commit.statement.strip()
    if not statement:
        raise DecisionCommitError("canonical statement is required")
    note = commit.outcome_effect_note.strip() if commit.outcome_effect_note else None
    if commit.outcome_effect in (OutcomeEffect.CLARIFIED, OutcomeEffect.CHANGED) and not note:
        raise DecisionCommitError("an outcome effect note is required")
    value = _validate_decision_value(session, question, commit.value)
    responses = _validate_evidence(session, ask, question, commit.evidence)
    now = clock.now()
    computed = existing_decision.provenance.get("computed") if existing_decision else None
    computed_value = computed.get("value") if isinstance(computed, dict) else None
    has_winner = bool(computed.get("has_winner")) if isinstance(computed, dict) else False
    if has_winner and value == computed_value and existing_decision is not None:
        basis = existing_decision.basis
    elif has_winner:
        basis = DecisionBasis.ASKER_OVERRIDE
    else:
        basis = DecisionBasis.ASKER_JUDGMENT
    decision = existing_decision or Decision(
        id=uuid4(),
        project_id=ask.project_id,
        question_id=question.id,
        ask_id=ask.id,
        state=DecisionState.COMMITTED,
        basis=basis,
        value=cast(object | None, value),
        statement=statement,
        statement_source=DecisionStatementSource.OWNER,
        decided_by=actor_id,
        supersedes_decision_id=None,
        provenance={"path": "manual"},
        shared_with_recipients_at=now if commit.share_with_recipients else None,
        committed_at=now,
        created_at=now,
    )
    decision.state = DecisionState.COMMITTED
    decision.basis = basis
    decision.value = cast(object | None, value)
    decision.statement = statement
    decision.statement_source = DecisionStatementSource.OWNER
    decision.decided_by = actor_id
    decision.provenance = {
        **(existing_decision.provenance if existing_decision else {}),
        "confirmation": {
            "path": "owner",
            "changed_computed_winner": has_winner and value != computed_value,
        },
    }
    decision.shared_with_recipients_at = now if commit.share_with_recipients else None
    decision.committed_at = now
    session.add(decision)
    session.flush()
    _supersede_predecessor(session, clock, ask, question, decision, actor_id)
    existing_links = list(
        session.scalars(select(DecisionResponse).where(DecisionResponse.decision_id == decision.id))
    )
    evidence_pairs = list(zip(commit.evidence, responses, strict=True))
    if not evidence_pairs and existing_links:
        evidence_pairs = []
    else:
        for link in existing_links:
            session.delete(link)
        session.flush()
    for evidence, response in evidence_pairs:
        assignment = session.get(Assignment, response.assignment_id)
        if assignment is None:
            raise DecisionCommitError("evidence Assignment not found")
        session.add(
            DecisionResponse(
                decision_id=decision.id,
                response_id=response.id,
                assignment_id=assignment.id,
                project_id=ask.project_id,
                ask_id=ask.id,
                question_id=question.id,
                role=evidence.role,
            )
        )

    question.state = QuestionState.CLOSED
    question.closed_at = now
    question.outcome_effect = commit.outcome_effect
    question.outcome_effect_note = note
    pending = list(
        session.scalars(
            select(Assignment).where(
                Assignment.ask_id == ask.id,
                Assignment.question_id == question.id,
                Assignment.state == AssignmentState.PENDING,
            )
        )
    )
    for assignment in pending:
        assignment.state = AssignmentState.EXPIRED
        emit_event(
            session,
            clock,
            EventName.ASSIGNMENT_EXPIRED,
            actor_id=actor_id,
            project_id=ask.project_id,
            ask_id=ask.id,
            question_id=question.id,
            assignment_id=assignment.id,
            ask_recipient_id=assignment.ask_recipient_id,
            data={"reason": "manual_resolution"},
        )
    determining = sum(item.role == DecisionResponseRole.DETERMINING for item in commit.evidence)
    emit_event(
        session,
        clock,
        EventName.DECISION_COMMITTED,
        actor_id=actor_id,
        project_id=ask.project_id,
        ask_id=ask.id,
        question_id=question.id,
        data={
            "decision_id": str(decision.id),
            "basis": decision.basis.value,
            "evidence_count": len(commit.evidence),
            "determining_count": determining,
        },
    )
    dispatch_committed_option_triggers(
        session,
        clock,
        ask=ask,
        question=question,
        decision=decision,
        actor_id=actor_id,
    )
    emit_event(
        session,
        clock,
        EventName.QUESTION_OUTCOME_RECORDED,
        actor_id=actor_id,
        project_id=ask.project_id,
        ask_id=ask.id,
        question_id=question.id,
        data={"effect": commit.outcome_effect.value},
    )
    if commit.share_with_recipients:
        emit_event(
            session,
            clock,
            EventName.DECISION_SHARED,
            actor_id=actor_id,
            project_id=ask.project_id,
            ask_id=ask.id,
            question_id=question.id,
            data={"decision_id": str(decision.id)},
        )
    if not was_closed:
        emit_event(
            session,
            clock,
            EventName.QUESTION_CLOSED,
            actor_id=actor_id,
            project_id=ask.project_id,
            ask_id=ask.id,
            question_id=question.id,
            data={"reason": "manual_resolution", "decision_id": str(decision.id)},
        )

    dependent_questions = list(
        session.scalars(
            select(Question)
            .join(AskQuestion, AskQuestion.question_id == Question.id)
            .where(
                AskQuestion.ask_id == ask.id,
                AskQuestion.superseded_at.is_(None),
                Question.state == QuestionState.OPEN,
                Question.depends_on.is_not(None),
            )
        )
    )
    for dependent in dependent_questions:
        if dependent.depends_on is None:
            continue
        condition = parse_condition(dependent.depends_on, require_question_id=True)
        if condition.question_id != question.id:
            continue
        states = list(
            session.scalars(
                select(Assignment.state).where(
                    Assignment.ask_id == ask.id,
                    Assignment.question_id == dependent.id,
                    Assignment.origin != AssignmentOrigin.UNSOLICITED,
                )
            )
        )
        if states and all(state == AssignmentState.WITHDRAWN for state in states):
            dependent.state = QuestionState.CLOSED
            dependent.closed_at = clock.now()
            emit_event(
                session,
                clock,
                EventName.QUESTION_CLOSED,
                actor_id=actor_id,
                project_id=ask.project_id,
                ask_id=ask.id,
                question_id=dependent.id,
                data={
                    "reason": "all_dependent_assignments_withdrawn",
                    "prerequisite_question_id": str(question.id),
                },
            )

    session.flush()
    open_questions = session.scalar(
        select(func.count())
        .select_from(Question)
        .join(AskQuestion, AskQuestion.question_id == Question.id)
        .where(
            AskQuestion.ask_id == ask.id,
            AskQuestion.superseded_at.is_(None),
            Question.state == QuestionState.OPEN,
        )
    )
    proposals = session.scalar(
        select(func.count())
        .select_from(Decision)
        .where(Decision.ask_id == ask.id, Decision.state == DecisionState.PROPOSED)
    )
    missing_outcomes = session.scalar(
        select(func.count())
        .select_from(Question)
        .join(AskQuestion, AskQuestion.question_id == Question.id)
        .where(
            AskQuestion.ask_id == ask.id,
            AskQuestion.superseded_at.is_(None),
            Question.state == QuestionState.CLOSED,
            Question.outcome_effect.is_(None),
            select(Assignment.id)
            .where(
                Assignment.question_id == Question.id,
                Assignment.origin != AssignmentOrigin.UNSOLICITED,
                Assignment.state != AssignmentState.WITHDRAWN,
            )
            .correlate(Question)
            .exists(),
        )
    )
    if not open_questions and not proposals and not missing_outcomes:
        ask.status = AskStatus.CLOSED
        ask.closed_at = now
        expiry_cap = now + timedelta(days=30)
        recipients = list(
            session.scalars(
                select(AskRecipient).where(
                    AskRecipient.ask_id == ask.id,
                    AskRecipient.revoked_at.is_(None),
                    AskRecipient.access_expires_at.is_not(None),
                )
            )
        )
        for recipient in recipients:
            if recipient.access_expires_at and recipient.access_expires_at > expiry_cap:
                recipient.access_expires_at = expiry_cap
        emit_event(
            session,
            clock,
            EventName.ASK_CLOSED,
            actor_id=actor_id,
            project_id=ask.project_id,
            ask_id=ask.id,
            data={"reason": "all_questions_decided"},
        )
    session.flush()
    return decision


def supersede_predecessor_for_committed_decision(
    session: Session, clock: Clock, ask: Ask, question: Question, decision: Decision
) -> None:
    """Apply successor lineage for an automatically committed Decision."""
    _supersede_predecessor(session, clock, ask, question, decision, None)


def _supersede_predecessor(
    session: Session,
    clock: Clock,
    ask: Ask,
    question: Question,
    decision: Decision,
    actor_id: UUID | None,
) -> None:
    if question.supersedes_question_id is None:
        return
    prior = session.scalar(
        select(Decision)
        .where(
            Decision.question_id == question.supersedes_question_id,
            Decision.state.in_((DecisionState.COMMITTED, DecisionState.SUPERSEDED)),
        )
        .with_for_update()
    )
    if prior is None:
        predecessor_ask_id = session.scalar(
            select(AskQuestion.ask_id).where(
                AskQuestion.question_id == question.supersedes_question_id
            )
        )
        if predecessor_ask_id == ask.id:
            return
        raise DecisionCommitError("successor Question has no committed predecessor Decision")
    existing = session.scalar(
        select(Decision.id).where(
            Decision.supersedes_decision_id == prior.id, Decision.id != decision.id
        )
    )
    if existing is not None:
        raise DecisionCommitError("predecessor Decision already has a successor")
    if prior.id == decision.id:
        raise DecisionCommitError("a Decision cannot supersede itself")
    decision.supersedes_decision_id = prior.id
    prior.state = DecisionState.SUPERSEDED
    emit_event(
        session,
        clock,
        EventName.DECISION_SUPERSEDED,
        actor_id=actor_id,
        project_id=ask.project_id,
        ask_id=ask.id,
        question_id=question.id,
        data={
            "prior_decision_id": str(prior.id),
            "successor_decision_id": str(decision.id),
            "prior_ask_id": str(prior.ask_id),
        },
    )


def _validate_decision_value(session: Session, question: Question, value: JsonValue) -> JsonValue:
    if question.primitive == QuestionPrimitive.TEXT:
        if value is not None:
            raise DecisionCommitError("text Decisions do not have a structured value")
        return None
    if question.primitive == QuestionPrimitive.SELECT_ONE:
        options = set(
            session.scalars(
                select(QuestionOption.value).where(QuestionOption.question_id == question.id)
            )
        )
        if not isinstance(value, str) or value not in options:
            raise DecisionCommitError("Decision value must be one of the Question options")
        return value
    if question.primitive in (QuestionPrimitive.NUMBER, QuestionPrimitive.DATE):
        try:
            validate_value(question.primitive, value, validation=question.validation)
        except DomainValidationError as error:
            raise DecisionCommitError(str(error)) from error
        return value
    if question.primitive == QuestionPrimitive.SELECT_MANY:
        options = set(
            session.scalars(
                select(QuestionOption.value).where(QuestionOption.question_id == question.id)
            )
        )
        try:
            validate_value(
                QuestionPrimitive.SELECT_MANY,
                value,
                validation=question.validation,
                option_values=options,
            )
        except DomainValidationError as error:
            raise DecisionCommitError(str(error)) from error
        return value
    raise DecisionCommitError("Question primitive is not supported")


def _validate_evidence(
    session: Session,
    ask: Ask,
    question: Question,
    evidence: tuple[DecisionEvidence, ...],
) -> list[Response]:
    if len({item.response_id for item in evidence}) != len(evidence):
        raise DecisionCommitError("evidence Responses must be unique")
    responses: list[Response] = []
    assignments: set[UUID] = set()
    for item in evidence:
        row = session.execute(
            select(Response, Assignment)
            .join(Assignment, Assignment.id == Response.assignment_id)
            .where(Response.id == item.response_id)
        ).one_or_none()
        if row is None:
            raise DecisionCommitError("evidence Response not found")
        response, assignment = row
        if (
            assignment.ask_id != ask.id
            or assignment.question_id != question.id
            or assignment.project_id != ask.project_id
        ):
            raise DecisionCommitError("evidence Response belongs to another Question")
        if assignment.id in assignments:
            raise DecisionCommitError("only one Response per Assignment may be evidence")
        latest_version = session.scalar(
            select(func.max(Response.version)).where(Response.assignment_id == assignment.id)
        )
        if response.version != latest_version:
            raise DecisionCommitError("only the latest Response revision may be evidence")
        if (
            item.role == DecisionResponseRole.DETERMINING
            and (
                response.disposition != ResponseDisposition.ANSWERED
                or assignment.origin == AssignmentOrigin.UNSOLICITED
            )
        ):
            raise DecisionCommitError(
                "only substantive assigned answers may determine a Decision"
            )
        assignments.add(assignment.id)
        responses.append(response)
    return responses
