import re
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_current_actor,
    get_db_session,
    get_token_generator,
    require_csrf,
)
from app.assistant.schemas import (
    AssistantTurn,
    DraftOption,
    DraftQuestion,
    NeedsClarification,
    QuestionDraft,
)
from app.assistant.service import get_draft_assistant
from app.auth.provisioning import create_login_invitation, provision_identity
from app.domain.access import create_project, grant_membership
from app.domain.enums import ActorKind, ContactKind, InitiativeKind, ResponseVisibility
from app.domain.initiatives import create_initiative
from app.domain.ports import IdentityClaims
from app.main import create_app
from app.models.identity import Actor, ContactMethod
from app.models.outcomes import Decision, DecisionResponse, Event, Response
from app.models.session import get_engine
from app.models.work import (
    Ask,
    AskQuestion,
    AskRecipient,
    Assignment,
    AuthoringSession,
    Question,
    QuestionOption,
)
from tests.fakes import DeterministicTokenGenerator, FixedClock

pytestmark = pytest.mark.integration


def test_manual_draft_authoring_slice() -> None:
    clock = FixedClock(datetime(2026, 7, 27, 10, 0, tzinfo=UTC))
    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(connection, join_transaction_mode="create_savepoint")
    app = create_app()

    def override_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[require_csrf] = lambda: None
    try:
        admin = _provision(session, clock, "draft-admin", "draft-admin@example.com", True)
        owner = _invite_member(session, clock, admin, "draft-owner", "draft-owner@example.com")
        other_member = _invite_member(
            session, clock, admin, "draft-other", "draft-other@example.com"
        )
        project = create_project(session, clock, acting_actor_id=admin.id, name="Draft Project")
        session.flush()
        grant_membership(
            session,
            clock,
            acting_actor_id=admin.id,
            project_id=project.id,
            actor_id=owner.id,
        )
        grant_membership(
            session,
            clock,
            acting_actor_id=admin.id,
            project_id=project.id,
            actor_id=other_member.id,
        )
        initiative = create_initiative(
            session,
            clock,
            acting_actor_id=owner.id,
            project_id=project.id,
            name="Manual authoring",
            kind=InitiativeKind.FEATURE,
        )
        session.flush()

        current_actor = [owner]
        app.dependency_overrides[get_current_actor] = lambda: current_actor[0]
        app.dependency_overrides[get_token_generator] = lambda: DeterministicTokenGenerator(
            "recipient"
        )
        assistant = FakeDraftAssistant(session)
        app.dependency_overrides[get_draft_assistant] = lambda: assistant
        with TestClient(app) as client:
            created = client.post(
                "/api/asks",
                json={
                    "project_id": str(project.id),
                    "initiative_id": str(initiative.id),
                    "title": "  Choose launch direction  ",
                    "intro": " Context ",
                },
            )
            assert created.status_code == 201, created.text
            aggregate = created.json()
            ask_id = aggregate["id"]
            assert aggregate["title"] == "Choose launch direction"
            assert aggregate["project"]["name"] == project.name
            assert aggregate["initiative"]["name"] == initiative.name
            assert aggregate["read_only"] is False

            current_actor[0] = other_member
            member_read = client.get(f"/api/asks/{ask_id}")
            assert member_read.status_code == 200
            assert member_read.json()["read_only"] is True
            assert (
                client.put(
                    f"/api/asks/{ask_id}",
                    json={"title": "Not mine", "critiques_overridden": []},
                ).status_code
                == 409
            )

            current_actor[0] = admin
            assert client.get(f"/api/asks/{ask_id}").status_code == 404

            current_actor[0] = owner
            updated = client.put(
                f"/api/asks/{ask_id}",
                json={
                    "title": "Launch direction",
                    "intro": "Updated context",
                    "deadline": "2026-07-30",
                    "timezone": "America/New_York",
                    "default_note": "Reply with rationale",
                    "critiques_overridden": [{"code": "known_tradeoff"}],
                },
            )
            assert updated.status_code == 200
            assert updated.json()["critiques_overridden"] == [{"code": "known_tradeoff"}]
            assert updated.json()["deadline"] == "2026-07-30T21:00:00Z"
            assert updated.json()["deadline_date"] == "2026-07-30"
            assert updated.json()["owner_timezone"] == "America/New_York"

            invalid = client.post(
                f"/api/asks/{ask_id}/questions",
                json={
                    "template_id": "decision_fork",
                    "prompt": "Choose",
                    "options": [
                        {"value": "a", "label": "A"},
                        {"value": "b", "label": "B"},
                    ],
                },
            )
            assert invalid.status_code == 409

            fork = client.post(
                f"/api/asks/{ask_id}/questions",
                json={
                    "template_id": "decision_fork",
                    "prompt": " Which launch path? ",
                    "help_text": "Consider risk",
                    "allow_comment": False,
                    "options": [
                        {"value": "safe", "label": "Safe", "consequence": "Slower"},
                        {"value": "fast", "label": "Fast", "consequence": "Riskier"},
                    ],
                    "critiques_overridden": [{"code": "binary_ok"}],
                },
            )
            assert fork.status_code == 201, fork.text
            fork_question = fork.json()["questions"][0]
            fork_id = fork_question["id"]
            assert [option["value"] for option in fork_question["options"]] == [
                "safe",
                "fast",
            ]

            text_question = client.post(
                f"/api/asks/{ask_id}/questions",
                json={"template_id": "open_question", "prompt": "What did we miss?"},
            )
            assert text_question.status_code == 201
            text_id = text_question.json()["questions"][1]["id"]

            edited = client.put(
                f"/api/asks/{ask_id}/questions/{fork_id}",
                json={
                    "template_id": "approval",
                    "prompt": "Approve launch?",
                    "options": [
                        {"value": "approve", "label": "Approve"},
                        {"value": "reject", "label": "Reject"},
                    ],
                },
            )
            assert edited.status_code == 200
            assert edited.json()["questions"][0]["template_id"] == "approval"

            assert client.delete(f"/api/asks/{ask_id}/questions/{fork_id}").status_code == 204
            after_delete = client.get(f"/api/asks/{ask_id}").json()
            assert [(item["id"], item["ordinal"]) for item in after_delete["questions"]] == [
                (text_id, 0)
            ]
            approval = client.post(
                f"/api/asks/{ask_id}/questions",
                json={
                    "template_id": "approval",
                    "prompt": "Approve the matching direction?",
                    "depends_on": {"question_id": text_id, "op": "answered"},
                    "options": [
                        {"value": "approve", "label": "Approve"},
                        {"value": "reject", "label": "Reject"},
                    ],
                },
            )
            assert approval.status_code == 201
            approval_id = approval.json()["questions"][1]["id"]
            assert approval.json()["questions"][1]["depends_on"] == {
                "question_id": text_id,
                "op": "answered",
            }

            first_recipient = client.post(
                f"/api/asks/{ask_id}/recipients",
                json={"display_name": " Sam Lee ", "email": "sam@example.com"},
            )
            second_recipient = client.post(
                f"/api/asks/{ask_id}/recipients",
                json={"display_name": "Sam Again", "email": "sam@example.com"},
            )
            assert first_recipient.status_code == second_recipient.status_code == 201
            assert first_recipient.json()["actor_id"] != second_recipient.json()["actor_id"]
            assert first_recipient.json()["open_assignments"] == 0
            assert first_recipient.json()["recent_assignments"] == 0
            assert first_recipient.json()["recent_asks"] == 0
            assert first_recipient.json()["window_days"] == 7
            assert first_recipient.json()["workload_warning"] is False
            recipient_id = first_recipient.json()["id"]
            second_recipient_id = second_recipient.json()["id"]
            preview = client.get(f"/api/asks/{ask_id}").json()
            assert len(preview["recipients"]) == 2
            assert all(
                [question["id"] for question in item["questions"]]
                == [
                    text_id,
                    approval_id,
                ]
                for item in preview["recipient_previews"]
            )
            assert client.delete(f"/api/asks/{ask_id}/recipients/{recipient_id}").status_code == 204
            assert len(client.get(f"/api/asks/{ask_id}").json()["recipients"]) == 1

            initiative.archived_at = clock.now()
            session.flush()
            assert client.get(f"/api/asks/{ask_id}").json()["read_only"] is True
            assert (
                client.put(
                    f"/api/asks/{ask_id}",
                    json={"title": "Archived", "critiques_overridden": []},
                ).status_code
                == 409
            )
            session.rollback()

            persisted_ask = session.get(Ask, ask_id)
            assert persisted_ask is not None
            project.archived_at = clock.now()
            session.flush()
            assert (
                client.post(
                    f"/api/asks/{ask_id}/recipients", json={"display_name": "Blocked"}
                ).status_code
                == 409
            )
            session.rollback()

            sent = client.post(f"/api/asks/{ask_id}/send")
            assert sent.status_code == 200, sent.text
            assert sent.json()["ask"]["status"] == "sent"
            sent_workload = sent.json()["ask"]["recipients"][0]
            assert sent_workload["open_assignments"] == 2
            assert sent_workload["recent_assignments"] == 2
            assert sent_workload["recent_asks"] == 1
            assert sent_workload["window_days"] == 7
            assert sent_workload["workload_warning"] is True
            assert len(sent.json()["artifacts"]) == 1
            assert sent.json()["artifacts"][0]["url"].endswith("/r/recipient-32")
            issued_recipient = session.get(AskRecipient, second_recipient_id)
            assert issued_recipient is not None
            assert "recipient-32" not in (issued_recipient.token_hash or "")

            crawler = client.get(
                "/r/recipient-32",
                headers={"User-Agent": "Slackbot-LinkExpanding 1.0"},
            )
            assert crawler.status_code == 200
            assert "Launch direction" in crawler.text
            assert "FAQ Development" in crawler.text
            assert "Sam Again" not in crawler.text
            assert "What did we miss?" not in crawler.text
            assert "Reply with rationale" not in crawler.text
            assert "faq_invitation" not in crawler.cookies

            exchange = client.get("/r/recipient-32", follow_redirects=False)
            assert exchange.status_code == 303
            assert exchange.headers["location"] == f"/r/i/{second_recipient_id}"
            assert "HttpOnly" in exchange.headers["set-cookie"]
            assert "SameSite=lax" in exchange.headers["set-cookie"]
            invitation = client.get(exchange.headers["location"])
            assert invitation.status_code == 200
            assert "Launch direction" in invitation.text
            assert "What did we miss?" in invitation.text
            assert "Approve the matching direction?" not in invitation.text
            assert "0 of 1 questions answered." in invitation.text
            assert "Delegate display name" in invitation.text
            assert 'Required when you choose &quot;Not my call' in invitation.text
            assert invitation.headers["content-security-policy"].startswith("default-src")
            assert invitation.headers["x-frame-options"] == "DENY"
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', invitation.text)
            submission = re.search(r'name="submission_id" value="([^"]+)"', invitation.text)
            assert csrf is not None and submission is not None
            assignment = session.scalar(
                select(Assignment).where(
                    Assignment.ask_recipient_id == UUID(second_recipient_id),
                    Assignment.question_id == UUID(text_id),
                )
            )
            assert assignment is not None
            approval_assignment = session.scalar(
                select(Assignment).where(
                    Assignment.ask_recipient_id == UUID(second_recipient_id),
                    Assignment.question_id == UUID(approval_id),
                )
            )
            assert approval_assignment is not None
            assert approval_assignment.state.value == "blocked"
            answer_path = f"/r/i/{second_recipient_id}/questions/{assignment.id}"
            approval_path = f"/r/i/{second_recipient_id}/questions/{approval_assignment.id}"
            answer_data = {
                "csrf_token": csrf.group(1),
                "submission_id": submission.group(1),
                "disposition": "answered",
                "value": "The matching cohort should include active trial candidates.",
                "comment": "Include screening status.",
            }
            blocked_post = client.post(
                approval_path,
                data={
                    "csrf_token": csrf.group(1),
                    "submission_id": str(uuid4()),
                    "disposition": "answered",
                    "value": "approve",
                },
            )
            assert blocked_post.status_code == 422
            assert "Approve the matching direction?" not in blocked_post.text
            saved = client.post(answer_path, data=answer_data, follow_redirects=False)
            assert saved.status_code == 303
            assert (
                client.post(answer_path, data=answer_data, follow_redirects=False).status_code
                == 303
            )
            responses = list(
                session.scalars(select(Response).where(Response.assignment_id == assignment.id))
            )
            assert len(responses) == 1
            assert responses[0].version == 1
            answered_page = client.get(exchange.headers["location"])
            assert "Saved response, version 1" in answered_page.text
            assert "active trial candidates" in answered_page.text
            assert "1 of 2 questions answered." in answered_page.text
            assert "Approve the matching direction?" in answered_page.text
            assert "class='saved' role='status'" in answered_page.text

            invalid_submission = re.search(
                r'name="submission_id" value="([^"]+)"', answered_page.text
            )
            invalid_csrf = re.search(r'name="csrf_token" value="([^"]+)"', answered_page.text)
            assert invalid_submission is not None and invalid_csrf is not None
            invalid_answer = client.post(
                answer_path,
                data={
                    "csrf_token": invalid_csrf.group(1),
                    "submission_id": invalid_submission.group(1),
                    "disposition": "answered",
                    "value": "",
                },
            )
            assert invalid_answer.status_code == 422
            assert "text must contain at least 1 characters" in invalid_answer.text
            assert (
                len(
                    list(
                        session.scalars(
                            select(Response).where(Response.assignment_id == assignment.id)
                        )
                    )
                )
                == 1
            )

            revision_page = client.get(exchange.headers["location"])
            revision_submission = re.search(
                r'name="submission_id" value="([^"]+)"', revision_page.text
            )
            revision_csrf = re.search(r'name="csrf_token" value="([^"]+)"', revision_page.text)
            assert revision_submission is not None and revision_csrf is not None
            delegated = client.post(
                answer_path,
                data={
                    "csrf_token": revision_csrf.group(1),
                    "submission_id": revision_submission.group(1),
                    "disposition": "need_context",
                    "value": "stale value must not persist",
                },
                follow_redirects=False,
            )
            assert delegated.status_code == 303
            latest_response = session.scalar(
                select(Response)
                .where(Response.assignment_id == assignment.id)
                .order_by(Response.version.desc())
            )
            assert latest_response is not None
            assert latest_response.version == 2
            assert latest_response.value is None
            assert latest_response.comment is None
            session.refresh(assignment)
            assert assignment.state.value == "responded"
            session.refresh(approval_assignment)
            assert approval_assignment.state.value == "withdrawn"
            withdrawn_page = client.get(exchange.headers["location"])
            assert "Approve the matching direction?" not in withdrawn_page.text
            reactivate = client.post(
                answer_path,
                data={
                    "csrf_token": revision_csrf.group(1),
                    "submission_id": str(uuid4()),
                    "disposition": "answered",
                    "value": "The cohort remains appropriate.",
                },
                follow_redirects=False,
            )
            assert reactivate.status_code == 303
            reactivated_assignment = session.get(Assignment, approval_assignment.id)
            assert reactivated_assignment is not None
            assert reactivated_assignment.state.value == "pending"
            latest_response = session.scalar(
                select(Response)
                .where(Response.assignment_id == assignment.id)
                .order_by(Response.version.desc())
            )
            assert latest_response is not None
            invalid_option = client.post(
                approval_path,
                data={
                    "csrf_token": revision_csrf.group(1),
                    "submission_id": str(uuid4()),
                    "disposition": "answered",
                    "value": "not-an-option",
                },
            )
            assert invalid_option.status_code == 422
            approved = client.post(
                approval_path,
                data={
                    "csrf_token": revision_csrf.group(1),
                    "submission_id": str(uuid4()),
                    "disposition": "answered",
                    "value": "approve",
                },
                follow_redirects=False,
            )
            assert approved.status_code == 303
            assert client.post(
                answer_path,
                data={
                    "csrf_token": revision_csrf.group(1),
                    "submission_id": str(uuid4()),
                    "disposition": "abstain",
                },
                follow_redirects=False,
            ).status_code == 303
            session.refresh(approval_assignment)
            assert approval_assignment.state.value == "withdrawn"
            assert session.scalar(
                select(Response).where(Response.assignment_id == approval_assignment.id)
            ) is not None
            assert client.post(
                answer_path,
                data={
                    "csrf_token": revision_csrf.group(1),
                    "submission_id": str(uuid4()),
                    "disposition": "answered",
                    "value": "The cohort remains appropriate.",
                },
                follow_redirects=False,
            ).status_code == 303
            retained_assignment = session.get(Assignment, approval_assignment.id)
            assert retained_assignment is not None
            assert retained_assignment.state.value == "responded"
            latest_response = session.scalar(
                select(Response)
                .where(Response.assignment_id == assignment.id)
                .order_by(Response.version.desc())
            )
            assert latest_response is not None

            reissued = client.post(f"/api/asks/{ask_id}/recipients/{second_recipient_id}/reissue")
            assert reissued.status_code == 200
            assert client.get(exchange.headers["location"]).status_code == 410
            replacement_exchange = client.get(
                urlparse(reissued.json()["url"]).path,
                follow_redirects=False,
            )
            assert replacement_exchange.status_code == 303
            checklist = client.put(
                f"/api/asks/{ask_id}/recipients/{second_recipient_id}/checklist",
                json={"sent": True},
            )
            assert checklist.status_code == 200
            assert checklist.json()["share_marked_sent_at"] is not None

            results = client.get(f"/api/asks/{ask_id}/results")
            assert results.status_code == 200
            assert results.json()["can_decide"] is True
            text_result, approval_result = results.json()["questions"]
            assert [item["version"] for item in text_result["assignments"][0]["revisions"]] == [
                1,
                2,
                3,
                4,
                5,
            ]
            assert text_result["assignments"][0]["latest_response"]["disposition"] == ("answered")
            assert approval_result["assignments"][0]["latest_response"]["value"] == ("approve")

            current_actor[0] = other_member
            hidden_results = client.get(f"/api/asks/{ask_id}/results")
            assert hidden_results.status_code == 200
            hidden_assignment = hidden_results.json()["questions"][0]["assignments"][0]
            assert hidden_assignment["response_visible"] is False
            assert hidden_assignment["latest_response"] is None

            visibility_question: Question | None = session.get(Question, UUID(text_id))
            assert visibility_question is not None
            visibility_question.response_visibility = ResponseVisibility.IMMEDIATE
            session.flush()
            immediate_results = client.get(f"/api/asks/{ask_id}/results").json()
            assert immediate_results["questions"][0]["assignments"][0]["response_visible"] is True

            visibility_question.response_visibility = ResponseVisibility.AFTER_CLOSE
            session.flush()
            after_close_results = client.get(f"/api/asks/{ask_id}/results").json()
            after_close_assignment = after_close_results["questions"][0]["assignments"][0]
            assert after_close_assignment["response_visible"] is False
            visibility_question.response_visibility = ResponseVisibility.AFTER_OWN_RESPONSE
            session.flush()
            forbidden_decision = client.post(
                f"/api/asks/{ask_id}/questions/{text_id}/decision",
                json={
                    "statement": "Not the owner's Decision",
                    "outcome_effect": "unchanged",
                },
            )
            assert forbidden_decision.status_code == 409
            current_actor[0] = owner

            missing_note = client.post(
                f"/api/asks/{ask_id}/questions/{text_id}/decision",
                json={
                    "statement": "Operations will define the matching cohort.",
                    "evidence": [{"response_id": str(latest_response.id), "role": "context"}],
                    "outcome_effect": "clarified",
                },
            )
            assert missing_note.status_code == 409
            text_decision = client.post(
                f"/api/asks/{ask_id}/questions/{text_id}/decision",
                json={
                    "statement": "Operations will define the matching cohort.",
                    "evidence": [{"response_id": str(latest_response.id), "role": "context"}],
                    "outcome_effect": "clarified",
                    "outcome_effect_note": "The response identified the accountable team.",
                },
            )
            assert text_decision.status_code == 200, text_decision.text
            assert text_decision.json()["status"] == "sent"
            assert (
                text_decision.json()["questions"][0]["decision"]["substantive_evidence_count"] == 0
            )
            partial_page = client.get(replacement_exchange.headers["location"])
            assert "This Question is closed" in partial_page.text
            assert "Approve the matching direction?" in partial_page.text

            approved_response = session.scalar(
                select(Response)
                .where(Response.assignment_id == approval_assignment.id)
                .order_by(Response.version.desc())
            )
            assert approved_response is not None
            final_decision = client.post(
                f"/api/asks/{ask_id}/questions/{approval_id}/decision",
                json={
                    "statement": "The matching direction is approved.",
                    "value": "approve",
                    "evidence": [{"response_id": str(approved_response.id), "role": "determining"}],
                    "outcome_effect": "unchanged",
                    "share_with_recipients": True,
                },
            )
            assert final_decision.status_code == 200, final_decision.text
            closed_results = final_decision.json()
            assert closed_results["status"] == "closed"
            assert closed_results["can_decide"] is False
            assert (
                closed_results["questions"][1]["decision"]["shared_with_recipients_at"] is not None
            )
            assert closed_results["questions"][1]["decision"]["substantive_evidence_count"] == 1
            closed_ask = session.get(Ask, UUID(ask_id))
            assert closed_ask is not None and closed_ask.closed_at is not None
            session.refresh(issued_recipient)
            assert issued_recipient.access_expires_at is not None
            assert issued_recipient.access_expires_at <= closed_ask.closed_at + timedelta(days=30)
            closed_page = client.get(replacement_exchange.headers["location"])
            assert closed_page.status_code == 200
            assert "The matching direction is approved." in closed_page.text
            assert "active trial candidates" not in closed_page.text
            assert client.post(f"/api/asks/{ask_id}/cancel").status_code == 409
            decisions = list(
                session.scalars(select(Decision).where(Decision.ask_id == UUID(ask_id)))
            )
            assert len(decisions) == 2
            evidence_links = list(session.scalars(select(DecisionResponse)))
            assert len(evidence_links) == 2
            event_types = set(
                session.scalars(select(Event.type).where(Event.ask_id == UUID(ask_id)))
            )
            assert {
                "decision.committed",
                "decision.shared",
                "question.closed",
                "question.outcome_recorded",
                "ask.closed",
            } <= event_types

            cancellable = client.post(
                "/api/asks",
                json={
                    "project_id": str(project.id),
                    "initiative_id": str(initiative.id),
                    "title": "Cancellation path",
                },
            )
            assert cancellable.status_code == 201
            cancellable_id = cancellable.json()["id"]
            assert (
                client.post(
                    f"/api/asks/{cancellable_id}/questions",
                    json={"template_id": "open_question", "prompt": "Still needed?"},
                ).status_code
                == 201
            )
            cancelled_recipient = client.post(
                f"/api/asks/{cancellable_id}/recipients",
                json={"display_name": "Cancellation recipient"},
            )
            assert cancelled_recipient.status_code == 201
            app.dependency_overrides[get_token_generator] = lambda: DeterministicTokenGenerator(
                "cancel"
            )
            cancellation_send = client.post(f"/api/asks/{cancellable_id}/send")
            assert cancellation_send.status_code == 200
            cancellation_url = cancellation_send.json()["artifacts"][0]["url"]
            cancellation_exchange = client.get(
                urlparse(cancellation_url).path, follow_redirects=False
            )
            assert cancellation_exchange.status_code == 303
            cancellation_invitation_path = cancellation_exchange.headers["location"]
            assert client.get(cancellation_invitation_path).status_code == 200
            cancelled = client.post(f"/api/asks/{cancellable_id}/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"
            assert client.get(urlparse(cancellation_url).path).status_code == 404
            assert client.get(cancellation_invitation_path).status_code == 410
            cancelled_assignment = session.scalar(
                select(Assignment).where(Assignment.ask_id == UUID(cancellable_id))
            )
            assert cancelled_assignment is not None
            assert cancelled_assignment.state.value == "expired"
            assert "ask.cancelled" in set(
                session.scalars(select(Event.type).where(Event.ask_id == UUID(cancellable_id)))
            )

            revocable = client.post(
                "/api/asks",
                json={
                    "project_id": str(project.id),
                    "initiative_id": str(initiative.id),
                    "title": "Revocation and expiry path",
                },
            )
            revocable_id = revocable.json()["id"]
            assert (
                client.post(
                    f"/api/asks/{revocable_id}/questions",
                    json={"template_id": "open_question", "prompt": "Can access continue?"},
                ).status_code
                == 201
            )
            revocable_recipient = client.post(
                f"/api/asks/{revocable_id}/recipients",
                json={"display_name": "Revocable recipient"},
            )
            revocable_recipient_id = revocable_recipient.json()["id"]
            app.dependency_overrides[get_token_generator] = lambda: DeterministicTokenGenerator(
                "revoke"
            )
            revocation_send = client.post(f"/api/asks/{revocable_id}/send")
            assert revocation_send.status_code == 200
            revocation_url = revocation_send.json()["artifacts"][0]["url"]
            revocation_exchange = client.get(urlparse(revocation_url).path, follow_redirects=False)
            assert revocation_exchange.status_code == 303
            revocation_invitation_path = revocation_exchange.headers["location"]
            assert client.get(revocation_invitation_path).status_code == 200

            expiring_recipient = session.get(AskRecipient, UUID(revocable_recipient_id))
            assert expiring_recipient is not None
            original_expiry = expiring_recipient.access_expires_at
            assert original_expiry is not None
            expiring_recipient.access_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
            assert client.get(urlparse(revocation_url).path).status_code == 404
            assert client.get(revocation_invitation_path).status_code == 410

            expiring_recipient.access_expires_at = original_expiry
            session.commit()
            assert (
                client.get(urlparse(revocation_url).path, follow_redirects=False).status_code == 303
            )
            assert (
                client.delete(
                    f"/api/asks/{revocable_id}/recipients/{revocable_recipient_id}"
                ).status_code
                == 204
            )
            assert client.get(urlparse(revocation_url).path).status_code == 404
            assert client.get(revocation_invitation_path).status_code == 410
            revoked_assignment = session.scalar(
                select(Assignment).where(Assignment.ask_id == UUID(revocable_id))
            )
            assert revoked_assignment is not None
            assert revoked_assignment.state.value == "withdrawn"
            assert "ask_recipient.revoked" in set(
                session.scalars(select(Event.type).where(Event.ask_id == UUID(revocable_id)))
            )

            ai_ask = client.post(
                "/api/asks",
                json={
                    "project_id": str(project.id),
                    "initiative_id": str(initiative.id),
                    "title": "Rough AI draft",
                },
            )
            assert ai_ask.status_code == 201
            ai_ask_id = ai_ask.json()["id"]
            clarification = client.post(
                f"/api/asks/{ai_ask_id}/assistant",
                json={"source": "We should improve matching."},
            )
            assert clarification.status_code == 200, clarification.text
            assert clarification.json()["kind"] == "clarification"
            authoring_session_id = clarification.json()["authoring_session_id"]
            drafted = client.post(
                f"/api/asks/{ai_ask_id}/assistant",
                json={
                    "source": "Casey decides which records should match.",
                    "authoring_session_id": authoring_session_id,
                },
            )
            assert drafted.status_code == 200, drafted.text
            assert drafted.json()["kind"] == "draft"
            assert drafted.json()["prompt_version"] == "draft-v2"
            assert drafted.json()["draft"]["title"] == "Confirm the matching model"
            assert len(drafted.json()["draft"]["questions"]) == 2
            critique_codes = {item["code"] for item in drafted.json()["critiques"]}
            assert {"missing_escape_hatch", "missing_deadline"} <= critique_codes
            assert "dependency_flattened" not in critique_codes

            authoring = session.get(AuthoringSession, authoring_session_id)
            assert authoring is not None
            assert authoring.ask_id == UUID(ai_ask_id)
            assert authoring.conversation_id == "conversation-1"
            ai_questions = list(
                session.scalars(
                    select(Question)
                    .join(AskQuestion, AskQuestion.question_id == Question.id)
                    .where(AskQuestion.ask_id == UUID(ai_ask_id))
                )
            )
            assert all(question.origin.value == "agent_surfaced" for question in ai_questions)
            by_prompt = {question.prompt: question for question in ai_questions}
            assert by_prompt["Which patients should match?"].depends_on == {
                "question_id": str(by_prompt["Which matching model should we implement?"].id),
                "op": "answered",
            }
            ai_events = set(
                session.scalars(select(Event.type).where(Event.ask_id == UUID(ai_ask_id)))
            )
            assert {
                "authoring.clarification_requested",
                "authoring.draft_applied",
            } <= ai_events

        question = session.get(Question, text_id)
        assert question is not None
        assert question.template_id == "open_question"
        assert question.validation == {"min_length": 1}
        assert question.state.value == "closed"
        assert (
            list(
                session.scalars(select(QuestionOption).where(QuestionOption.question_id == text_id))
            )
            == []
        )
        deleted_link = session.get(AskQuestion, (ask_id, fork_id))
        assert deleted_link is not None and deleted_link.superseded_at is not None
        recipient = session.get(AskRecipient, recipient_id)
        assert recipient is not None and recipient.revoked_at is not None
        assert recipient.token_hash is None
        closed_recipient = session.get(AskRecipient, second_recipient_id)
        assert closed_recipient is not None
        assert closed_recipient.revoked_at is None
        assert closed_recipient.session_version == 2
        lightweight_actor = session.get(Actor, recipient.actor_id)
        assert lightweight_actor is not None
        assert lightweight_actor.kind == ActorKind.HUMAN
        assert lightweight_actor.firebase_uid is None
        contact = session.scalar(
            select(ContactMethod).where(
                ContactMethod.actor_id == recipient.actor_id,
                ContactMethod.kind == ContactKind.EMAIL,
            )
        )
        assert contact is not None and contact.value == "sam@example.com"
        event_types = set(
            session.scalars(select(Event.type).where(Event.ask_id == persisted_ask.id))
        )
        assert {
            "ask.created",
            "ask.updated",
            "question.created",
            "question.updated",
            "question.deleted",
            "ask_recipient.added",
            "ask_recipient.revoked",
            "ask.sent",
            "assignment.created",
            "ask_recipient.credential_issued",
        } <= event_types
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _invite_member(
    session: Session, clock: FixedClock, admin: Actor, uid: str, email: str
) -> Actor:
    create_login_invitation(session, clock, acting_actor_id=admin.id, email=email)
    return _provision(session, clock, uid, email, False)


def _provision(session: Session, clock: FixedClock, uid: str, email: str, bootstrap: bool) -> Actor:
    return provision_identity(
        session,
        clock,
        IdentityClaims(uid=uid, email=email, email_verified=True, display_name=uid),
        bootstrap_admin_email=email if bootstrap else "draft-admin@example.com",
    )


class FakeDraftAssistant:
    def __init__(self, session: Session) -> None:
        self.calls = 0
        self.session = session

    def run(
        self,
        source: str,
        *,
        history: list[ModelMessage],
        conversation_id: str | None,
    ) -> AssistantTurn:
        assert not self.session.in_transaction()
        self.calls += 1
        if self.calls == 1:
            return AssistantTurn(
                output=NeedsClarification(
                    question="Who decides which patients should match?",
                    reason="The decision owner is unclear.",
                ),
                conversation_id="conversation-1",
                messages=[],
            )
        assert conversation_id == "conversation-1"
        return AssistantTurn(
            output=QuestionDraft(
                title="Confirm the matching model",
                intro="Confirm the desired state before implementation.",
                questions=[
                    DraftQuestion(
                        template_id="decision_fork",
                        prompt="Which matching model should we implement?",
                        options=[
                            DraftOption(value="exact", label="Exact", consequence="Less reach"),
                            DraftOption(value="broad", label="Broad", consequence="More review"),
                        ],
                    ),
                    DraftQuestion(
                        template_id="open_question",
                        prompt="Which patients should match?",
                        depends_on_question_index=0,
                    ),
                ],
            ),
            conversation_id="conversation-1",
            messages=[],
        )
