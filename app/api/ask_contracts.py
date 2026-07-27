from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

from app.domain.enums import (
    DecisionResponseRole,
    OutcomeEffect,
    QuestionClosePolicy,
    QuestionOpenTo,
    ResponseDisposition,
    ResponseVisibility,
)
from app.domain.integration_triggers import IntegrationTrigger


class AskCreate(BaseModel):
    project_id: UUID
    initiative_id: UUID
    title: str = Field(max_length=500)
    intro: str | None = None
    deadline: date | None = None
    timezone: str | None = None
    default_note: str | None = None


class AskUpdate(BaseModel):
    title: str = Field(max_length=500)
    intro: str | None = None
    deadline: date | None = None
    timezone: str | None = None
    default_note: str | None = None
    critiques_overridden: list[dict[str, object]] = Field(default_factory=list)


class OptionWrite(BaseModel):
    value: str
    label: str
    consequence: str | None = None
    triggers: list[IntegrationTrigger] = Field(default_factory=list)


class QuestionWrite(BaseModel):
    template_id: str
    prompt: str
    help_text: str | None = None
    allow_comment: bool = True
    depends_on: dict[str, object] | None = None
    options: list[OptionWrite] = Field(default_factory=list)
    critiques_overridden: list[dict[str, object]] = Field(default_factory=list)
    response_visibility: ResponseVisibility = ResponseVisibility.AFTER_OWN_RESPONSE
    close_policy: QuestionClosePolicy = QuestionClosePolicy.EITHER
    open_to: QuestionOpenTo = QuestionOpenTo.ASSIGNED_ONLY


class RecipientWrite(BaseModel):
    display_name: str | None = None
    email: str | None = None
    actor_id: UUID | None = None
    question_ids: list[UUID] | None = None
    replacement_deadline: date | None = None
    timezone: str | None = None


class AdvisoryResponseWrite(BaseModel):
    disposition: ResponseDisposition
    value: JsonValue = None
    comment: str | None = None
    submission_id: UUID


class ChecklistWrite(BaseModel):
    sent: bool


class EvidenceWrite(BaseModel):
    response_id: UUID
    role: DecisionResponseRole


class DecisionWrite(BaseModel):
    statement: str
    value: JsonValue = None
    evidence: list[EvidenceWrite] = Field(default_factory=list)
    outcome_effect: OutcomeEffect
    outcome_effect_note: str | None = None
    share_with_recipients: bool = False
    proposal_id: UUID | None = None


class OutcomeEffectWrite(BaseModel):
    outcome_effect: OutcomeEffect
    outcome_effect_note: str | None = None
