from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_actor, get_db_session
from app.auth.provisioning import create_login_invitation, provision_identity
from app.domain.access import create_project, grant_membership
from app.domain.enums import (
    AskStatus,
    DecisionBasis,
    DecisionState,
    DecisionStatementSource,
    InitiativeKind,
    OutcomeEffect,
    QuestionClosePolicy,
    QuestionOpenTo,
    QuestionOrigin,
    QuestionPrimitive,
    QuestionState,
    ResponseVisibility,
)
from app.domain.initiatives import create_initiative
from app.domain.ports import IdentityClaims
from app.main import create_app
from app.models.identity import Actor, Initiative, Membership, Project
from app.models.outcomes import Decision
from app.models.session import get_engine
from app.models.work import Ask, AskQuestion, Question
from tests.fakes import FixedClock

pytestmark = pytest.mark.integration


def test_owner_inbox_categories_isolation_lifecycle_and_transfer() -> None:
    with _test_session() as (session, override_session):
        owner, member, project, initiative = _identity_graph(session)
        ask = _ask(session, owner, project, initiative, "Lifecycle")
        proposed = _question(session, ask, owner, "Review proposal", minutes=1)
        missing_effect = _question(session, ask, owner, "Record effect", minutes=2)
        _question(session, ask, owner, "Still collecting", minutes=3)
        completed = _question(session, ask, owner, "Already complete", minutes=4)
        session.flush()
        _decision(session, ask, proposed, owner, DecisionState.PROPOSED)
        _decision(session, ask, missing_effect, owner, DecisionState.COMMITTED)
        _decision(session, ask, completed, owner, DecisionState.COMMITTED)
        completed.outcome_effect = OutcomeEffect.CLARIFIED
        session.flush()

        current = {"actor": owner}
        client = _client(override_session, lambda: current["actor"])
        with client:
            page = client.get("/api/inbox").json()
            assert page["counts"] == {
                "total": 3,
                "proposed_decision": 1,
                "outcome_effect": 1,
                "collecting": 1,
            }
            assert [item["kind"] for item in page["items"]] == [
                "proposed_decision",
                "outcome_effect",
                "collecting",
            ]
            assert {item["question_prompt"] for item in page["items"]} == {
                "Review proposal",
                "Record effect",
                "Still collecting",
            }

            current["actor"] = member
            assert client.get("/api/inbox").json()["items"] == []

            ask.owner_id = member.id
            session.flush()
            assert len(client.get("/api/inbox").json()["items"]) == 3
            current["actor"] = owner
            assert client.get("/api/inbox").json()["items"] == []

            current["actor"] = member
            membership = session.get_one(Membership, (project.id, member.id))
            membership.revoked_at = datetime.now(UTC)
            session.flush()
            assert client.get("/api/inbox").json()["items"] == []

            membership.revoked_at = None
            ask.status = AskStatus.CLOSED
            ask.closed_at = datetime.now(UTC)
            session.flush()
            assert client.get("/api/inbox").json()["counts"]["total"] == 0


def test_owner_inbox_pagination_is_stable_complete_and_rejects_invalid_cursors() -> None:
    with _test_session() as (session, override_session):
        owner, _, project, initiative = _identity_graph(session)
        ask = _ask(session, owner, project, initiative, "Pagination")
        for index in range(8):
            _question(session, ask, owner, f"Question {index}", minutes=index)
        session.flush()

        with _client(override_session, lambda: owner) as client:
            expected = [
                item["question_id"] for item in client.get("/api/inbox?limit=100").json()["items"]
            ]
            actual: list[str] = []
            cursor: str | None = None
            while True:
                response = client.get(
                    "/api/inbox", params={"limit": 3, **({"cursor": cursor} if cursor else {})}
                )
                assert response.status_code == 200
                body = response.json()
                actual.extend(item["question_id"] for item in body["items"])
                cursor = body["next_cursor"]
                if cursor is None:
                    break

            assert actual == expected
            assert len(actual) == len(set(actual)) == 8
            invalid = client.get("/api/inbox", params={"cursor": "a"})
            assert invalid.status_code == 400
            assert invalid.json() == {"detail": "invalid inbox cursor"}


