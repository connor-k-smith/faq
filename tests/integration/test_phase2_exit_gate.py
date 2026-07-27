from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
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
    QuestionClosePolicy,
    QuestionOpenTo,
    QuestionOrigin,
    QuestionPrimitive,
    QuestionState,
    ResponseVisibility,
)
from app.domain.initiatives import create_initiative
from app.domain.ports import IdentityClaims
from app.google_identity import get_google_identity_verifier
from app.main import create_app
from app.models.identity import Actor, Project
from app.models.outcomes import Decision, Event
from app.models.session import get_engine
from app.models.work import Ask, AskQuestion, AskRecipient, Question
from app.operator_main import create_app as create_operator_app
from tests.fakes import FakeGoogleIdentityVerifier, FixedClock

pytestmark = pytest.mark.integration


def test_two_project_feed_and_search_do_not_reveal_hidden_exact_text() -> None:
    with _test_session() as (session, override_session):
        clock, member, other_member, first, second = _two_project_data(session)
        visible = _decision_graph(session, clock, member, first, "Visible launch record")
        hidden_text = "saffron-orbit-credential-7391"
        _decision_graph(session, clock, other_member, second, hidden_text)
        session.flush()

        app = create_app()
        app.dependency_overrides[get_db_session] = override_session
        app.dependency_overrides[get_current_actor] = lambda: member
        with TestClient(app) as client:
            feed = client.get(f"/api/projects/{first.id}/feed")
            search = client.get(f"/api/projects/{first.id}/feed", params={"q": hidden_text})
            forbidden = client.get(f"/api/projects/{second.id}/feed", params={"q": hidden_text})

        assert feed.status_code == 200
        assert [item["source_id"] for item in feed.json()["items"]] == [str(visible.id)]
        assert hidden_text not in feed.text
        assert search.status_code == 200
        assert search.json()["items"] == []
        assert hidden_text not in search.text
        assert forbidden.status_code == 404
        assert hidden_text not in forbidden.text


def test_markdown_decision_export_requires_membership_and_leaks_no_credentials() -> None:
    with _test_session() as (session, override_session):
        clock, member, outsider, project, _ = _two_project_data(session)
        decision = _decision_graph(session, clock, member, project, "Ship the bounded pilot.")
        secret = "respondent-token-hash-that-must-not-export"
        session.add(
            AskRecipient(
                id=uuid4(),
                project_id=project.id,
                ask_id=decision.ask_id,
                actor_id=outsider.id,
                display_name="External reviewer",
                token_hash=secret,
                token_issued_at=clock.now(),
                session_version=7,
                revoked_at=None,
                access_expires_at=clock.now(),
                share_marked_sent_at=None,
                created_at=clock.now(),
            )
        )
        session.flush()

        current_actor = [member]
        app = create_app()
        app.dependency_overrides[get_db_session] = override_session
        app.dependency_overrides[get_current_actor] = lambda: current_actor[0]
        with TestClient(app) as client:
            exported = client.get(f"/d/{decision.id}.md")
            current_actor[0] = outsider
            denied = client.get(f"/d/{decision.id}.md")

        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("text/markdown")
        assert exported.headers["cache-control"] == "private, no-store"
        assert "# Decision:" in exported.text
        assert "Ship the bounded pilot." in exported.text
        assert str(decision.id) in exported.text
        assert secret not in exported.text
        assert "token" not in exported.text.lower()
        assert denied.status_code == 404
        assert "Ship the bounded pilot." not in denied.text


def test_operator_redaction_and_guarded_audited_emergency_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAQ_OPERATOR_AUDIENCE", "operator-audience")
    monkeypatch.setenv("FAQ_OPERATOR_ALLOWED_EMAILS", '["operator@example.com"]')
    with _test_session() as (session, override_session):
        clock, member, _, project, _ = _two_project_data(session)
        decision = _decision_graph(session, clock, member, project, "Private decision body")
        ask = session.get_one(Ask, decision.ask_id)
        ask.status = AskStatus.DRAFT
        secret = "operator-inspection-secret"
        session.add(
            Event(
                at=clock.now(),
                project_id=project.id,
                ask_id=ask.id,
                question_id=None,
                assignment_id=None,
                ask_recipient_id=None,
                actor_id=member.id,
                type="credential.test",
                data={"token": secret, "nested": {"token_hash": secret}, "safe": "retained"},
                ip=None,
                user_agent=None,
            )
        )
        session.flush()

        app = create_operator_app()
        app.dependency_overrides[get_db_session] = override_session
        app.dependency_overrides[get_google_identity_verifier] = FakeGoogleIdentityVerifier
        headers = {"Authorization": "Bearer valid-token"}
        with TestClient(app) as client:
            events = client.get("/admin/inspect/events", headers=headers)
            guarded = client.post(
                f"/admin/projects/{project.id}",
                json={"archived": True, "reason": "Emergency containment"},
                headers=headers,
            )
            ask.status = AskStatus.CLOSED
            ask.closed_at = clock.now()
            changed = client.post(
                f"/admin/projects/{project.id}",
                json={"name": "Recovered Project", "reason": "Correct corrupted label"},
                headers=headers,
            )

        assert events.status_code == 200
        assert secret not in events.text
        record = next(item for item in events.json() if item["label"] == "credential.test")
        assert record["detail"]["data"] == {
            "token": "[redacted]",
            "nested": {"token_hash": "[redacted]"},
            "safe": "retained",
        }
        assert guarded.status_code == 409
        assert changed.status_code == 200
        assert changed.json()["label"] == "Recovered Project"
        audit = session.scalar(
            select(Event)
            .where(Event.project_id == project.id, Event.type == "project.updated")
            .order_by(Event.id.desc())
        )
        assert audit is not None
        assert audit.data["source"] == "operator_emergency"
        assert audit.data["operator"] == "operator@example.com"
        assert audit.data["reason"] == "Correct corrupted label"


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


