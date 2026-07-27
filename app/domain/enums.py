from enum import StrEnum


class ActorKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class OrganizationRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


class ContactKind(StrEnum):
    EMAIL = "email"
    SLACK = "slack"
    SMS = "sms"
    WEBHOOK = "webhook"


class InitiativeKind(StrEnum):
    FEATURE = "feature"
    MILESTONE = "milestone"
    WORKSTREAM = "workstream"
    OTHER = "other"


class QuestionPrimitive(StrEnum):
    SELECT_ONE = "select_one"
    SELECT_MANY = "select_many"
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    DATE_RANGE = "date_range"
    BOOL = "bool"
    RANK = "rank"
    SCALE = "scale"


class QuestionOpenTo(StrEnum):
    ASSIGNED_ONLY = "assigned_only"
    PROJECT_MEMBERS = "project_members"


class ResponseVisibility(StrEnum):
    IMMEDIATE = "immediate"
    AFTER_OWN_RESPONSE = "after_own_response"
    AFTER_CLOSE = "after_close"


class QuestionState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    SUPERSEDED = "superseded"


class QuestionClosePolicy(StrEnum):
    ALL_RESPONDED = "all_responded"
    DEADLINE = "deadline"
    EITHER = "either"


class QuestionOrigin(StrEnum):
    AUTHOR = "author"
    AGENT_SURFACED = "agent_surfaced"
    AGENT_RESTRUCTURED = "agent_restructured"


class OutcomeEffect(StrEnum):
    UNCHANGED = "unchanged"
    CLARIFIED = "clarified"
    CHANGED = "changed"


class AskStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class AssignmentOrigin(StrEnum):
    ASSIGNED = "assigned"
    UNSOLICITED = "unsolicited"
    DELEGATED = "delegated"


class AssignmentState(StrEnum):
    BLOCKED = "blocked"
    PENDING = "pending"
    RESPONDED = "responded"
    DELEGATED = "delegated"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class ResponseDisposition(StrEnum):
    ANSWERED = "answered"
    REJECTED_PREMISE = "rejected_premise"
    DELEGATED = "delegated"
    NEED_CONTEXT = "need_context"
    ABSTAIN = "abstain"


class ResponseChannel(StrEnum):
    WEB = "web"
    API = "api"


class DecisionState(StrEnum):
    PROPOSED = "proposed"
    COMMITTED = "committed"
    SUPERSEDED = "superseded"


class DecisionBasis(StrEnum):
    UNANIMOUS = "unanimous"
    SINGLE_RESPONDENT = "single_respondent"
    MAJORITY = "majority"
    ASKER_JUDGMENT = "asker_judgment"
    ASKER_OVERRIDE = "asker_override"
    EXPIRED_NO_RESPONSE = "expired_no_response"
    REVISION = "revision"


class DecisionStatementSource(StrEnum):
    OWNER = "owner"
    DETERMINISTIC = "deterministic"
    MODEL_DRAFT = "model_draft"


class DecisionResponseRole(StrEnum):
    DETERMINING = "determining"
    CONTEXT = "context"
