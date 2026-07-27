from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.decisions import supersede_predecessor_for_committed_decision
from app.domain.enums import (
    AskStatus,
    AssignmentOrigin,
    AssignmentState,
    DecisionBasis,
    DecisionResponseRole,
    DecisionState,
    DecisionStatementSource,
    OutcomeEffect,
    QuestionClosePolicy,
    QuestionPrimitive,
    QuestionState,
    ResponseDisposition,
)
from app.domain.events import EventName, emit_event
from app.domain.expressions import evaluate_condition, parse_condition
from app.domain.integration_triggers import dispatch_committed_option_triggers
from app.domain.ports import Clock
from app.domain.resolution import (
    RENDERER_VERSION,
    Resolution,
    ResolutionInput,
    render_select_one,
    resolve,
)
from app.models.outcomes import Decision, DecisionResponse, Response
from app.models.work import Ask, AskQuestion, AskRecipient, Assignment, Question, QuestionOption


class OutcomeRecordingError(ValueError):
    pass


SettlementTrigger = Literal["direct", "lazy", "scheduler"]


@dataclass(frozen=True)
class SettlementResult:
    question_id: UUID
    settled: bool
    reason: str | None = None
    decision: Decision | None = None


def effective_close_policy(ask: Ask, question: Question) -> QuestionClosePolicy:
    """A deadline-less deadline/either policy behaves as all-responded."""
    if ask.deadline is None and question.close_policy in (
        QuestionClosePolicy.DEADLINE,
        QuestionClosePolicy.EITHER,
    ):
        return QuestionClosePolicy.ALL_RESPONDED
    return question.close_policy


def record_outcome_effect(
    session: Session,
    clock: Clock,
    *,
    actor_id: UUID,
    ask_id: UUID,
    question_id: UUID,
    effect: OutcomeEffect,
    note: str | None,
) -> None:
    question = session.scalar(select(Question).where(Question.id == question_id).with_for_update())
    ask = session.scalar(select(Ask).where(Ask.id == ask_id).with_for_update())
    if question is None or ask is None or ask.owner_id != actor_id:
        raise OutcomeRecordingError("only the Ask owner may record the outcome")
    decision = session.scalar(
        select(Decision).where(
            Decision.ask_id == ask.id,
            Decision.question_id == question.id,
            Decision.state == DecisionState.COMMITTED,
        )
    )
    if decision is None or question.state != QuestionState.CLOSED:
        raise OutcomeRecordingError("Question has no committed Decision")
    clean_note = note.strip() if note else None
    if effect in (OutcomeEffect.CLARIFIED, OutcomeEffect.CHANGED) and not clean_note:
        raise OutcomeRecordingError("an outcome effect note is required")
    question.outcome_effect = effect
    question.outcome_effect_note = clean_note
    emit_event(
        session,
        clock,
        EventName.QUESTION_OUTCOME_RECORDED,
        actor_id=actor_id,
        project_id=ask.project_id,
        ask_id=ask.id,
        question_id=question.id,
        data={"effect": effect.value},
    )
    _maybe_close_ask(session, clock, ask)
    session.flush()


def settle_question(session: Session, clock: Clock, question_id: UUID) -> Decision | None:
    result = settle_question_locked(session, clock, question_id)
    return result.decision


