from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_actor, get_db_session
from app.auth.provisioning import create_login_invitation, provision_identity
from app.domain.access import create_project, grant_membership
from app.domain.decisions import DecisionCommit, DecisionEvidence, commit_decision
from app.domain.enums import (
    ActorKind,
    AskStatus,
    AssignmentOrigin,
    AssignmentState,
    DecisionBasis,
    DecisionResponseRole,
    DecisionState,
    InitiativeKind,
    OrganizationRole,
    OutcomeEffect,
    QuestionClosePolicy,
    QuestionOpenTo,
    QuestionOrigin,
    QuestionPrimitive,
    QuestionState,
    ResponseChannel,
    ResponseDisposition,
    ResponseVisibility,
)
from app.domain.initiatives import create_initiative
from app.domain.ports import IdentityClaims
from app.domain.resolution import RENDERER_VERSION
from app.domain.settlement import settle_question
from app.main import create_app
from app.models.identity import Actor, Project
from app.models.outcomes import Decision, DecisionResponse, Event, Response
from app.models.session import get_engine
from app.models.work import Ask, AskQuestion, AskRecipient, Assignment, Question, QuestionOption
from tests.fakes import FixedClock

pytestmark = pytest.mark.integration


@dataclass
class SettlementGraph:
    clock: FixedClock
    owner: Actor
    project: Project
    ask: Ask
    question: Question
    assignments: list[Assignment]


def test_unanimous_auto_commit_requires_every_eligible_assignee_and_keeps_ask_sent() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=2, auto_commit=True)
        first = _answer(session, graph, 0, "approve")
        graph.question.close_eligible_at = graph.clock.now()

        proposal = settle_question(session, graph.clock, graph.question.id)

        assert proposal is not None
        assert proposal.state == DecisionState.PROPOSED
        assert proposal.basis == DecisionBasis.ASKER_JUDGMENT
        assert proposal.value is None
        assert _computed(proposal) == {
            "basis": "asker_judgment",
            "value": None,
            "has_winner": False,
            "conflict": False,
            "eligible_count": 2,
            "substantive_count": 1,
            "quorum_met": False,
            "vote_counts": {"approve": 1},
        }
        assert _evidence_ids(session, proposal.id) == {first.id}
        assert graph.ask.status == AskStatus.SENT

    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=2, auto_commit=True)
        responses = [_answer(session, graph, index, "approve") for index in range(2)]
        graph.question.close_eligible_at = graph.clock.now()

        decision = settle_question(session, graph.clock, graph.question.id)
        session.flush()

        assert decision is not None
        assert decision.state == DecisionState.COMMITTED
        assert decision.basis == DecisionBasis.UNANIMOUS
        assert decision.value == "approve"
        assert decision.statement == "Should we ship?: Approve."
        assert decision.provenance["path"] == "automatic"
        assert decision.provenance["renderer"] == RENDERER_VERSION
        assert _computed(decision)["quorum_met"] is True
        assert _evidence_ids(session, decision.id) == {item.id for item in responses}
        assert graph.ask.status == AskStatus.SENT
        assert graph.question.outcome_effect is None


def test_option_triggers_are_inert_transactional_and_idempotent_on_auto_commit() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=True)
        options = list(
            session.scalars(
                select(QuestionOption)
                .where(QuestionOption.question_id == graph.question.id)
                .order_by(QuestionOption.ordinal)
            )
        )
        options[0].triggers = [
            {
                "kind": "linear.issue",
                "team": "ATLAS",
                "title": "Ship",
                "body_template": "Decision committed",
            },
            {"kind": "linear.issue", "team": "ATLAS"},
        ]
        options[1].triggers = [
            {
                "kind": "linear.issue",
                "team": "ATLAS",
                "title": "Unselected",
                "body_template": "Never attempted",
            }
        ]
        _answer(session, graph, 0, "approve")
        graph.question.close_eligible_at = graph.clock.now()

        decision = settle_question(session, graph.clock, graph.question.id)
        assert decision is not None
        assert settle_question(session, graph.clock, graph.question.id) is None
        attempts = list(
            session.scalars(
                select(Event)
                .where(
                    Event.question_id == graph.question.id,
                    Event.type == "integration.trigger_attempted",
                )
                .order_by(Event.id)
            )
        )

        assert [event.actor_id for event in attempts] == [None, None]
        assert [event.data for event in attempts] == [
            {
                "schema_version": 1,
                "decision_id": str(decision.id),
                "option_value": "approve",
                "trigger_index": 0,
                "kind": "linear.issue",
                "outcome": "stubbed",
            },
            {
                "schema_version": 1,
                "decision_id": str(decision.id),
                "option_value": "approve",
                "trigger_index": 1,
                "kind": "linear.issue",
                "outcome": "invalid",
            },
        ]


