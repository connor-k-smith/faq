from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from sqlalchemy.orm import Session

from app.domain.enums import QuestionClosePolicy
from app.domain.responding import _deadline_has_precedence, _update_grace
from app.models.work import Ask, Question
from tests.fakes import FixedClock


class ScalarSession:
    def __init__(self, values: list[int]) -> None:
        self.values = iter(values)

    def scalar(self, _statement: object) -> int:
        return next(self.values)


def test_all_responded_grace_starts_and_resets_from_the_test_clock() -> None:
    question = Question()
    question.id = uuid4()
    question.close_policy = QuestionClosePolicy.EITHER
    ask = Ask()
    ask.id = uuid4()
    clock = FixedClock(datetime(2026, 7, 25, 12, 0, tzinfo=UTC))

    _update_grace(cast(Session, ScalarSession([0, 1])), clock, ask, question, timedelta(minutes=15))
    assert question.close_eligible_at == datetime(2026, 7, 25, 12, 15, tzinfo=UTC)

    clock.instant += timedelta(minutes=10)
    _update_grace(cast(Session, ScalarSession([0, 1])), clock, ask, question, timedelta(minutes=15))
    assert question.close_eligible_at == datetime(2026, 7, 25, 12, 25, tzinfo=UTC)


def test_grace_is_cleared_while_an_assignment_is_unresolved_or_policy_is_deadline() -> None:
    question = Question()
    question.id = uuid4()
    question.close_policy = QuestionClosePolicy.ALL_RESPONDED
    question.close_eligible_at = datetime(2026, 7, 25, 12, 15, tzinfo=UTC)
    ask = Ask()
    ask.id = uuid4()
    clock = FixedClock(datetime(2026, 7, 25, 12, 0, tzinfo=UTC))

    _update_grace(cast(Session, ScalarSession([1, 1])), clock, ask, question, timedelta(minutes=15))
    assert question.close_eligible_at is None

    question.close_policy = QuestionClosePolicy.DEADLINE
    ask.deadline = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    question.close_eligible_at = datetime(2026, 7, 25, 12, 15, tzinfo=UTC)
    _update_grace(cast(Session, ScalarSession([])), clock, ask, question, timedelta(minutes=15))
    assert question.close_eligible_at is None


def test_deadline_wins_over_active_grace_only_for_deadline_capable_policies() -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    ask = Ask()
    ask.deadline = now
    question = Question()
    question.close_eligible_at = now + timedelta(minutes=10)

    question.close_policy = QuestionClosePolicy.EITHER
    assert _deadline_has_precedence(ask, question, now) is True
    question.close_policy = QuestionClosePolicy.DEADLINE
    assert _deadline_has_precedence(ask, question, now) is True
    question.close_policy = QuestionClosePolicy.ALL_RESPONDED
    assert _deadline_has_precedence(ask, question, now) is False