def settle_question_locked(
    session: Session,
    clock: Clock,
    question_id: UUID,
    *,
    trigger: SettlementTrigger = "direct",
    run_id: UUID | None = None,
) -> SettlementResult:
    question = session.scalar(select(Question).where(Question.id == question_id).with_for_update())
    if question is None or question.state != QuestionState.OPEN:
        return SettlementResult(question_id, False)
    ask = session.scalar(
        select(Ask).where(Ask.id == _ask_id(session, question.id)).with_for_update()
    )
    if ask is None or ask.status != AskStatus.SENT:
        return SettlementResult(question_id, False)
    now = clock.now()
    policy = effective_close_policy(ask, question)
    deadline = bool(
        ask.deadline is not None
        and ask.deadline <= now
        and policy in (QuestionClosePolicy.DEADLINE, QuestionClosePolicy.EITHER)
    )

    assignments = list(
        session.scalars(
            select(Assignment)
            .where(Assignment.ask_id == ask.id, Assignment.question_id == question.id)
            .order_by(Assignment.id)
            .with_for_update()
        )
    )
    unresolved = any(
        item.state in (AssignmentState.PENDING, AssignmentState.BLOCKED) for item in assignments
    )
    responded = any(
        item.state in (AssignmentState.RESPONDED, AssignmentState.DELEGATED) for item in assignments
    )
    grace_due = bool(
        policy != QuestionClosePolicy.DEADLINE
        and question.close_eligible_at is not None
        and question.close_eligible_at <= now
    )
    grace = grace_due and (trigger == "direct" or (responded and not unresolved))
    if not deadline and not grace:
        if question.close_eligible_at is not None and (unresolved or not responded):
            question.close_eligible_at = None
        return SettlementResult(question_id, False)
    event_data: dict[str, object] = {"trigger": trigger}
    if run_id is not None:
        event_data["run_id"] = str(run_id)
    if deadline:
        for assignment in assignments:
            if assignment.state == AssignmentState.PENDING:
                assignment.state = AssignmentState.EXPIRED
                emit_event(
                    session,
                    clock,
                    EventName.ASSIGNMENT_EXPIRED,
                    actor_id=None,
                    project_id=ask.project_id,
                    ask_id=ask.id,
                    question_id=question.id,
                    assignment_id=assignment.id,
                    ask_recipient_id=assignment.ask_recipient_id,
                    data={"reason": "deadline", **event_data},
                )
        _withdraw_blocked_dependents(session, clock, ask, question.id, event_data)

    eligible = [
        item
        for item in assignments
        if item.origin != AssignmentOrigin.UNSOLICITED
        and item.state not in (AssignmentState.BLOCKED, AssignmentState.WITHDRAWN)
    ]
    latest = _latest_responses(session, [item.id for item in eligible])
    substantive = [
        (item, latest[item.id])
        for item in eligible
        if item.id in latest and latest[item.id].disposition == ResponseDisposition.ANSWERED
    ]
    vote_counts = Counter(
        response.value
        for _, response in substantive
        if question.primitive == QuestionPrimitive.SELECT_ONE
        and isinstance(response.value, str)
    )
    assigned = [item for item in assignments if item.origin != AssignmentOrigin.UNSOLICITED]
    if assigned and all(item.state == AssignmentState.WITHDRAWN for item in assigned):
        _close_question(
            session,
            clock,
            ask,
            question,
            "all_assignments_withdrawn",
            None,
            event_data,
        )
        _maybe_close_ask(session, clock, ask, event_data)
        return SettlementResult(question_id, True, "all_assignments_withdrawn")

    result = resolve(
        ResolutionInput(
            len(eligible),
            tuple(cast(JsonValue, response.value) for _, response in substantive),
            question.primitive,
            deadline,
        )
    )
    revision_values = {
        "directional_check": {"mostly", "no"},
        "assertion": {"partially", "reject"},
    }
    if result.value in revision_values.get(question.template_id, set()):
        result = Resolution(
            DecisionBasis.REVISION, result.value, result.has_winner, result.conflict
        )
    option_rows = session.execute(
        select(QuestionOption.value, QuestionOption.label).where(
            QuestionOption.question_id == question.id
        )
    ).all()
    options: dict[str, str] = {value: label for value, label in option_rows}
    statement = None
    if (
        result.has_winner
        and question.primitive == QuestionPrimitive.SELECT_ONE
        and isinstance(result.value, str)
    ):
        label = options.get(result.value)
        if label is not None:
            statement = (
                question.prompt.strip()
                if question.template_id == "assertion" and result.value == "confirm"
                else render_select_one(question.prompt, label)
            )
    auto = bool(statement and question.auto_commit and _auto_commit_matches(question, result.value))
    decision = Decision(
        id=uuid4(),
        project_id=ask.project_id,
        question_id=question.id,
        ask_id=ask.id,
        state=DecisionState.PROPOSED,
        basis=result.basis,
        value=cast(object | None, result.value),
        statement=statement,
        statement_source=DecisionStatementSource.DETERMINISTIC if statement else None,
        decided_by=ask.owner_id,
        supersedes_decision_id=None,
        provenance={
            "path": "automatic",
            "renderer": RENDERER_VERSION if statement else None,
            "computed": {
                "basis": result.basis.value,
                "value": result.value,
                "has_winner": result.has_winner,
                "conflict": result.conflict,
                "eligible_count": len(eligible),
                "substantive_count": len(substantive),
                "quorum_met": len(substantive) > len(eligible) / 2,
                "vote_counts": dict(vote_counts),
            },
        },
        shared_with_recipients_at=None,
        committed_at=None,
        created_at=now,
    )
    session.add(decision)
    session.flush()
    for assignment, response in substantive:
        session.add(
            DecisionResponse(
                decision_id=decision.id,
                response_id=response.id,
                assignment_id=assignment.id,
                project_id=ask.project_id,
                ask_id=ask.id,
                question_id=question.id,
                role=DecisionResponseRole.DETERMINING,
            )
        )
    emit_event(
        session,
        clock,
        EventName.DECISION_PROPOSED,
        actor_id=None,
        project_id=ask.project_id,
        ask_id=ask.id,
        question_id=question.id,
        data={
            "decision_id": str(decision.id),
            "basis": result.basis.value,
            "conflict": result.conflict,
            **event_data,
        },
    )
    if auto:
        decision.state = DecisionState.COMMITTED
        decision.committed_at = now
        supersede_predecessor_for_committed_decision(session, clock, ask, question, decision)
        emit_event(
            session,
            clock,
            EventName.DECISION_COMMITTED,
            actor_id=None,
            project_id=ask.project_id,
            ask_id=ask.id,
            question_id=question.id,
            data={
                "decision_id": str(decision.id),
                "basis": result.basis.value,
                "automatic": True,
                **event_data,
            },
        )
        dispatch_committed_option_triggers(
            session,
            clock,
            ask=ask,
            question=question,
            decision=decision,
            actor_id=None,
        )
    _close_question(
        session,
        clock,
        ask,
        question,
        "deadline" if deadline else "grace_elapsed",
        decision,
        event_data,
    )
    _maybe_close_ask(session, clock, ask, event_data)
    reason = "deadline" if deadline else "grace_elapsed"
    return SettlementResult(question_id, True, reason, decision)