def test_manual_commit_attempts_only_the_selected_option_trigger_with_actor() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=1, auto_commit=False)
        approve = session.scalar(
            select(QuestionOption).where(
                QuestionOption.question_id == graph.question.id,
                QuestionOption.value == "approve",
            )
        )
        assert approve is not None
        approve.triggers = [
            {
                "kind": "linear.issue",
                "team": "ATLAS",
                "title": "Approved",
                "body_template": "Decision committed",
            }
        ]
        reject = session.scalar(
            select(QuestionOption).where(
                QuestionOption.question_id == graph.question.id,
                QuestionOption.value == "reject",
            )
        )
        assert reject is not None
        reject.triggers = [
            {
                "kind": "linear.issue",
                "team": "ATLAS",
                "title": "Rejected",
                "body_template": "Decision committed",
            }
        ]

        decision = commit_decision(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=graph.ask.id,
            question_id=graph.question.id,
            commit=DecisionCommit(
                statement="Rejected.",
                value="reject",
                evidence=(),
                outcome_effect=OutcomeEffect.UNCHANGED,
                outcome_effect_note=None,
                share_with_recipients=False,
            ),
        )

        assert decision.state == DecisionState.COMMITTED
        attempts = list(
            session.scalars(
                select(Event).where(
                    Event.type == "integration.trigger_attempted",
                    Event.question_id == graph.question.id,
                )
            )
        )
        assert len(attempts) == 1
        assert attempts[0].actor_id == graph.owner.id
        assert attempts[0].data["option_value"] == "reject"


def test_majority_uses_all_substantive_evidence_and_records_provenance() -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=4, auto_commit=False)
        responses = [
            _answer(session, graph, 0, "approve"),
            _answer(session, graph, 1, "approve"),
            _answer(session, graph, 2, "reject"),
        ]
        graph.question.close_eligible_at = graph.clock.now()

        decision = settle_question(session, graph.clock, graph.question.id)
        session.flush()

        assert decision is not None
        assert decision.state == DecisionState.PROPOSED
        assert decision.basis == DecisionBasis.MAJORITY
        assert decision.value == "approve"
        assert decision.provenance["computed"] == {
            "basis": "majority",
            "value": "approve",
            "has_winner": True,
            "conflict": False,
            "eligible_count": 4,
            "substantive_count": 3,
            "quorum_met": True,
            "vote_counts": {"approve": 2, "reject": 1},
        }
        links = list(
            session.scalars(
                select(DecisionResponse).where(DecisionResponse.decision_id == decision.id)
            )
        )
        assert {link.response_id for link in links} == {item.id for item in responses}
        assert {link.role for link in links} == {DecisionResponseRole.DETERMINING}


def test_tie_and_deadline_without_responses_create_one_proposal_idempotently() -> None:
    with _test_session() as (session, _):
        tied = _graph(session, assignee_count=2, auto_commit=True)
        _answer(session, tied, 0, "approve")
        _answer(session, tied, 1, "reject")
        tied.question.close_eligible_at = tied.clock.now()

        tie = settle_question(session, tied.clock, tied.question.id)
        again = settle_question(session, tied.clock, tied.question.id)
        session.flush()

        assert tie is not None
        assert tie.basis == DecisionBasis.ASKER_JUDGMENT
        assert tie.state == DecisionState.PROPOSED
        assert _computed(tie)["conflict"] is True
        assert _computed(tie)["vote_counts"] == {"approve": 1, "reject": 1}
        assert again is None
        assert session.scalar(
            select(func.count())
            .select_from(Decision)
            .where(Decision.question_id == tied.question.id)
        ) == 1
        assert tied.ask.status == AskStatus.SENT

    with _test_session() as (session, _):
        expired = _graph(session, assignee_count=2, auto_commit=True, deadline=True)

        decision = settle_question(session, expired.clock, expired.question.id)
        session.flush()

        assert decision is not None
        assert decision.basis == DecisionBasis.EXPIRED_NO_RESPONSE
        assert decision.state == DecisionState.PROPOSED
        assert decision.value is None
        assert decision.statement is None
        assert _computed(decision)["substantive_count"] == 0
        assert {item.state for item in expired.assignments} == {AssignmentState.EXPIRED}
        assert expired.ask.status == AskStatus.SENT


