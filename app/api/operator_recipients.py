from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.domain.enums import AssignmentState
from app.domain.events import EventName, emit_event
from app.domain.ports import SystemClock
from app.models.work import AskRecipient, Assignment
from app.operator_identity import OperatorPrincipal

router = APIRouter(prefix="/admin/ask-recipients", tags=["operator"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]


class OperatorRecipient(BaseModel):
    id: UUID
    ask_id: UUID
    display_name: str
    revoked: bool
    session_version: int


@router.get("/{recipient_id}", response_model=OperatorRecipient)
def get_recipient(recipient_id: UUID, session: DatabaseSession) -> OperatorRecipient:
    recipient = session.get(AskRecipient, recipient_id)
    if recipient is None:
        raise HTTPException(status_code=404, detail="recipient not found")
    return _dto(recipient)


@router.post("/{recipient_id}/revoke", response_model=OperatorRecipient)
def emergency_revoke(
    recipient_id: UUID, session: DatabaseSession, principal: OperatorPrincipal
) -> OperatorRecipient:
    recipient = session.scalar(
        select(AskRecipient).where(AskRecipient.id == recipient_id).with_for_update()
    )
    if recipient is None:
        raise HTTPException(status_code=404, detail="recipient not found")
    if recipient.revoked_at is None:
        recipient.revoked_at = SystemClock().now()
        recipient.session_version += 1
        assignments = list(
            session.scalars(
                select(Assignment).where(
                    Assignment.ask_recipient_id == recipient.id,
                    Assignment.state.in_([AssignmentState.PENDING, AssignmentState.BLOCKED]),
                )
            )
        )
        for assignment in assignments:
            assignment.state = AssignmentState.WITHDRAWN
        emit_event(
            session,
            SystemClock(),
            EventName.RECIPIENT_REVOKED,
            project_id=recipient.project_id,
            ask_id=recipient.ask_id,
            ask_recipient_id=recipient.id,
            data={"source": "operator_emergency", "operator": principal.email},
        )
        session.commit()
    return _dto(recipient)


def _dto(recipient: AskRecipient) -> OperatorRecipient:
    return OperatorRecipient(
        id=recipient.id,
        ask_id=recipient.ask_id,
        display_name=recipient.display_name,
        revoked=recipient.revoked_at is not None,
        session_version=recipient.session_version,
    )