def settle_ask(
    session: Session, clock: Clock, ask_id: UUID, *, trigger: SettlementTrigger = "direct"
) -> bool:
    ask = session.get(Ask, ask_id)
    if ask is None or ask.status != AskStatus.SENT:
        return False
    now = clock.now()
    deadline_due = ask.deadline is not None and ask.deadline <= now
    due = Question.close_eligible_at <= now
    if deadline_due:
        due = due | Question.close_policy.in_(
            (QuestionClosePolicy.DEADLINE, QuestionClosePolicy.EITHER)
        )
    ids = list(
        session.scalars(
            select(Question.id)
            .join(AskQuestion)
            .where(
                AskQuestion.ask_id == ask_id,
                AskQuestion.superseded_at.is_(None),
                Question.state == QuestionState.OPEN,
                due,
            )
        )
    )
    if not ids:
        return False
    for question_id in ids:
        settle_question_locked(session, clock, question_id, trigger=trigger)
    session.flush()
    return True


def _ask_id(session: Session, question_id: UUID) -> UUID:
    value = session.scalar(select(AskQuestion.ask_id).where(AskQuestion.question_id == question_id))
    if value is None:
        raise RuntimeError("Question has no Ask")
    return value


def _latest_responses(session: Session, assignment_ids: list[UUID]) -> dict[UUID, Response]:
    if not assignment_ids:
        return {}
    rows = session.scalars(
        select(Response)
        .where(Response.assignment_id.in_(assignment_ids))
        .order_by(Response.assignment_id, Response.version.desc())
    ).all()
    latest: dict[UUID, Response] = {}
    for row in rows:
        latest.setdefault(row.assignment_id, row)
    return latest


def _auto_commit_matches(question: Question, value: JsonValue) -> bool:
    if question.primitive != QuestionPrimitive.SELECT_ONE:
        return False
    if question.auto_commit_if is None:
        return True
    condition = parse_condition(question.auto_commit_if, require_question_id=False)
    return evaluate_condition(condition, value, answered=True)


def _close_question(
    session: Session,
    clock: Clock,
    ask: Ask,
    question: Question,
    reason: str,
    decision: Decision | None,
    trigger_data: dict[str, object] | None = None,
) -> None:
    question.state = QuestionState.CLOSED
    question.closed_at = clock.now()
    question.close_eligible_at = None
    emit_event(
        session,
        clock,
        EventName.QUESTION_CLOSED,
        actor_id=None if trigger_data else ask.owner_id,
        project_id=ask.project_id,
        ask_id=ask.id,
        question_id=question.id,
        data={
            "reason": reason,
            "decision_id": str(decision.id) if decision else None,
            **(trigger_data or {}),
        },
    )


