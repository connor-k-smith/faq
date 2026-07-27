from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import (
    AskStatus,
    AssignmentOrigin,
    AssignmentState,
    OutcomeEffect,
    QuestionClosePolicy,
    QuestionOpenTo,
    QuestionOrigin,
    QuestionPrimitive,
    QuestionState,
    ResponseVisibility,
)
from app.models.base import Base
from app.models.types import database_enum


class QuestionTemplate(Base):
    __tablename__ = "question_template"

    id: Mapped[str] = mapped_column(primary_key=True)
    primitive: Mapped[QuestionPrimitive] = mapped_column(
        database_enum(QuestionPrimitive, "question_primitive")
    )
    label: Mapped[str]
    description: Mapped[str | None]
    default_options: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    default_validation: Mapped[dict[str, object]] = mapped_column(JSONB)
    requires_consequence: Mapped[bool]
    auto_commit: Mapped[bool]
    default_auto_commit_if: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    default_require_comment_if: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    renderer: Mapped[str]
    builtin: Mapped[bool]


class Question(Base):
    __tablename__ = "question"
    __table_args__ = (
        Index(
            "question_search_idx",
            text(
                "to_tsvector('english'::regconfig, "
                "(COALESCE(prompt, ''::text) || ' '::text) || COALESCE(help_text, ''::text))"
            ),
            postgresql_using="gin",
        ),
        UniqueConstraint("id", "project_id"),
        ForeignKeyConstraint(
            ["project_id", "created_by"],
            ["membership.project_id", "membership.actor_id"],
        ),
        ForeignKeyConstraint(
            ["supersedes_question_id", "project_id"],
            ["question.id", "question.project_id"],
        ),
        ForeignKeyConstraint(
            ["copied_from_question_id", "project_id"],
            ["question.id", "question.project_id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    template_id: Mapped[str] = mapped_column(ForeignKey("question_template.id"))
    primitive: Mapped[QuestionPrimitive] = mapped_column(
        database_enum(QuestionPrimitive, "question_primitive")
    )
    version: Mapped[int]
    supersedes_question_id: Mapped[UUID | None]
    copied_from_question_id: Mapped[UUID | None]
    state: Mapped[QuestionState] = mapped_column(database_enum(QuestionState, "question_state"))
    origin: Mapped[QuestionOrigin] = mapped_column(database_enum(QuestionOrigin, "question_origin"))
    prompt: Mapped[str]
    help_text: Mapped[str | None]
    context_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    open_to: Mapped[QuestionOpenTo] = mapped_column(
        database_enum(QuestionOpenTo, "question_open_to")
    )
    allow_comment: Mapped[bool]
    validation: Mapped[dict[str, object]] = mapped_column(JSONB)
    require_comment_if: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    depends_on: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    response_visibility: Mapped[ResponseVisibility] = mapped_column(
        database_enum(ResponseVisibility, "response_visibility")
    )
    anonymous: Mapped[bool]
    proposed_value: Mapped[object | None] = mapped_column(JSONB)
    proposed_rationale: Mapped[str | None]
    close_policy: Mapped[QuestionClosePolicy] = mapped_column(
        database_enum(QuestionClosePolicy, "question_close_policy")
    )
    auto_commit: Mapped[bool]
    auto_commit_if: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("actor.id"))
    critiques_overridden: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    close_eligible_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    outcome_effect: Mapped[OutcomeEffect | None] = mapped_column(
        database_enum(OutcomeEffect, "outcome_effect")
    )
    outcome_effect_note: Mapped[str | None]
    created_at: Mapped[datetime]


class QuestionOption(Base):
    __tablename__ = "question_option"
    __table_args__ = (UniqueConstraint("question_id", "value"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    question_id: Mapped[UUID] = mapped_column(ForeignKey("question.id", ondelete="CASCADE"))
    ordinal: Mapped[int]
    value: Mapped[str]
    label: Mapped[str]
    consequence: Mapped[str | None]
    triggers: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    search_tsv: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(label,'') || ' ' || coalesce(consequence,''))",
            persisted=True,
        ),
    )


class Ask(Base):
    __tablename__ = "ask"
    __table_args__ = (
        UniqueConstraint("id", "project_id"),
        ForeignKeyConstraint(
            ["project_id", "created_by"],
            ["membership.project_id", "membership.actor_id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "owner_id"],
            ["membership.project_id", "membership.actor_id"],
        ),
        ForeignKeyConstraint(
            ["initiative_id", "project_id"],
            ["initiative.id", "initiative.project_id"],
        ),
        ForeignKeyConstraint(
            ["parent_ask_id", "project_id"],
            ["ask.id", "ask.project_id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    initiative_id: Mapped[UUID]
    parent_ask_id: Mapped[UUID | None]
    title: Mapped[str]
    intro: Mapped[str | None]
    created_by: Mapped[UUID] = mapped_column(ForeignKey("actor.id"))
    deadline: Mapped[datetime | None]
    default_note: Mapped[str | None]
    status: Mapped[AskStatus] = mapped_column(database_enum(AskStatus, "ask_status"))
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actor.id"))
    sent_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    share_message: Mapped[str | None]
    critiques_overridden: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    search_tsv: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title,'') || ' ' || coalesce(intro,''))",
            persisted=True,
        ),
    )
    created_at: Mapped[datetime]


class AskRecipient(Base):
    __tablename__ = "ask_recipient"
    __table_args__ = (
        UniqueConstraint("ask_id", "actor_id"),
        UniqueConstraint("id", "ask_id", "project_id", "actor_id"),
        ForeignKeyConstraint(
            ["ask_id", "project_id"], ["ask.id", "ask.project_id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "(token_hash IS NULL AND token_issued_at IS NULL AND access_expires_at IS NULL) OR "
            "(token_hash IS NOT NULL AND token_issued_at IS NOT NULL "
            "AND access_expires_at IS NOT NULL)",
            name="credential_fields",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    ask_id: Mapped[UUID]
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("actor.id"))
    display_name: Mapped[str]
    token_hash: Mapped[str | None] = mapped_column(unique=True)
    token_issued_at: Mapped[datetime | None]
    session_version: Mapped[int]
    revoked_at: Mapped[datetime | None]
    access_expires_at: Mapped[datetime | None]
    share_marked_sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime]


class AskQuestion(Base):
    __tablename__ = "ask_question"
    __table_args__ = (
        UniqueConstraint("question_id"),
        UniqueConstraint("ask_id", "question_id", "project_id"),
        ForeignKeyConstraint(
            ["ask_id", "project_id"], ["ask.id", "ask.project_id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["question_id", "project_id"],
            ["question.id", "question.project_id"],
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    ask_id: Mapped[UUID] = mapped_column(primary_key=True)
    question_id: Mapped[UUID] = mapped_column(primary_key=True)
    ordinal: Mapped[int]
    superseded_at: Mapped[datetime | None]


class Assignment(Base):
    __tablename__ = "assignment"
    __table_args__ = (
        UniqueConstraint("ask_id", "question_id", "actor_id"),
        UniqueConstraint("id", "ask_id", "question_id", "project_id"),
        ForeignKeyConstraint(
            ["ask_id", "question_id", "project_id"],
            ["ask_question.ask_id", "ask_question.question_id", "ask_question.project_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["ask_recipient_id", "ask_id", "project_id", "actor_id"],
            [
                "ask_recipient.id",
                "ask_recipient.ask_id",
                "ask_recipient.project_id",
                "ask_recipient.actor_id",
            ],
        ),
        ForeignKeyConstraint(["child_ask_id", "project_id"], ["ask.id", "ask.project_id"]),
        CheckConstraint(
            "(origin = 'unsolicited' AND ask_recipient_id IS NULL) OR "
            "(origin <> 'unsolicited' AND ask_recipient_id IS NOT NULL)",
            name="recipient_by_origin",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    ask_id: Mapped[UUID]
    question_id: Mapped[UUID]
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("actor.id"))
    ask_recipient_id: Mapped[UUID | None]
    origin: Mapped[AssignmentOrigin] = mapped_column(
        database_enum(AssignmentOrigin, "assignment_origin")
    )
    state: Mapped[AssignmentState] = mapped_column(
        database_enum(AssignmentState, "assignment_state")
    )
    delegated_to_actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("actor.id"))
    child_ask_id: Mapped[UUID | None]
    created_at: Mapped[datetime]


class AuthoringSession(Base):
    __tablename__ = "authoring_session"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "actor_id"],
            ["membership.project_id", "membership.actor_id"],
        ),
        ForeignKeyConstraint(
            ["ask_id", "project_id"], ["ask.id", "ask.project_id"], ondelete="CASCADE"
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    actor_id: Mapped[UUID]
    ask_id: Mapped[UUID | None]
    conversation_id: Mapped[str | None]
    messages: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


Index(
    "ask_question_active_ordinal",
    AskQuestion.ask_id,
    AskQuestion.ordinal,
    unique=True,
    postgresql_where=AskQuestion.superseded_at.is_(None),
)
Index("assignment_recipient_state_idx", Assignment.ask_recipient_id, Assignment.state)
Index("assignment_actor_state_idx", Assignment.actor_id, Assignment.state)
Index("assignment_ask_question_idx", Assignment.ask_id, Assignment.question_id)
Index(
    "question_close_eligible_idx",
    Question.close_eligible_at,
    postgresql_where=Question.state == QuestionState.OPEN,
)
Index("question_state_policy_idx", Question.state, Question.close_policy)
Index(
    "ask_deadline_idx",
    Ask.deadline,
    postgresql_where=Ask.status == AskStatus.SENT,
)
Index("ask_search_idx", Ask.search_tsv, postgresql_using="gin")
Index("question_option_search_idx", QuestionOption.search_tsv, postgresql_using="gin")
Index("ask_recipient_actor_created_idx", AskRecipient.actor_id, AskRecipient.created_at.desc())
Index("ask_initiative_created_idx", Ask.initiative_id, Ask.created_at.desc())
Index("question_project_state_idx", Question.project_id, Question.state)
