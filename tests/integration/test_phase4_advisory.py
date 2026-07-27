from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.domain.decisions import (
    DecisionCommit,
    DecisionCommitError,
    DecisionEvidence,
    commit_decision,
)
from app.domain.enums import (
    AssignmentOrigin,
    DecisionResponseRole,
    DecisionState,
    OutcomeEffect,
    QuestionOpenTo,
    ResponseDisposition,
)
from app.domain.responding import ResponseSubmission, submit_unsolicited_response
from app.domain.settlement import settle_question
from app.models.outcomes import Decision, Event, Response
from app.models.work import Assignment
from tests.integration.test_phase3_settlement import _answer, _graph, _test_session

pytestmark = pytest.mark.integration


def test_late_advisory_is_idempotent_audited_and_does_not_mutate_settlement() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=True)
        graph.question.open_to = QuestionOpenTo.PROJECT_MEMBERS
        assigned = _answer(session, graph, 0, "approve")
        graph.question.close_eligible_at = graph.clock.now()
        decision = settle_question(session, graph.clock, graph.question.id)
        assert decision is not None and decision.state == DecisionState.COMMITTED
        decision_snapshot = (decision.id, decision.value, decision.provenance.copy())
        submission_id = uuid4()

        advisory = submit_unsolicited_response(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=graph.ask.id,
            question_id=graph.question.id,
            submission=ResponseSubmission(
                disposition=ResponseDisposition.ANSWERED,
                value="reject",
                comment="Owner advisory context",
                submission_id=submission_id,
                source_ip="127.0.0.1",
                user_agent="phase4-test",
            ),
        )
        repeated = submit_unsolicited_response(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=graph.ask.id,
            question_id=graph.question.id,
            submission=ResponseSubmission(
                disposition=ResponseDisposition.ANSWERED,
                value="reject",
                comment="Owner advisory context",
                submission_id=submission_id,
                source_ip="127.0.0.1",
                user_agent="phase4-test",
            ),
        )

        assignment = session.get_one(Assignment, advisory.assignment_id)
        session.refresh(decision)
        assert repeated.id == advisory.id
        assert assignment.origin == AssignmentOrigin.UNSOLICITED
        assert assignment.ask_recipient_id is None
        assert advisory.provenance["auth"] == "session"
        assert advisory.provenance["late"] is True
        assert (decision.id, decision.value, decision.provenance) == decision_snapshot
        assert session.scalar(select(func.count()).select_from(Decision)) == 1
        assert session.scalar(select(func.count()).select_from(Response)) == 2
        assert session.scalar(
            select(func.count()).select_from(Event).where(Event.assignment_id == assignment.id)
        ) == 1
        assert assigned.id != advisory.id


def test_unsolicited_response_may_be_context_but_never_determining_evidence() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        graph.question.open_to = QuestionOpenTo.PROJECT_MEMBERS
        _answer(session, graph, 0, "approve")
        graph.question.close_eligible_at = graph.clock.now()
        proposal = settle_question(session, graph.clock, graph.question.id)
        assert proposal is not None
        advisory = submit_unsolicited_response(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=graph.ask.id,
            question_id=graph.question.id,
            submission=ResponseSubmission(
                ResponseDisposition.ANSWERED, "reject", None, uuid4(), None, "phase4-test"
            ),
        )

        with pytest.raises(DecisionCommitError, match="substantive assigned"):
            commit_decision(
                session,
                graph.clock,
                actor_id=graph.owner.id,
                ask_id=graph.ask.id,
                question_id=graph.question.id,
                commit=DecisionCommit(
                    statement="Should we ship?: Approve.",
                    value="approve",
                    evidence=(
                        DecisionEvidence(advisory.id, DecisionResponseRole.DETERMINING),
                    ),
                    outcome_effect=OutcomeEffect.UNCHANGED,
                    outcome_effect_note=None,
                    share_with_recipients=False,
                    proposal_id=proposal.id,
                ),
            )

        decision = commit_decision(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=graph.ask.id,
            question_id=graph.question.id,
            commit=DecisionCommit(
                statement="Should we ship?: Approve.",
                value="approve",
                evidence=(DecisionEvidence(advisory.id, DecisionResponseRole.CONTEXT),),
                outcome_effect=OutcomeEffect.UNCHANGED,
                outcome_effect_note=None,
                share_with_recipients=False,
                proposal_id=proposal.id,
            ),
        )
        assert decision.state == DecisionState.COMMITTED
