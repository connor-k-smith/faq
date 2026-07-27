from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_actor
from app.config import get_settings
from app.domain.enums import (
    AssignmentState,
    DecisionBasis,
    QuestionClosePolicy,
    QuestionState,
)
from app.google_identity import get_google_identity_verifier
from app.jobs.metrics import get_metrics_sink
from app.jobs.scheduler import run_tick
from app.jobs_main import create_app as create_jobs_app
from app.main import create_app as create_public_app
from app.models.identity import Actor, LoginInvitation, Project
from app.models.outcomes import Decision, DecisionResponse
from app.models.session import get_engine, get_session_factory
from app.models.work import Ask, AskQuestion, Assignment, Question
from tests.fakes import FakeGoogleIdentityVerifier, FakeMetricsSink, FixedClock
from tests.integration.test_phase3_settlement import SettlementGraph, _answer, _graph

pytestmark = pytest.mark.integration

PAST = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
def graphs() -> Iterator[Callable[..., SettlementGraph]]:
    project_ids: list[UUID] = []
    actor_ids: list[UUID] = []

    def create(*, deadline: bool = True, assignee_count: int = 1) -> SettlementGraph:
        with get_session_factory()() as session:
            existing_actor_ids = set(session.scalars(select(Actor.id)))
            graph = _graph(
                session,
                assignee_count=assignee_count,
                auto_commit=False,
                deadline=deadline,
            )
            project_ids.append(graph.project.id)
            actor_ids.extend(
                actor_id
                for actor_id in [
                    graph.owner.id,
                    *(assignment.actor_id for assignment in graph.assignments),
                ]
                if actor_id not in existing_actor_ids
            )
            if deadline:
                graph.ask.deadline = PAST
            session.commit()
            return graph

    yield create

    with Session(get_engine()) as session, session.begin():
        session.execute(
            delete(DecisionResponse).where(DecisionResponse.project_id.in_(project_ids))
        )
        session.execute(delete(Project).where(Project.id.in_(project_ids)))
        session.execute(
            delete(LoginInvitation).where(
                or_(
                    LoginInvitation.invited_by.in_(actor_ids),
                    LoginInvitation.accepted_by.in_(actor_ids),
                )
            )
        )
        session.execute(delete(Actor).where(Actor.id.in_(actor_ids)))


