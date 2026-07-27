from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import ActorKind, ContactKind, InitiativeKind, OrganizationRole
from app.models.base import Base
from app.models.types import database_enum


class Organization(Base):
    __tablename__ = "organization"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    name: Mapped[str]
    logo_url: Mapped[str | None]
    primary_domain: Mapped[str | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class Actor(Base):
    __tablename__ = "actor"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    kind: Mapped[ActorKind] = mapped_column(database_enum(ActorKind, "actor_kind"))
    organization_role: Mapped[OrganizationRole] = mapped_column(
        database_enum(OrganizationRole, "organization_role")
    )
    display_name: Mapped[str]
    firebase_uid: Mapped[str | None] = mapped_column(unique=True)
    avatar_url: Mapped[str | None]
    timezone: Mapped[str]
    deleted_at: Mapped[datetime | None]
    created_at: Mapped[datetime]


class ContactMethod(Base):
    __tablename__ = "contact_method"
    __table_args__ = (UniqueConstraint("actor_id", "kind", "value"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("actor.id", ondelete="CASCADE"))
    kind: Mapped[ContactKind] = mapped_column(database_enum(ContactKind, "contact_kind"))
    value: Mapped[str]
    verified_at: Mapped[datetime | None]
    opted_in_at: Mapped[datetime | None]
    priority: Mapped[int]
    quiet_hours: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime]


class LoginInvitation(Base):
    __tablename__ = "login_invitation"
    __table_args__ = (
        CheckConstraint("(accepted_by IS NULL) = (accepted_at IS NULL)", name="acceptance_pair"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    email: Mapped[str]
    invited_by: Mapped[UUID] = mapped_column(ForeignKey("actor.id"))
    accepted_by: Mapped[UUID | None] = mapped_column(ForeignKey("actor.id"))
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    created_at: Mapped[datetime]


class Project(Base):
    __tablename__ = "project"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str]
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text))
    description: Mapped[str | None]
    external_refs: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("actor.id"))
    created_at: Mapped[datetime]
    archived_at: Mapped[datetime | None]


class Membership(Base):
    __tablename__ = "membership"

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("actor.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str | None]
    revoked_at: Mapped[datetime | None]
    created_at: Mapped[datetime]


class Initiative(Base):
    __tablename__ = "initiative"
    __table_args__ = (
        UniqueConstraint("id", "project_id"),
        ForeignKeyConstraint(
            ["project_id", "created_by"],
            ["membership.project_id", "membership.actor_id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    name: Mapped[str]
    kind: Mapped[InitiativeKind] = mapped_column(database_enum(InitiativeKind, "initiative_kind"))
    description: Mapped[str | None]
    external_refs: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("actor.id"))
    created_at: Mapped[datetime]
    archived_at: Mapped[datetime | None]


Index(
    "login_invitation_one_active_per_email",
    func.lower(LoginInvitation.email),
    unique=True,
    postgresql_where=(LoginInvitation.accepted_at.is_(None) & LoginInvitation.revoked_at.is_(None)),
)
Index(
    "initiative_active_name",
    Initiative.project_id,
    func.lower(Initiative.name),
    unique=True,
    postgresql_where=Initiative.archived_at.is_(None),
)
Index("contact_method_actor_idx", ContactMethod.actor_id)