@contextmanager
def _test_session() -> Iterator[tuple[Session, Callable[[], Generator[Session]]]]:
    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(connection)

    def override() -> Generator[Session]:
        yield session

    try:
        yield session, override
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _identity_graph(session: Session) -> tuple[Actor, Actor, Project, Initiative]:
    clock = FixedClock(datetime(2026, 7, 25, 18, 0, tzinfo=UTC))
    owner_email = f"inbox-owner-{uuid4()}@example.com"
    owner = provision_identity(
        session,
        clock,
        IdentityClaims(f"inbox-owner-{uuid4()}", owner_email, True, "Inbox owner"),
        bootstrap_admin_email=owner_email,
    )
    invitation_email = f"inbox-member-{uuid4()}@example.com"
    create_login_invitation(session, clock, acting_actor_id=owner.id, email=invitation_email)
    member = provision_identity(
        session,
        clock,
        IdentityClaims(f"inbox-member-{uuid4()}", invitation_email, True, "Inbox member"),
        bootstrap_admin_email=owner_email,
    )
    project = create_project(session, clock, acting_actor_id=owner.id, name=f"Inbox {uuid4()}")
    session.flush()
    grant_membership(
        session, clock, acting_actor_id=owner.id, project_id=project.id, actor_id=owner.id
    )
    grant_membership(
        session, clock, acting_actor_id=owner.id, project_id=project.id, actor_id=member.id
    )
    session.flush()
    initiative = create_initiative(
        session,
        clock,
        acting_actor_id=owner.id,
        project_id=project.id,
        name=f"Inbox initiative {uuid4()}",
        kind=InitiativeKind.FEATURE,
    )
    return owner, member, project, initiative


def _ask(
    session: Session, owner: Actor, project: Project, initiative: Initiative, title: str
) -> Ask:
    at = datetime(2026, 7, 25, 18, 0, tzinfo=UTC)
    ask = Ask(
        id=uuid4(),
        project_id=project.id,
        initiative_id=initiative.id,
        parent_ask_id=None,
        title=title,
        intro=None,
        created_by=owner.id,
        deadline=None,
        default_note=None,
        status=AskStatus.SENT,
        owner_id=owner.id,
        sent_at=at,
        closed_at=None,
        share_message=None,
        critiques_overridden=[],
        created_at=at,
    )
    session.add(ask)
    session.flush()
    return ask


def _question(session: Session, ask: Ask, owner: Actor, prompt: str, *, minutes: int) -> Question:
    at = datetime(2026, 7, 25, 18, 0, tzinfo=UTC) + timedelta(minutes=minutes)
    question = Question(
        id=uuid4(),
        project_id=ask.project_id,
        template_id="open_question",
        primitive=QuestionPrimitive.TEXT,
        version=1,
        supersedes_question_id=None,
        copied_from_question_id=None,
        state=QuestionState.OPEN,
        origin=QuestionOrigin.AUTHOR,
        prompt=prompt,
        help_text=None,
        context_refs=[],
        open_to=QuestionOpenTo.ASSIGNED_ONLY,
        allow_comment=True,
        validation={},
        require_comment_if=None,
        depends_on=None,
        response_visibility=ResponseVisibility.AFTER_OWN_RESPONSE,
        anonymous=False,
        proposed_value=None,
        proposed_rationale=None,
        close_policy=QuestionClosePolicy.EITHER,
        auto_commit=False,
        auto_commit_if=None,
        created_by=owner.id,
        critiques_overridden=[],
        close_eligible_at=None,
        closed_at=None,
        outcome_effect=None,
        outcome_effect_note=None,
        created_at=at,
    )
    session.add(question)
    session.flush()
    session.add(
        AskQuestion(
            project_id=ask.project_id,
            ask_id=ask.id,
            question_id=question.id,
            ordinal=minutes,
            superseded_at=None,
        )
    )
    return question


def _decision(
    session: Session, ask: Ask, question: Question, owner: Actor, state: DecisionState
) -> None:
    at = question.created_at + timedelta(seconds=30)
    session.add(
        Decision(
            id=uuid4(),
            project_id=ask.project_id,
            question_id=question.id,
            ask_id=ask.id,
            state=state,
            basis=DecisionBasis.MAJORITY,
            value="yes",
            statement="Proceed" if state == DecisionState.COMMITTED else None,
            statement_source=DecisionStatementSource.DETERMINISTIC
            if state == DecisionState.COMMITTED
            else None,
            decided_by=owner.id,
            supersedes_decision_id=None,
            provenance={},
            shared_with_recipients_at=None,
            committed_at=at if state == DecisionState.COMMITTED else None,
            created_at=at,
        )
    )


def _client(
    override_session: Callable[[], Generator[Session]], actor: Callable[[], Actor]
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_actor] = actor
    return TestClient(app)
