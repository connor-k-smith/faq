from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import (
    DecisionBasis,
    DecisionResponseRole,
    DecisionState,
    DecisionStatementSource,
    ResponseChannel,
    ResponseDisposition,
)
from app.models.base import Base
from app.models.types import database_enum


class Response(Base):
    __tablename__ = "response"
    __table_args__ = (
        UniqueConstraint("assignment_id", "version"),
        UniqueConstraint("assignment_id", "submission_id"),
        UniqueConstraint("id", "assignment_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignment.id", ondelete="CASCADE"))
    submission_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    version: Mapped[int]
    disposition: Mapped[ResponseDisposition] = mapped_column(
        database_enum(ResponseDisposition, "response_disposition")
    )
    value: Mapped[object | None] = mapped_column(JSONB)
    comment: Mapped[str | None]
    delegated_to_actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("actor.id"))
    answered_via: Mapped[ResponseChannel] = mapped_column(
        database_enum(ResponseChannel, "response_channel")
    )
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB)
    search_tsv: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(value::text,'') || ' ' || coalesce(comment,''))",
            persisted=True,
        ),
    )
    created_at: Mapped[datetime]


class Decision(Base):
    __tablename__ = "decision"
    __table_args__ = (
        UniqueConstraint("id", "project_id"),
        UniqueConstraint("id", "ask_id", "question_id", "project_id"),
        ForeignKeyConstraint(
            ["ask_id", "question_id", "project_id"],
            ["ask_question.ask_id", "ask_question.question_id", "ask_question.project_id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "decided_by"],
            ["membership.project_id", "membership.actor_id"],
        ),
        ForeignKeyConstraint(
            ["supersedes_decision_id", "project_id"],
            ["decision.id", "decision.project_id"],
        ),
        CheckConstraint(
            "state <> 'committed' OR "
            "(statement IS NOT NULL AND statement_source IN ('owner','deterministic') "
            "AND committed_at IS NOT NULL)",
            name="committed_fields",
        ),
        CheckConstraint(
            "supersedes_decision_id IS NULL OR supersedes_decision_id <> id",
            name="decision_no_self_supersession",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    question_id: Mapped[UUID]
    ask_id: Mapped[UUID]
    state: Mapped[DecisionState] = mapped_column(database_enum(DecisionState, "decision_state"))
    basis: Mapped[DecisionBasis] = mapped_column(database_enum(DecisionBasis, "decision_basis"))
    value: Mapped[object | None] = mapped_column(JSONB)
    statement: Mapped[str | None]
    statement_source: Mapped[DecisionStatementSource | None] = mapped_column(
        database_enum(DecisionStatementSource, "decision_statement_source")
    )
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("actor.id"))
    supersedes_decision_id: Mapped[UUID | None]
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB)
    shared_with_recipients_at: Mapped[datetime | None]
    search_tsv: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(statement,''))", persisted=True),
    )
    committed_at: Mapped[datetime | None]
    created_at: Mapped[datetime]


class DecisionResponse(Base):
    __tablename__ = "decision_response"
    __table_args__ = (
        ForeignKeyConstraint(
            ["decision_id", "ask_id", "question_id", "project_id"],
            ["decision.id", "decision.ask_id", "decision.question_id", "decision.project_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["response_id", "assignment_id"], ["response.id", "response.assignment_id"]
        ),
        ForeignKeyConstraint(
            ["assignment_id", "ask_id", "question_id", "project_id"],
            [
                "assignment.id",
                "assignment.ask_id",
                "assignment.question_id",
                "assignment.project_id",
            ],
        ),
    )

    decision_id: Mapped[UUID] = mapped_column(primary_key=True)
    response_id: Mapped[UUID] = mapped_column(primary_key=True)
    assignment_id: Mapped[UUID]
    project_id: Mapped[UUID]
    ask_id: Mapped[UUID]
    question_id: Mapped[UUID]
    role: Mapped[DecisionResponseRole] = mapped_column(
        database_enum(DecisionResponseRole, "decision_response_role")
    )


class Event(Base):
    __tablename__ = "event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime]
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("project.id", ondelete="SET NULL"))
    ask_id: Mapped[UUID | None] = mapped_column(ForeignKey("ask.id", ondelete="SET NULL"))
    question_id: Mapped[UUID | None] = mapped_column(ForeignKey("question.id", ondelete="SET NULL"))
    assignment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assignment.id", ondelete="SET NULL")
    )
    ask_recipient_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ask_recipient.id", ondelete="SET NULL")
    )
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("actor.id", ondelete="SET NULL"))
    type: Mapped[str]
    data: Mapped[dict[str, object]] = mapped_column(JSONB)
    ip: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET)
    user_agent: Mapped[str | None]


Index(
    "decision_one_committed_per_question",
    Decision.question_id,
    unique=True,
    postgresql_where=Decision.state == DecisionState.COMMITTED,
)
Index(
    "decision_one_proposed_per_question",
    Decision.question_id,
    unique=True,
    postgresql_where=Decision.state == DecisionState.PROPOSED,
)
Index(
    "decision_project_committed_idx",
    Decision.project_id,
    Decision.committed_at.desc(),
    postgresql_where=Decision.state == DecisionState.COMMITTED,
)
Index("decision_search_idx", Decision.search_tsv, postgresql_using="gin")
Index(
    "decision_one_successor",
    Decision.supersedes_decision_id,
    unique=True,
    postgresql_where=Decision.supersedes_decision_id.is_not(None),
)
Index("response_search_idx", Response.search_tsv, postgresql_using="gin")
Index("response_assignment_version_idx", Response.assignment_id, Response.version.desc())
Index("event_project_at_idx", Event.project_id, Event.at.desc())
Index("event_type_at_idx", Event.type, Event.at.desc())
Index("event_ask_at_idx", Event.ask_id, Event.at.desc())
