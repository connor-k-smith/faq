from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.ask_contracts import OptionWrite, QuestionWrite, RecipientWrite
from app.api.ask_projections import _aggregate
from app.api.ask_response_models import RecipientAddResult
from app.api.asks import (
    add_question,
    add_recipient,
    create_successor_ask,
    update_question,
)
from app.config import Settings
from app.domain.access import grant_membership
from app.domain.decisions import DecisionCommit, commit_decision
from app.domain.enums import (
    AskStatus,
    AssignmentOrigin,
    AssignmentState,
    DecisionBasis,
    DecisionState,
    DecisionStatementSource,
    OutcomeEffect,
    QuestionOpenTo,
    ResponseDisposition,
)
from app.domain.responding import ResponseSubmission, submit_unsolicited_response
from app.domain.settlement import settle_question
from app.models.identity import Actor
from app.models.outcomes import Decision, Event
from app.models.work import Ask, AskQuestion, AskRecipient, Assignment, Question
from tests.fakes import DeterministicTokenGenerator
from tests.integration.test_phase3_settlement import (
    SettlementGraph,
    _answer,
    _graph,
    _test_session,
)

pytestmark = pytest.mark.integration

TOKENS = DeterministicTokenGenerator("phase43-secret")
SETTINGS = Settings(public_base_url="https://faq.example")


def test_adding_question_to_sent_ask_targets_every_active_recipient() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=2, auto_commit=False)
        result = add_question(
            graph.ask.id,
            QuestionWrite(
                template_id="approval",
                prompt="Approve the follow-up?",
                options=[
                    OptionWrite(
                        value="approve",
                        label="Approve",
                        triggers=[
                            {
                                "kind": "linear.issue",
                                "team": "ATLAS",
                                "title": "Approved",
                                "body_template": "Decision committed",
                            }
                        ],
                    ),
                    OptionWrite(value="reject", label="Reject"),
                ],
            ),
            graph.owner,
            session,
        )
        added_id = next(item.id for item in result.questions if item.id != graph.question.id)
        assignments = list(
            session.scalars(select(Assignment).where(Assignment.question_id == added_id))
        )
        assert len(assignments) == 2
        assert {item.state for item in assignments} == {AssignmentState.PENDING}
        assert {item.actor_id for item in assignments} == {
            item.actor_id for item in graph.assignments
        }
        added = next(item for item in result.questions if item.id == added_id)
        assert added.options[0].triggers[0].kind == "linear.issue"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Event)
                .where(
                    Event.question_id == added_id,
                    Event.type == "assignment.created",
                )
            )
            == 2
        )


def test_sent_recipient_selected_questions_returns_one_raw_artifact_without_leakage() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        added = add_question(
            graph.ask.id,
            approval_question("Optional detail"),
            graph.owner,
            session,
        )
        selected = next(
            question.id for question in added.questions if question.id != graph.question.id
        )

        result = add_recipient(
            graph.ask.id,
            RecipientWrite(display_name="Selected stakeholder", question_ids=[selected]),
            graph.owner,
            session,
            TOKENS,
            SETTINGS,
        )

        assert isinstance(result, RecipientAddResult)
        payload = result.model_dump(mode="json")
        raw_token = TOKENS.urlsafe(32)
        assert payload["artifact"]["url"] == f"https://faq.example/r/{raw_token}"
        assert str(payload).count(raw_token) == 2  # URL plus the same URL in its share message.
        assert "token_hash" not in str(payload)
        recipient = session.get_one(AskRecipient, result.recipient.id)
        assert recipient.token_hash is not None and raw_token not in recipient.token_hash
        assert recipient.share_marked_sent_at is None
        assignments = list(select_assignment_ids(session, recipient.id))
        assert assignments == [selected]
        preview = next(
            item
            for item in _aggregate(session, graph.ask.id, graph.owner.id).recipient_previews
            if item.recipient_id == recipient.id
        )
        assert [question.id for question in preview.questions] == [selected]
        assert (
            session.scalar(
                select(func.count())
                .select_from(Event)
                .where(
                    Event.ask_recipient_id == recipient.id,
                    Event.type == "ask_recipient.credential_issued",
                )
            )
            == 1
        )


