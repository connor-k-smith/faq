from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import AskStatus, QuestionClosePolicy, QuestionState
from app.domain.ports import Clock
from app.domain.settlement import settle_question_locked
from app.jobs.metrics import MetricsSink
from app.models.work import Ask, AskQuestion, Question

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TickSummary:
    run_id: UUID
    batches: int
    examined: int
    settled: int
    has_more: bool


def _due_query(clock: Clock) -> Select[tuple[UUID]]:
    now = clock.now()
    deadline_due = and_(
        Ask.deadline.is_not(None),
        Ask.deadline <= now,
        Question.close_policy.in_((QuestionClosePolicy.DEADLINE, QuestionClosePolicy.EITHER)),
    )
    grace_due = and_(
        Question.close_eligible_at.is_not(None),
        Question.close_eligible_at <= now,
        or_(
            Question.close_policy != QuestionClosePolicy.DEADLINE,
            Ask.deadline.is_(None),
        ),
    )
    return (
        select(Question.id)
        .join(AskQuestion, AskQuestion.question_id == Question.id)
        .join(Ask, Ask.id == AskQuestion.ask_id)
        .where(
            Question.state == QuestionState.OPEN,
            Ask.status == AskStatus.SENT,
            AskQuestion.superseded_at.is_(None),
            or_(deadline_due, grace_due),
        )
        .order_by(Question.id)
    )


def run_tick(
    sessions: sessionmaker[Session],
    clock: Clock,
    metrics: MetricsSink,
    *,
    run_id: UUID,
    batch_size: int,
    max_batches: int,
) -> TickSummary:
    batches = examined = settled = 0
    for _ in range(max_batches):
        with sessions() as session, session.begin():
            ids = list(
                session.scalars(
                    _due_query(clock)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True, of=Question)
                )
            )
            if not ids:
                break
            batches += 1
            examined += len(ids)
            batch_settled = 0
            for question_id in ids:
                result = settle_question_locked(
                    session, clock, question_id, trigger="scheduler", run_id=run_id
                )
                settled += int(result.settled)
                batch_settled += int(result.settled)
        metrics.increment("jobs.questions_examined", len(ids))
        metrics.increment("jobs.questions_settled", batch_settled)
        logger.info(
            "jobs_tick_batch",
            run_id=str(run_id),
            batch=batches,
            examined=len(ids),
        )
        if len(ids) < batch_size:
            break
    with sessions() as session:
        has_more = session.scalar(_due_query(clock).limit(1)) is not None
    metrics.increment("jobs.ticks")
    logger.info(
        "jobs_tick_complete",
        run_id=str(run_id),
        batches=batches,
        examined=examined,
        settled=settled,
        has_more=has_more,
    )
    return TickSummary(run_id, batches, examined, settled, has_more)
