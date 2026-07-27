from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import QuestionPrimitive
from app.domain.events import EventName, emit_event
from app.domain.ports import Clock
from app.models.outcomes import Decision
from app.models.work import Ask, Question, QuestionOption


class LinearIssueTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["linear.issue"]
    team: str
    title: str
    body_template: str


IntegrationTrigger = LinearIssueTrigger
_TRIGGER_ADAPTER = TypeAdapter(IntegrationTrigger)


def dispatch_committed_option_triggers(
    session: Session,
    clock: Clock,
    *,
    ask: Ask,
    question: Question,
    decision: Decision,
    actor_id: UUID | None,
) -> None:
    """Record inert attempts for triggers attached to selected options."""
    if question.primitive == QuestionPrimitive.SELECT_ONE and isinstance(decision.value, str):
        selected_values = [decision.value]
    elif question.primitive == QuestionPrimitive.SELECT_MANY and isinstance(decision.value, list):
        selected_values = [value for value in decision.value if isinstance(value, str)]
    else:
        return

    options = session.scalars(
        select(QuestionOption)
        .where(
            QuestionOption.question_id == question.id,
            QuestionOption.value.in_(selected_values),
        )
        .order_by(QuestionOption.ordinal)
    )
    for option in options:
        for trigger_index, payload in enumerate(option.triggers):
            kind: str
            try:
                trigger = _TRIGGER_ADAPTER.validate_python(payload)
                kind = trigger.kind
                outcome = "stubbed"
            except ValidationError:
                raw_kind = payload.get("kind") if isinstance(payload, dict) else None
                kind = raw_kind if isinstance(raw_kind, str) else "unknown"
                outcome = "invalid"
            emit_event(
                session,
                clock,
                EventName.INTEGRATION_TRIGGER_ATTEMPTED,
                actor_id=actor_id,
                project_id=ask.project_id,
                ask_id=ask.id,
                question_id=question.id,
                data={
                    "schema_version": 1,
                    "decision_id": str(decision.id),
                    "option_value": option.value,
                    "trigger_index": trigger_index,
                    "kind": kind,
                    "outcome": outcome,
                },
            )