def test_existing_member_recipient_converts_unsolicited_assignment() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        graph.question.open_to = QuestionOpenTo.PROJECT_MEMBERS
        member = graph.assignments[0]
        advisory = submit_unsolicited_response(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=graph.ask.id,
            question_id=graph.question.id,
            submission=ResponseSubmission(
                ResponseDisposition.ANSWERED, "reject", "Context", uuid4(), None, "phase43"
            ),
        )
        unsolicited = session.get_one(Assignment, advisory.assignment_id)

        result = add_recipient(
            graph.ask.id,
            RecipientWrite(actor_id=graph.owner.id, question_ids=[graph.question.id]),
            graph.owner,
            session,
            TOKENS,
            SETTINGS,
        )

        assert isinstance(result, RecipientAddResult)
        session.refresh(unsolicited)
        assert result.recipient.actor_id == graph.owner.id
        assert unsolicited.origin == AssignmentOrigin.ASSIGNED
        assert unsolicited.ask_recipient_id == result.recipient.id
        assert unsolicited.state == AssignmentState.RESPONDED
        event = session.scalar(
            select(Event)
            .where(Event.assignment_id == unsolicited.id, Event.type == "assignment.created")
            .order_by(Event.id.desc())
        )
        assert event is not None and event.data["reason"] == "unsolicited_converted"
        assert member.actor_id != result.recipient.actor_id


def test_overdue_recipient_requires_and_applies_future_replacement_deadline() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        graph.ask.deadline = datetime(2020, 1, 1, tzinfo=UTC)
        session.commit()

        with pytest.raises(HTTPException, match="future replacement_deadline"):
            add_recipient(
                graph.ask.id,
                RecipientWrite(display_name="Too late", question_ids=[graph.question.id]),
                graph.owner,
                session,
                TOKENS,
                SETTINGS,
            )
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        graph.ask.deadline = datetime(2020, 1, 1, tzinfo=UTC)
        session.commit()
        future = date.today() + timedelta(days=10)
        result = add_recipient(
            graph.ask.id,
            RecipientWrite(
                display_name="With replacement",
                question_ids=[graph.question.id],
                replacement_deadline=future,
                timezone="UTC",
            ),
            graph.owner,
            session,
            TOKENS,
            SETTINGS,
        )
        assert isinstance(result, RecipientAddResult)
        session.refresh(graph.ask)
        assert graph.ask.deadline is not None and graph.ask.deadline.date() == future
        event = session.scalar(
            select(Event).where(Event.ask_id == graph.ask.id, Event.type == "ask.deadline_replaced")
        )
        assert event is not None and str(event.data["old"]).startswith("2020-01-01")


@pytest.mark.parametrize("satisfied", [True, False])
def test_new_recipient_dependency_state_uses_existing_prerequisite_response(
    satisfied: bool,
) -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        graph.question.open_to = QuestionOpenTo.PROJECT_MEMBERS
        advisory = submit_unsolicited_response(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=graph.ask.id,
            question_id=graph.question.id,
            submission=ResponseSubmission(
                ResponseDisposition.ANSWERED,
                "approve" if satisfied else "reject",
                None,
                uuid4(),
                None,
                "phase43",
            ),
        )
        aggregate = add_question(
            graph.ask.id,
            approval_question(
                "Why should we proceed?",
                depends_on={
                    "question_id": str(graph.question.id),
                    "op": "eq",
                    "value": "approve",
                },
            ),
            graph.owner,
            session,
        )
        dependent_id = next(item.id for item in aggregate.questions if item.id != graph.question.id)

        result = add_recipient(
            graph.ask.id,
            RecipientWrite(
                actor_id=graph.owner.id,
                question_ids=[graph.question.id, dependent_id],
            ),
            graph.owner,
            session,
            TOKENS,
            SETTINGS,
        )

        assert isinstance(result, RecipientAddResult)
        prerequisite = session.get_one(Assignment, advisory.assignment_id)
        dependent = session.scalar(
            select(Assignment).where(
                Assignment.ask_recipient_id == result.recipient.id,
                Assignment.question_id == dependent_id,
            )
        )
        assert prerequisite.origin == AssignmentOrigin.ASSIGNED
        assert dependent is not None
        assert dependent.state == (
            AssignmentState.PENDING if satisfied else AssignmentState.WITHDRAWN
        )


