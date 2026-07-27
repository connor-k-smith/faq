from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.domain.events import EventName, emit_event
from app.models.outcomes import Event
from app.models.session import get_engine
from tests.fakes import FixedClock

pytestmark = pytest.mark.integration


def test_event_is_committed_with_its_callers_transaction() -> None:
    clock = FixedClock(datetime(2026, 7, 25, 17, 0, tzinfo=UTC))
    engine = get_engine()

    with Session(engine) as session, session.begin():
        session.execute(delete(Event).where(Event.type == EventName.ASK_CREATED.value))
        event = emit_event(session, clock, EventName.ASK_CREATED, data={"title": "Atlas"})
        session.flush()
        event_id = event.id

    with Session(engine) as session:
        persisted = session.get(Event, event_id)
        assert persisted is not None
        assert persisted.at == clock.now()
        assert persisted.data == {"title": "Atlas"}


def test_event_disappears_when_the_transaction_rolls_back() -> None:
    clock = FixedClock(datetime(2026, 7, 25, 17, 0, tzinfo=UTC))
    engine = get_engine()

    with Session(engine) as session:
        emit_event(session, clock, EventName.ASK_SENT, data={"sent": True})
        session.flush()
        session.rollback()

    with Session(engine) as session:
        count = session.scalar(
            select(func.count()).select_from(Event).where(Event.type == EventName.ASK_SENT.value)
        )
        assert count == 0