def test_authenticated_tick_is_bounded_reports_more_then_drains_and_is_idempotent(
    graphs: Callable[..., SettlementGraph],
    monkeypatch: MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    created = [graphs() for _ in range(3)]
    metrics = FakeMetricsSink()
    verifier = FakeGoogleIdentityVerifier(
        email="scheduler@example.com", valid_token="phase-34-secret-token"
    )
    monkeypatch.setenv("FAQ_JOBS_AUDIENCE", "phase-34-scheduler")
    monkeypatch.setenv("FAQ_JOBS_CALLER_EMAIL", "scheduler@example.com")
    monkeypatch.setenv("FAQ_JOBS_BATCH_SIZE", "2")
    monkeypatch.setenv("FAQ_JOBS_MAX_BATCHES", "1")
    get_settings.cache_clear()
    app = create_jobs_app()
    app.dependency_overrides[get_google_identity_verifier] = lambda: verifier
    app.dependency_overrides[get_metrics_sink] = lambda: metrics

    with TestClient(app) as client:
        first = client.post(
            "/jobs/tick", headers={"Authorization": "Bearer phase-34-secret-token"}
        )
        second = client.post(
            "/jobs/tick", headers={"Authorization": "Bearer phase-34-secret-token"}
        )
        repeated = client.post(
            "/jobs/tick", headers={"Authorization": "Bearer phase-34-secret-token"}
        )

    assert first.status_code == 200
    assert first.json() | {"run_id": None} == {
        "run_id": None,
        "batches": 1,
        "examined": 2,
        "settled": 2,
        "has_more": True,
    }
    assert second.json()["examined"] == second.json()["settled"] == 1
    assert second.json()["has_more"] is False
    assert repeated.json() | {"run_id": None} == {
        "run_id": None,
        "batches": 0,
        "examined": 0,
        "settled": 0,
        "has_more": False,
    }
    assert metrics.values == {
        "jobs.questions_examined": 3,
        "jobs.questions_settled": 3,
        "jobs.ticks": 3,
    }
    assert verifier.calls == [
        ("phase-34-secret-token", "phase-34-scheduler"),
    ] * 3
    assert "phase-34-secret-token" not in capsys.readouterr().out
    with Session(get_engine()) as session:
        assert session.scalar(
            select(func.count()).select_from(Decision).where(
                Decision.question_id.in_([item.question.id for item in created])
            )
        ) == 3


def test_tick_applies_all_responded_and_deadline_policies(
    graphs: Callable[..., SettlementGraph],
) -> None:
    all_responded = graphs(deadline=False, assignee_count=1)
    deadline = graphs(deadline=True, assignee_count=1)
    with Session(get_engine()) as session:
        answered = session.get_one(Question, all_responded.question.id)
        answered.close_policy = QuestionClosePolicy.ALL_RESPONDED
        answered.close_eligible_at = PAST
        hydrated = SettlementGraph(
            all_responded.clock,
            session.get_one(Actor, all_responded.owner.id),
            session.get_one(Project, all_responded.project.id),
            session.get_one(Ask, all_responded.ask.id),
            answered,
            [session.get_one(Assignment, all_responded.assignments[0].id)],
        )
        _answer(session, hydrated, 0, "approve")
        session.commit()

    summary = run_tick(
        get_session_factory(),
        FixedClock(datetime(2026, 7, 25, 18, 0, tzinfo=UTC)),
        FakeMetricsSink(),
        run_id=uuid4(),
        batch_size=10,
        max_batches=1,
    )

    assert summary.examined == summary.settled == 2
    with Session(get_engine()) as session:
        decisions = {
            item.question_id: item
            for item in session.scalars(
                select(Decision).where(
                    Decision.question_id.in_([all_responded.question.id, deadline.question.id])
                )
            )
        }
        assert decisions[all_responded.question.id].basis == DecisionBasis.SINGLE_RESPONDENT
        assert decisions[deadline.question.id].basis == DecisionBasis.EXPIRED_NO_RESPONSE


def test_expired_prerequisite_withdraws_and_closes_unasked_dependent(
    graphs: Callable[..., SettlementGraph],
) -> None:
    graph = graphs(deadline=True, assignee_count=2)
    with Session(get_engine()) as session:
        prerequisite = session.get_one(Question, graph.question.id)
        dependent = Question(
            id=uuid4(),
            project_id=prerequisite.project_id,
            template_id=prerequisite.template_id,
            primitive=prerequisite.primitive,
            version=1,
            supersedes_question_id=None,
            copied_from_question_id=None,
            state=QuestionState.OPEN,
            origin=prerequisite.origin,
            prompt="Blocked follow-up",
            help_text=None,
            context_refs=[],
            open_to=prerequisite.open_to,
            allow_comment=True,
            validation={},
            require_comment_if=None,
            depends_on={"question_id": str(prerequisite.id), "op": "answered"},
            response_visibility=prerequisite.response_visibility,
            anonymous=False,
            proposed_value=None,
            proposed_rationale=None,
            close_policy=QuestionClosePolicy.ALL_RESPONDED,
            auto_commit=False,
            auto_commit_if=None,
            created_by=prerequisite.created_by,
            critiques_overridden=[],
            close_eligible_at=None,
            closed_at=None,
            outcome_effect=None,
            outcome_effect_note=None,
            created_at=PAST,
        )
        session.add(dependent)
        session.flush()
        session.add(
            AskQuestion(
                project_id=graph.project.id,
                ask_id=graph.ask.id,
                question_id=dependent.id,
                ordinal=1,
                superseded_at=None,
            )
        )
        for source in session.scalars(
            select(Assignment).where(Assignment.question_id == prerequisite.id)
        ):
            session.add(
                Assignment(
                    id=uuid4(),
                    project_id=source.project_id,
                    ask_id=source.ask_id,
                    question_id=dependent.id,
                    actor_id=source.actor_id,
                    ask_recipient_id=source.ask_recipient_id,
                    origin=source.origin,
                    state=AssignmentState.BLOCKED,
                    delegated_to_actor_id=None,
                    child_ask_id=None,
                    created_at=PAST,
                )
            )
        dependent_id = dependent.id
        session.commit()

    run_tick(
        get_session_factory(), FixedClock(PAST), FakeMetricsSink(),
        run_id=uuid4(), batch_size=10, max_batches=1,
    )
    with Session(get_engine()) as session:
        dependent = session.get_one(Question, dependent_id)
        states = set(
            session.scalars(
                select(Assignment.state).where(Assignment.question_id == dependent_id)
            )
        )
        assert dependent.state == QuestionState.CLOSED
        assert states == {AssignmentState.WITHDRAWN}
        assert session.scalar(
            select(func.count()).select_from(Decision).where(Decision.question_id == dependent_id)
        ) == 0


def test_unauthorized_lazy_ask_read_does_not_settle_due_question(
    graphs: Callable[..., SettlementGraph],
) -> None:
    graph = graphs(deadline=True, assignee_count=1)
    with Session(get_engine()) as session:
        outsider = session.get_one(Actor, graph.assignments[0].actor_id)
        app = create_public_app()
        app.dependency_overrides[get_current_actor] = lambda: outsider
        response = TestClient(app).get(f"/api/asks/{graph.ask.id}")

    assert response.status_code == 404
    with Session(get_engine()) as session:
        assert session.get_one(Question, graph.question.id).state == QuestionState.OPEN
        assert session.scalar(
            select(func.count()).select_from(Decision).where(
                Decision.question_id == graph.question.id
            )
        ) == 0


def test_tick_skips_question_locked_by_another_connection(
    graphs: Callable[..., SettlementGraph],
) -> None:
    first, second = graphs(), graphs()
    engine = get_engine()
    lock_connection = engine.connect()
    lock_transaction = lock_connection.begin()
    locker = Session(lock_connection)
    try:
        locker.scalar(
            select(Question).where(Question.id == first.question.id).with_for_update()
        )
        summary = run_tick(
            get_session_factory(), FixedClock(PAST), FakeMetricsSink(),
            run_id=uuid4(), batch_size=10, max_batches=1,
        )
        assert summary.examined == summary.settled == 1
        with Session(engine) as session:
            assert session.get_one(Question, first.question.id).state == QuestionState.OPEN
            assert session.get_one(Question, second.question.id).state == QuestionState.CLOSED
    finally:
        locker.close()
        lock_transaction.rollback()
        lock_connection.close()

    summary = run_tick(
        get_session_factory(), FixedClock(PAST), FakeMetricsSink(),
        run_id=uuid4(), batch_size=10, max_batches=1,
    )
    assert summary.examined == summary.settled == 1
    with Session(engine) as session:
        assert session.get_one(Question, first.question.id).state == QuestionState.CLOSED