def test_sent_dependency_update_add_change_and_remove_recomputes_assignments() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        aggregate = add_question(
            graph.ask.id, approval_question("Dependent?"), graph.owner, session
        )
        dependent_id = next(item.id for item in aggregate.questions if item.id != graph.question.id)
        dependent = session.scalar(select(Assignment).where(Assignment.question_id == dependent_id))
        assert dependent is not None and dependent.state == AssignmentState.PENDING

        update_question(
            graph.ask.id,
            dependent_id,
            approval_question(
                "Dependent?",
                depends_on={"question_id": str(graph.question.id), "op": "eq", "value": "approve"},
            ),
            graph.owner,
            session,
        )
        session.refresh(dependent)
        assert cast(AssignmentState, dependent.state) == AssignmentState.BLOCKED

        _answer(session, graph, 0, "reject")
        update_question(
            graph.ask.id,
            dependent_id,
            approval_question(
                "Dependent?",
                depends_on={"question_id": str(graph.question.id), "op": "eq", "value": "approve"},
            ),
            graph.owner,
            session,
        )
        session.refresh(dependent)
        assert cast(AssignmentState, dependent.state) == AssignmentState.WITHDRAWN

        update_question(
            graph.ask.id, dependent_id, approval_question("Independent"), graph.owner, session
        )
        session.refresh(dependent)
        assert dependent.state == AssignmentState.PENDING


@pytest.mark.parametrize("invalid", ["missing", "cycle"])
def test_sent_dependency_update_rejects_invalid_final_graph(invalid: str) -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        aggregate = add_question(graph.ask.id, approval_question("Second"), graph.owner, session)
        second_id = next(item.id for item in aggregate.questions if item.id != graph.question.id)
        if invalid == "cycle":
            update_question(
                graph.ask.id,
                second_id,
                approval_question(
                    "Second", depends_on={"question_id": str(graph.question.id), "op": "answered"}
                ),
                graph.owner,
                session,
            )
            target_id = second_id
        else:
            target_id = uuid4()
        with pytest.raises(HTTPException) as raised:
            update_question(
                graph.ask.id,
                graph.question.id,
                approval_question(
                    "First", depends_on={"question_id": str(target_id), "op": "answered"}
                ),
                graph.owner,
                session,
            )
        assert raised.value.status_code == 409
        assert "depend" in str(raised.value.detail).lower()


def test_sent_question_update_persists_open_to() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        body = approval_question("Open correction")
        body.open_to = QuestionOpenTo.PROJECT_MEMBERS
        result = update_question(graph.ask.id, graph.question.id, body, graph.owner, session)
        assert result.questions[0].open_to == QuestionOpenTo.PROJECT_MEMBERS
        session.refresh(graph.question)
        assert graph.question.open_to == QuestionOpenTo.PROJECT_MEMBERS