def _withdraw_blocked_dependents(
    session: Session,
    clock: Clock,
    ask: Ask,
    prerequisite_id: UUID,
    event_data: dict[str, object],
) -> None:
    """Withdraw same-recipient blocked descendants, then close all-withdrawn branches."""
    frontier = [prerequisite_id]
    while frontier:
        parent_id = frontier.pop(0)
        questions = list(
            session.scalars(
                select(Question)
                .join(AskQuestion, AskQuestion.question_id == Question.id)
                .where(
                    AskQuestion.ask_id == ask.id,
                    Question.state == QuestionState.OPEN,
                    Question.depends_on.is_not(None),
                )
                .order_by(Question.id)
                .with_for_update(of=Question)
            )
        )
        for dependent_question in questions:
            if dependent_question.depends_on is None:
                continue
            condition = parse_condition(
                dependent_question.depends_on, require_question_id=True
            )
            if condition.question_id != parent_id:
                continue
            blocked = list(
                session.scalars(
                    select(Assignment)
                    .where(
                        Assignment.ask_id == ask.id,
                        Assignment.question_id == dependent_question.id,
                        Assignment.origin != AssignmentOrigin.UNSOLICITED,
                        Assignment.state == AssignmentState.BLOCKED,
                    )
                    .order_by(Assignment.id)
                    .with_for_update()
                )
            )
            for assignment in blocked:
                assignment.state = AssignmentState.WITHDRAWN
                emit_event(
                    session,
                    clock,
                    EventName.ASSIGNMENT_WITHDRAWN,
                    actor_id=None,
                    project_id=ask.project_id,
                    ask_id=ask.id,
                    question_id=dependent_question.id,
                    assignment_id=assignment.id,
                    ask_recipient_id=assignment.ask_recipient_id,
                    data={
                        "reason": "prerequisite_expired",
                        "prerequisite_question_id": str(parent_id),
                        **event_data,
                    },
                )
            session.flush()
            remaining = session.scalar(
                select(func.count()).select_from(Assignment).where(
                    Assignment.ask_id == ask.id,
                    Assignment.question_id == dependent_question.id,
                    Assignment.origin != AssignmentOrigin.UNSOLICITED,
                    Assignment.state != AssignmentState.WITHDRAWN,
                )
            )
            if blocked and not remaining:
                _close_question(
                    session,
                    clock,
                    ask,
                    dependent_question,
                    "all_assignments_withdrawn",
                    None,
                    event_data,
                )
                frontier.append(dependent_question.id)


def _maybe_close_ask(
    session: Session,
    clock: Clock,
    ask: Ask,
    trigger_data: dict[str, object] | None = None,
) -> None:
    session.flush()
    open_count = session.scalar(
        select(func.count())
        .select_from(Question)
        .join(AskQuestion)
        .where(
            AskQuestion.ask_id == ask.id,
            AskQuestion.superseded_at.is_(None),
            Question.state == QuestionState.OPEN,
        )
    )
    proposal_count = session.scalar(
        select(func.count())
        .select_from(Decision)
        .where(Decision.ask_id == ask.id, Decision.state == DecisionState.PROPOSED)
    )
    missing_outcomes = session.scalar(
        select(func.count())
        .select_from(Question)
        .join(AskQuestion)
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
    # Automatic commits intentionally stay open until their owner records an outcome effect.
    if open_count or proposal_count or missing_outcomes:
        return
    ask.status = AskStatus.CLOSED
    ask.closed_at = clock.now()
    cap = clock.now() + timedelta(days=30)
    for recipient in session.scalars(select(AskRecipient).where(AskRecipient.ask_id == ask.id)):
        if recipient.access_expires_at and recipient.access_expires_at > cap:
            recipient.access_expires_at = cap
    emit_event(
        session,
        clock,
        EventName.ASK_CLOSED,
        actor_id=None if trigger_data else ask.owner_id,
        project_id=ask.project_id,
        ask_id=ask.id,
        data={"reason": "all_questions_decided", **(trigger_data or {})},
    )
