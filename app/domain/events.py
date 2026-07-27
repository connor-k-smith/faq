from enum import StrEnum
from ipaddress import ip_address
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.ports import Clock
from app.models.outcomes import Event


class EventName(StrEnum):
    ACTOR_CREATED = "actor.created"
    ACTOR_DEACTIVATED = "actor.deactivated"
    ACTOR_MERGED = "actor.merged"
    ACTOR_ROLE_CHANGED = "actor.role_changed"
    LOGIN_INVITATION_CREATED = "login_invitation.created"
    LOGIN_INVITATION_CONSUMED = "login_invitation.consumed"
    MEMBERSHIP_GRANTED = "membership.granted"
    MEMBERSHIP_REVOKED = "membership.revoked"
    ASK_OWNERSHIP_TRANSFERRED = "ask.ownership_transferred"
    PROJECT_CREATED = "project.created"
    PROJECT_ARCHIVED = "project.archived"
    PROJECT_REACTIVATED = "project.reactivated"
    PROJECT_UPDATED = "project.updated"
    PURGE_REQUESTED = "purge.requested"
    LOGIN_INVITATION_REVOKED = "login_invitation.revoked"
    INITIATIVE_CREATED = "initiative.created"
    INITIATIVE_UPDATED = "initiative.updated"
    INITIATIVE_ARCHIVED = "initiative.archived"
    INITIATIVE_REACTIVATED = "initiative.reactivated"
    ASK_CREATED = "ask.created"
    ASK_UPDATED = "ask.updated"
    ASK_CANCELLED = "ask.cancelled"
    ASK_SENT = "ask.sent"
    ASK_DEADLINE_REPLACED = "ask.deadline_replaced"
    SUCCESSOR_ASK_CREATED = "ask.successor_created"
    AUTHORING_CLARIFICATION_REQUESTED = "authoring.clarification_requested"
    AUTHORING_DRAFT_APPLIED = "authoring.draft_applied"
    QUESTION_CREATED = "question.created"
    QUESTION_UPDATED = "question.updated"
    QUESTION_SUPERSEDED = "question.superseded"
    QUESTION_DELETED = "question.deleted"
    RECIPIENT_ADDED = "ask_recipient.added"
    RECIPIENT_REVOKED = "ask_recipient.revoked"
    RECIPIENT_CREDENTIAL_ISSUED = "ask_recipient.credential_issued"
    RECIPIENT_SHARE_MARKED_SENT = "ask_recipient.share_marked_sent"
    ASSIGNMENT_CREATED = "assignment.created"
    ASSIGNMENT_ACTIVATED = "assignment.activated"
    ASSIGNMENT_EXPIRED = "assignment.expired"
    ASSIGNMENT_WITHDRAWN = "assignment.withdrawn"
    RESPONSE_SUBMITTED = "response.submitted"
    DECISION_PROPOSED = "decision.proposed"
    DECISION_COMMITTED = "decision.committed"
    DECISION_SUPERSEDED = "decision.superseded"
    DECISION_SHARED = "decision.shared"
    QUESTION_CLOSED = "question.closed"
    QUESTION_OUTCOME_RECORDED = "question.outcome_recorded"
    ASK_CLOSED = "ask.closed"
    INTEGRATION_TRIGGER_ATTEMPTED = "integration.trigger_attempted"


def emit_event(
    session: Session,
    clock: Clock,
    event_name: EventName,
    *,
    actor_id: UUID | None = None,
    project_id: UUID | None = None,
    ask_id: UUID | None = None,
    question_id: UUID | None = None,
    assignment_id: UUID | None = None,
    ask_recipient_id: UUID | None = None,
    data: dict[str, object] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Event:
    event = Event(
        at=clock.now(),
        type=event_name.value,
        actor_id=actor_id,
        project_id=project_id,
        ask_id=ask_id,
        question_id=question_id,
        assignment_id=assignment_id,
        ask_recipient_id=ask_recipient_id,
        data=data or {},
        ip=ip_address(ip) if ip else None,
        user_agent=user_agent,
    )
    session.add(event)
    return event