def test_successor_commit_supersedes_decision_without_mutating_prior_lifecycle() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        response = _answer(session, graph, 0, "approve")
        prior = commit_decision(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=graph.ask.id,
            question_id=graph.question.id,
            commit=DecisionCommit(
                statement="Approved.",
                value="approve",
                evidence=(),
                outcome_effect=OutcomeEffect.UNCHANGED,
                outcome_effect_note=None,
                share_with_recipients=True,
            ),
        )
        prior_snapshot = (
            row_snapshot(graph.ask),
            row_snapshot(graph.question),
            row_snapshot(response),
        )
        decision_snapshot = row_snapshot(prior, exclude={"state"})
        successor_aggregate = create_successor_ask(
            graph.ask.id, graph.question.id, graph.owner, session
        )
        successor_ask = session.get_one(Ask, successor_aggregate.id)
        successor_question = session.scalar(
            select(Question).join(AskQuestion).where(AskQuestion.ask_id == successor_ask.id)
        )
        assert successor_question is not None
        assert successor_question.supersedes_question_id == graph.question.id
        assert successor_question.copied_from_question_id is None
        assert successor_question.depends_on is None
        assert successor_ask.parent_ask_id == graph.ask.id
        assert successor_ask.deadline is None

        recipient = AskRecipient(
            id=uuid4(),
            project_id=successor_ask.project_id,
            ask_id=successor_ask.id,
            actor_id=graph.assignments[0].actor_id,
            display_name="Successor recipient",
            token_hash=None,
            token_issued_at=None,
            session_version=1,
            revoked_at=None,
            access_expires_at=None,
            share_marked_sent_at=None,
            created_at=graph.clock.now(),
        )
        assignment = Assignment(
            id=uuid4(),
            project_id=successor_ask.project_id,
            ask_id=successor_ask.id,
            question_id=successor_question.id,
            actor_id=recipient.actor_id,
            ask_recipient_id=recipient.id,
            origin=AssignmentOrigin.ASSIGNED,
            state=AssignmentState.PENDING,
            delegated_to_actor_id=None,
            child_ask_id=None,
            created_at=graph.clock.now(),
        )
        successor_ask.status = AskStatus.SENT
        successor_ask.sent_at = graph.clock.now()
        session.add_all([recipient, assignment])
        session.flush()
        successor = commit_decision(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=successor_ask.id,
            question_id=successor_question.id,
            commit=DecisionCommit(
                statement="Rejected after review.",
                value="reject",
                evidence=(),
                outcome_effect=OutcomeEffect.CHANGED,
                outcome_effect_note="New information",
                share_with_recipients=False,
            ),
        )
        session.refresh(prior)
        session.refresh(graph.ask)
        session.refresh(graph.question)
        assert successor.supersedes_decision_id == prior.id
        assert prior.state == DecisionState.SUPERSEDED
        assert (row_snapshot(graph.ask), row_snapshot(graph.question), row_snapshot(response)) == (
            prior_snapshot
        )
        assert row_snapshot(prior, exclude={"state"}) == decision_snapshot
        assert (
            session.scalar(
                select(func.count())
                .select_from(Decision)
                .where(Decision.supersedes_decision_id == prior.id)
            )
            == 1
        )
        superseded = session.scalar(
            select(Event).where(
                Event.type == "decision.superseded", Event.question_id == successor_question.id
            )
        )
        assert superseded is not None
        assert superseded.data == {
            "prior_decision_id": str(prior.id),
            "successor_decision_id": str(successor.id),
            "prior_ask_id": str(graph.ask.id),
        }


