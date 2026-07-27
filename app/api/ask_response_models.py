from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, JsonValue

from app.api.ask_contracts import EvidenceWrite
from app.domain.enums import (
    AskStatus,
    AssignmentOrigin,
    AssignmentState,
    DecisionBasis,
    DecisionState,
    DecisionStatementSource,
    OutcomeEffect,
    QuestionClosePolicy,
    QuestionOpenTo,
    QuestionPrimitive,
    QuestionState,
    ResponseVisibility,
)
from app.domain.integration_triggers import IntegrationTrigger


class ProjectRef(BaseModel):
    id: UUID
    name: str


class InitiativeRef(BaseModel):
    id: UUID
    name: str


class OptionDto(BaseModel):
    id: UUID
    ordinal: int
    value: str
    label: str
    consequence: str | None
    triggers: list[IntegrationTrigger]


class QuestionDto(BaseModel):
    id: UUID
    template_id: str
    primitive: QuestionPrimitive
    version: int
    supersedes_question_id: UUID | None
    copied_from_question_id: UUID | None
    ordinal: int
    prompt: str
    help_text: str | None
    allow_comment: bool
    depends_on: dict[str, object] | None
    options: list[OptionDto]
    critiques_overridden: list[dict[str, object]]
    response_visibility: ResponseVisibility
    close_policy: QuestionClosePolicy
    open_to: QuestionOpenTo


class RecipientDto(BaseModel):
    id: UUID
    actor_id: UUID
    display_name: str
    email: str | None
    created_at: datetime
    credential_active: bool
    share_marked_sent_at: datetime | None
    open_assignments: int
    recent_assignments: int
    recent_asks: int
    window_days: int
    workload_warning: bool


class RecipientPreview(BaseModel):
    recipient_id: UUID
    questions: list[QuestionDto]


class AskAggregate(BaseModel):
    id: UUID
    project_id: UUID
    initiative_id: UUID
    parent_ask_id: UUID | None
    title: str
    intro: str | None
    deadline: datetime | None
    deadline_date: date | None
    owner_timezone: str
    overdue: bool
    default_note: str | None
    status: AskStatus
    owner_id: UUID
    critiques_overridden: list[dict[str, object]]
    created_at: datetime
    read_only: bool
    can_edit_questions: bool
    can_add_questions: bool
    can_add_recipients: bool
    can_create_successor: bool
    project: ProjectRef
    initiative: InitiativeRef
    questions: list[QuestionDto]
    recipients: list[RecipientDto]
    recipient_previews: list[RecipientPreview]


class ShareArtifact(BaseModel):
    recipient_id: UUID
    display_name: str
    url: str
    message: str


class SendResult(BaseModel):
    ask: AskAggregate
    artifacts: list[ShareArtifact]


class RecipientAddResult(BaseModel):
    recipient: RecipientDto
    artifact: ShareArtifact


class ResponseRevisionDto(BaseModel):
    id: UUID
    version: int
    disposition: str
    value: JsonValue
    comment: str | None
    created_at: datetime


class ResultAssignmentDto(BaseModel):
    id: UUID
    recipient_id: UUID | None
    actor_id: UUID
    delegated_to_actor_id: UUID | None
    child_ask_id: UUID | None
    display_name: str
    origin: AssignmentOrigin
    advisory: bool
    late: bool
    state: AssignmentState
    elapsed_seconds: int
    distinct_ip_count: int
    latest_response: ResponseRevisionDto | None
    revisions: list[ResponseRevisionDto]
    response_visible: bool


class ResolutionMetadataDto(BaseModel):
    computed_winner: bool
    computed_value: JsonValue
    computed_basis: DecisionBasis
    eligible_count: int
    substantive_count: int
    quorum_met: bool
    conflict: bool
    vote_counts: dict[str, int]
    proposal_state: DecisionState


class DecisionDto(BaseModel):
    id: UUID
    state: DecisionState
    basis: DecisionBasis
    value: JsonValue
    statement: str | None
    statement_source: DecisionStatementSource | None
    committed_at: datetime | None
    shared_with_recipients_at: datetime | None
    substantive_evidence_count: int
    evidence: list[EvidenceWrite]
    resolution: ResolutionMetadataDto | None
    advisory_disagreement: bool
    supersedes_decision_id: UUID | None
    successor_decision_id: UUID | None
    historical: bool


class ResultQuestionDto(BaseModel):
    id: UUID
    ordinal: int
    prompt: str
    primitive: QuestionPrimitive
    state: QuestionState
    open_to: QuestionOpenTo
    close_policy: QuestionClosePolicy
    can_contribute_advisory: bool
    version: int
    supersedes_question_id: UUID | None
    copied_from_question_id: UUID | None
    overdue: bool
    options: list[OptionDto]
    outcome_effect: OutcomeEffect | None
    outcome_effect_note: str | None
    decision: DecisionDto | None
    assignments: list[ResultAssignmentDto]


class StakeholderQuestionDto(BaseModel):
    question_id: UUID
    assignment_id: UUID


class StakeholderResultDto(BaseModel):
    recipient_id: UUID
    display_name: str
    distinct_ip_count: int
    questions: list[StakeholderQuestionDto]


class AskResults(BaseModel):
    id: UUID
    title: str
    parent_ask_id: UUID | None
    status: AskStatus
    owner_id: UUID
    sent_at: datetime | None
    closed_at: datetime | None
    deadline: datetime | None
    overdue: bool
    elapsed_seconds: int
    can_decide: bool
    questions: list[ResultQuestionDto]
    stakeholders: list[StakeholderResultDto]