def _two_project_data(
    session: Session,
) -> tuple[FixedClock, Actor, Actor, Project, Project]:
    clock = FixedClock(datetime(2026, 7, 25, 18, 0, tzinfo=UTC))
    admin = _provision(
        session, clock, f"gate-admin-{uuid4()}", f"gate-admin-{uuid4()}@example.com", True
    )
    member = _invite(session, clock, admin, "gate-member")
    other_member = _invite(session, clock, admin, "gate-other")
    first = create_project(session, clock, acting_actor_id=admin.id, name=f"First {uuid4()}")
    second = create_project(session, clock, acting_actor_id=admin.id, name=f"Second {uuid4()}")
    session.flush()
    grant_membership(
        session, clock, acting_actor_id=admin.id, project_id=first.id, actor_id=member.id
    )
    grant_membership(
        session, clock, acting_actor_id=admin.id, project_id=second.id, actor_id=other_member.id
    )
    session.flush()
    return clock, member, other_member, first, second


def _decision_graph(
    session: Session, clock: FixedClock, owner: Actor, project: Project, statement: str
) -> Decision:
    initiative = create_initiative(
        session,
        clock,
        acting_actor_id=owner.id,
        project_id=project.id,
        name=f"Initiative {uuid4()}",
        kind=InitiativeKind.FEATURE,
    )
    ask = Ask(
        id=uuid4(),
        project_id=project.id,
        initiative_id=initiative.id,
        parent_ask_id=None,
        title=f"Ask {uuid4()}",
        intro=None,
        created_by=owner.id,
        deadline=None,
        default_note=None,
        status=AskStatus.CLOSED,
        owner_id=owner.id,
        sent_at=clock.now(),
        closed_at=clock.now(),
        share_message=None,
        critiques_overridden=[],
        created_at=clock.now(),
    )
    question = Question(
        id=uuid4(),
        project_id=project.id,
        template_id="open_question",
        primitive=QuestionPrimitive.TEXT,
        version=1,
        supersedes_question_id=None,
        copied_from_question_id=None,
        state=QuestionState.CLOSED,
        origin=QuestionOrigin.AUTHOR,
        prompt="What should happen?",
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
        close_policy=QuestionClosePolicy.ALL_RESPONDED,
        auto_commit=False,
        auto_commit_if=None,
        created_by=owner.id,
        critiques_overridden=[],
        close_eligible_at=clock.now(),
        closed_at=clock.now(),
        outcome_effect=None,
        outcome_effect_note=None,
        created_at=clock.now(),
    )
    decision = Decision(
        id=uuid4(),
        project_id=project.id,
        question_id=question.id,
        ask_id=ask.id,
        state=DecisionState.COMMITTED,
        basis=DecisionBasis.ASKER_JUDGMENT,
        value=statement,
        statement=statement,
        statement_source=DecisionStatementSource.OWNER,
        decided_by=owner.id,
        supersedes_decision_id=None,
        provenance={},
        shared_with_recipients_at=None,
        committed_at=clock.now(),
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
    session.flush()
    session.add(decision)
    return decision


def _invite(session: Session, clock: FixedClock, admin: Actor, prefix: str) -> Actor:
    email = f"{prefix}-{uuid4()}@example.com"
    create_login_invitation(session, clock, acting_actor_id=admin.id, email=email)
    return _provision(session, clock, f"{prefix}-{uuid4()}", email, False)


def _provision(session: Session, clock: FixedClock, uid: str, email: str, bootstrap: bool) -> Actor:
    return provision_identity(
        session,
        clock,
        IdentityClaims(uid=uid, email=email, email_verified=True, display_name=uid),
        bootstrap_admin_email=email if bootstrap else "not-the-bootstrap@example.com",
    )