def test_automatic_successor_commit_supersedes_predecessor() -> None:
    with _test_session() as (session, _):
        graph, prior = committed_graph(session)
        successor = create_successor_ask(graph.ask.id, graph.question.id, graph.owner, session)
        successor_ask = session.get_one(Ask, successor.id)
        successor_question = session.scalar(
            select(Question).join(AskQuestion).where(AskQuestion.ask_id == successor.id)
        )
        assert successor_question is not None
        successor_question.auto_commit = True
        recipient = session.get_one(AskRecipient, graph.assignments[0].ask_recipient_id)
        successor_recipient = AskRecipient(
            id=uuid4(),
            project_id=successor_ask.project_id,
            ask_id=successor_ask.id,
            actor_id=recipient.actor_id,
            display_name=recipient.display_name,
            token_hash="successor-hash",
            token_issued_at=graph.clock.now(),
            session_version=1,
            revoked_at=None,
            access_expires_at=graph.clock.now() + timedelta(days=7),
            share_marked_sent_at=None,
            created_at=graph.clock.now(),
        )
        assignment = Assignment(
            id=uuid4(),
            project_id=successor_ask.project_id,
            ask_id=successor_ask.id,
            question_id=successor_question.id,
            actor_id=recipient.actor_id,
            ask_recipient_id=successor_recipient.id,
            origin=AssignmentOrigin.ASSIGNED,
            state=AssignmentState.PENDING,
            delegated_to_actor_id=None,
            child_ask_id=None,
            created_at=graph.clock.now(),
        )
        successor_ask.status = AskStatus.SENT
        successor_ask.sent_at = graph.clock.now()
        session.add_all([successor_recipient, assignment])
        session.flush()
        graph.ask = successor_ask
        graph.question = successor_question
        graph.assignments = [assignment]
        _answer(session, graph, 0, "reject")
        successor_question.close_eligible_at = graph.clock.now()

        decision = settle_question(session, graph.clock, successor_question.id)
        session.flush()

        session.refresh(prior)
        assert decision is not None and decision.state == DecisionState.COMMITTED
        assert decision.supersedes_decision_id == prior.id
        assert prior.state == DecisionState.SUPERSEDED
        event_types = set(session.scalars(select(Event.type).where(Event.ask_id == successor.id)))
        assert {"decision.proposed", "decision.superseded", "decision.committed"} <= event_types


def test_in_place_correction_commits_without_predecessor_decision() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        _answer(session, graph, 0, "approve")

        aggregate = update_question(
            graph.ask.id,
            graph.question.id,
            approval_question("Corrected approval?"),
            graph.owner,
            session,
        )
        successor_id = next(item.id for item in aggregate.questions)
        successor = session.get_one(Question, successor_id)
        replacement = session.scalar(
            select(Assignment).where(Assignment.question_id == successor.id)
        )
        assert replacement is not None
        graph.question = successor
        graph.assignments = [replacement]
        _answer(session, graph, 0, "approve")

        decision = commit_decision(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=graph.ask.id,
            question_id=successor.id,
            commit=DecisionCommit(
                "Corrected approval accepted.",
                "approve",
                (),
                OutcomeEffect.UNCHANGED,
                None,
                False,
            ),
        )

        assert decision.supersedes_decision_id is None
        assert graph.ask.status == AskStatus.CLOSED


def test_competing_successor_rolls_back_predecessor_state() -> None:
    with _test_session() as (session, _):
        graph, prior = committed_graph(session)
        first = create_successor_ask(graph.ask.id, graph.question.id, graph.owner, session)
        aggregate = add_question(
            first.id, approval_question("Competing successor?"), graph.owner, session
        )
        competing_question = next(
            item for item in aggregate.questions if item.supersedes_question_id is None
        )
        competing_row = session.get_one(Question, competing_question.id)
        competing_row.supersedes_question_id = graph.question.id
        session.commit()
        first_ask, first_question = prepare_successor(session, graph, first.id)
        commit_decision(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=first_ask.id,
            question_id=first_question.id,
            commit=DecisionCommit(
                "First successor.", "approve", (), OutcomeEffect.UNCHANGED, None, False
            ),
        )

        prior_id = prior.id
        nested = session.begin_nested()
        session.add(
            Decision(
                id=uuid4(),
                project_id=first_ask.project_id,
                ask_id=first_ask.id,
                question_id=competing_row.id,
                state=DecisionState.COMMITTED,
                basis=DecisionBasis.ASKER_JUDGMENT,
                value="reject",
                statement="Competing successor.",
                statement_source=DecisionStatementSource.OWNER,
                decided_by=graph.owner.id,
                supersedes_decision_id=prior_id,
                provenance={"path": "test"},
                shared_with_recipients_at=None,
                committed_at=graph.clock.now(),
                created_at=graph.clock.now(),
            )
        )
        with pytest.raises(IntegrityError, match="decision_one_successor"):
            session.flush()
        nested.rollback()

        persisted_prior = session.get_one(Decision, prior_id)
        assert persisted_prior.state == DecisionState.SUPERSEDED
        assert (
            session.scalar(
                select(func.count())
                .select_from(Decision)
                .where(Decision.supersedes_decision_id == prior_id)
            )
            == 1
        )