@pytest.mark.parametrize(
    ("confirmed_value", "expected_basis", "changed"),
    [
        ("approve", DecisionBasis.MAJORITY, False),
        ("reject", DecisionBasis.ASKER_OVERRIDE, True),
    ],
)
def test_owner_confirmation_updates_proposal_in_place_and_preserves_computed_basis(
    confirmed_value: str, expected_basis: DecisionBasis, changed: bool
) -> None:
    with _test_session() as (session, _):
        graph = _graph(session, assignee_count=4, auto_commit=False)
        responses = [
            _answer(session, graph, 0, "approve"),
            _answer(session, graph, 1, "approve"),
            _answer(session, graph, 2, "reject"),
        ]
        graph.question.close_eligible_at = graph.clock.now()
        proposal = settle_question(session, graph.clock, graph.question.id)
        assert proposal is not None
        computed = dict(_computed(proposal))

        committed = commit_decision(
            session,
            graph.clock,
            actor_id=graph.owner.id,
            ask_id=graph.ask.id,
            question_id=graph.question.id,
            commit=DecisionCommit(
                statement="Owner-confirmed outcome",
                value=confirmed_value,
                evidence=tuple(
                    DecisionEvidence(item.id, DecisionResponseRole.DETERMINING)
                    for item in responses
                ),
                outcome_effect=OutcomeEffect.UNCHANGED,
                outcome_effect_note=None,
                share_with_recipients=False,
                proposal_id=proposal.id,
            ),
        )

        assert committed.id == proposal.id
        assert committed.state == DecisionState.COMMITTED
        assert committed.basis == expected_basis
        assert committed.provenance["computed"] == computed
        assert committed.provenance["confirmation"] == {
            "path": "owner",
            "changed_computed_winner": changed,
        }
        assert graph.ask.status == AskStatus.CLOSED


def test_proposals_are_excluded_from_feed_search_and_markdown_export() -> None:
    with _test_session() as (session, override_session):
        graph = _graph(session, assignee_count=2, auto_commit=False)
        _answer(session, graph, 0, "approve")
        _answer(session, graph, 1, "approve")
        graph.question.close_eligible_at = graph.clock.now()
        proposal = settle_question(session, graph.clock, graph.question.id)
        session.flush()
        assert proposal is not None

        app = create_app()
        app.dependency_overrides[get_db_session] = override_session
        app.dependency_overrides[get_current_actor] = lambda: graph.owner
        with TestClient(app) as client:
            feed = client.get(f"/api/projects/{graph.project.id}/feed")
            searched = client.get(
                f"/api/projects/{graph.project.id}/feed", params={"q": "Approve"}
            )
            exported = client.get(f"/d/{proposal.id}.md")

        assert feed.status_code == 200
        assert all(item["source_id"] != str(proposal.id) for item in feed.json()["items"])
        assert searched.status_code == 200
        assert all(item["source_id"] != str(proposal.id) for item in searched.json()["items"])
        assert exported.status_code == 404


@contextmanager
def _test_session() -> Iterator[tuple[Session, Callable[[], Generator[Session]]]]:
    session = Session(get_engine())

    def override() -> Generator[Session]:
        yield session

    try:
        yield session, override
    finally:
        session.close()


def _graph(
    session: Session, *, assignee_count: int, auto_commit: bool, deadline: bool = False
) -> SettlementGraph:
    clock = FixedClock(datetime(2026, 7, 25, 18, 0, tzinfo=UTC))
    owner_email = f"settlement-owner-{uuid4()}@example.com"
    existing_admin = session.scalar(
        select(Actor)
        .where(
            Actor.kind == ActorKind.HUMAN,
            Actor.organization_role == OrganizationRole.ADMIN,
            Actor.firebase_uid.is_not(None),
            Actor.deleted_at.is_(None),
        )
        .limit(1)
    )
    owner = existing_admin or provision_identity(
        session,
        clock,
        IdentityClaims(
            uid=f"settlement-owner-{uuid4()}",
            email=owner_email,
            email_verified=True,
            display_name="Settlement owner",
        ),
        bootstrap_admin_email=owner_email,
    )
    project = create_project(
        session, clock, acting_actor_id=owner.id, name=f"Settlement {uuid4()}"
    )
    session.flush()
    grant_membership(
        session,
        clock,
        acting_actor_id=owner.id,
        project_id=project.id,
        actor_id=owner.id,
    )
    session.flush()
    initiative = create_initiative(
        session,
        clock,
        acting_actor_id=owner.id,
        project_id=project.id,
        name=f"Settlement initiative {uuid4()}",
        kind=InitiativeKind.FEATURE,
    )
    ask = Ask(
        id=uuid4(),
        project_id=project.id,
        initiative_id=initiative.id,
        parent_ask_id=None,
        title=f"Settlement Ask {uuid4()}",
        intro=None,
        created_by=owner.id,
        deadline=clock.now() if deadline else None,
        default_note=None,
        status=AskStatus.SENT,
        owner_id=owner.id,
        sent_at=clock.now(),
        closed_at=None,
        share_message=None,
        critiques_overridden=[],
        created_at=clock.now(),
    )
    question = Question(
        id=uuid4(),
        project_id=project.id,
        template_id="approval",
        primitive=QuestionPrimitive.SELECT_ONE,
        version=1,
        supersedes_question_id=None,
        copied_from_question_id=None,
        state=QuestionState.OPEN,
        origin=QuestionOrigin.AUTHOR,
        prompt="Should we ship?",
        help_text=None,
        context_refs=[],
        open_to=QuestionOpenTo.ASSIGNED_ONLY,
        allow_comment=True,
        validation={},
        require_comment_if=None,
        depends_on=None,
        response_visibility=ResponseVisibility.AFTER_CLOSE,
        anonymous=False,
        proposed_value=None,
        proposed_rationale=None,
        close_policy=QuestionClosePolicy.EITHER,
        auto_commit=auto_commit,
        auto_commit_if=None,
        created_by=owner.id,
        critiques_overridden=[],
        close_eligible_at=None,
        closed_at=None,
        outcome_effect=None,
        outcome_effect_note=None,
        created_at=clock.now(),
    )
    session.add_all([ask, question])
    session.flush()
    session.add(
        AskQuestion(
            project_id=project.id,
            ask_id=ask.id,
            question_id=question.id,
            ordinal=0,
            superseded_at=None,
        )
    )
    session.add_all(
        [
            QuestionOption(
                id=uuid4(),
                question_id=question.id,
                ordinal=index,
                value=value,
                label=label,
                consequence=None,
                triggers=[],
            )
            for index, (value, label) in enumerate(
                (("approve", "Approve"), ("reject", "Reject"))
            )
        ]
    )
    session.flush()
    assignments = [
        _assignee(session, clock, project.id, ask.id, question.id, index)
        for index in range(assignee_count)
    ]
    session.flush()
    return SettlementGraph(clock, owner, project, ask, question, assignments)


def _assignee(
    session: Session,
    clock: FixedClock,
    project_id: UUID,
    ask_id: UUID,
    question_id: UUID,
    index: int,
) -> Assignment:
    email = f"settlement-assignee-{uuid4()}@example.com"
    owner = session.get_one(Ask, ask_id).owner_id
    create_login_invitation(session, clock, acting_actor_id=owner, email=email)
    actor = provision_identity(
        session,
        clock,
        IdentityClaims(
            uid=f"settlement-assignee-{uuid4()}",
            email=email,
            email_verified=True,
            display_name=f"Assignee {index}",
        ),
        bootstrap_admin_email="not-the-bootstrap@example.com",
    )
    recipient = AskRecipient(
        id=uuid4(),
        project_id=project_id,
        ask_id=ask_id,
        actor_id=actor.id,
        display_name=actor.display_name,
        token_hash=f"hash-{uuid4()}",
        token_issued_at=clock.now(),
        session_version=1,
        revoked_at=None,
        access_expires_at=clock.now() + timedelta(days=7),
        share_marked_sent_at=clock.now(),
        created_at=clock.now(),
    )
    assignment = Assignment(
        id=uuid4(),
        project_id=project_id,
        ask_id=ask_id,
        question_id=question_id,
        actor_id=actor.id,
        ask_recipient_id=recipient.id,
        origin=AssignmentOrigin.ASSIGNED,
        state=AssignmentState.PENDING,
        delegated_to_actor_id=None,
        child_ask_id=None,
        created_at=clock.now(),
    )
    session.add_all([recipient, assignment])
    return assignment


def _answer(session: Session, graph: SettlementGraph, index: int, value: str) -> Response:
    assignment = graph.assignments[index]
    response = Response(
        id=uuid4(),
        assignment_id=assignment.id,
        submission_id=uuid4(),
        version=1,
        disposition=ResponseDisposition.ANSWERED,
        value=value,
        comment=f"Evidence for {value}",
        delegated_to_actor_id=None,
        answered_via=ResponseChannel.WEB,
        provenance={"auth": "token", "ip": None, "ua": "integration-test"},
        created_at=graph.clock.now(),
    )
    session.add(response)
    assignment.state = AssignmentState.RESPONDED
    session.flush()
    return response


def _evidence_ids(session: Session, decision_id: UUID) -> set[UUID]:
    return set(
        session.scalars(
            select(DecisionResponse.response_id).where(DecisionResponse.decision_id == decision_id)
        )
    )


def _computed(decision: Decision) -> dict[str, object]:
    return cast(dict[str, object], decision.provenance["computed"])