@pytest.mark.parametrize("denial", ["non_owner", "cross_project", "archived", "closed"])
def test_sent_recipient_addition_denials(denial: str) -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        actor = graph.owner
        actor_id: UUID | None = None
        if denial == "non_owner":
            actor = session.get_one(Actor, graph.assignments[0].actor_id)
            grant_membership(
                session,
                graph.clock,
                acting_actor_id=graph.owner.id,
                project_id=graph.project.id,
                actor_id=actor.id,
            )
        elif denial == "cross_project":
            other = _graph(session, assignee_count=1, auto_commit=False)
            actor_id = other.assignments[0].actor_id
        elif denial == "archived":
            graph.project.archived_at = graph.clock.now()
        else:
            graph.ask.status = AskStatus.CLOSED
            graph.ask.closed_at = graph.clock.now()
        session.commit()

        with pytest.raises(HTTPException):
            add_recipient(
                graph.ask.id,
                RecipientWrite(
                    display_name=None if actor_id else "Denied",
                    actor_id=actor_id,
                    question_ids=[graph.question.id],
                ),
                actor,
                session,
                TOKENS,
                SETTINGS,
            )


def select_assignment_ids(session: Session, recipient_id: UUID) -> list[UUID]:
    return list(
        session.scalars(
            select(Assignment.question_id)
            .where(Assignment.ask_recipient_id == recipient_id)
            .order_by(Assignment.question_id)
        )
    )


def row_snapshot(row: Any, *, exclude: set[str] | None = None) -> dict[str, object]:
    excluded = exclude or set()
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in excluded and column.name != "search_tsv"
    }


def committed_graph(session: Session) -> tuple[SettlementGraph, Decision]:
    graph = _graph(session, assignee_count=1, auto_commit=False)
    _answer(session, graph, 0, "approve")
    prior = commit_decision(
        session,
        graph.clock,
        actor_id=graph.owner.id,
        ask_id=graph.ask.id,
        question_id=graph.question.id,
        commit=DecisionCommit("Approved.", "approve", (), OutcomeEffect.UNCHANGED, None, False),
    )
    return graph, prior


def prepare_successor(
    session: Session, graph: SettlementGraph, ask_id: UUID
) -> tuple[Ask, Question]:
    ask = session.get_one(Ask, ask_id)
    question = session.scalar(
        select(Question)
        .join(AskQuestion)
        .where(
            AskQuestion.ask_id == ask_id,
            Question.supersedes_question_id == graph.question.id,
        )
    )
    assert question is not None
    prior_recipient = session.get_one(AskRecipient, graph.assignments[0].ask_recipient_id)
    recipient = AskRecipient(
        id=uuid4(),
        project_id=ask.project_id,
        ask_id=ask.id,
        actor_id=prior_recipient.actor_id,
        display_name=prior_recipient.display_name,
        token_hash=None,
        token_issued_at=None,
        session_version=1,
        revoked_at=None,
        access_expires_at=None,
        share_marked_sent_at=None,
        created_at=graph.clock.now(),
    )
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
        created_at=graph.clock.now(),
    )
    ask.status = AskStatus.SENT
    ask.sent_at = graph.clock.now()
    session.add_all([recipient, assignment])
    session.flush()
    return ask, question


def approval_question(prompt: str, *, depends_on: dict[str, object] | None = None) -> QuestionWrite:
    return QuestionWrite(
        template_id="approval",
        prompt=prompt,
        depends_on=depends_on,
        options=[
            OptionWrite(value="approve", label="Approve"),
            OptionWrite(value="reject", label="Reject"),
        ],
    )
