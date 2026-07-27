"""Create the initial FAQ schema.

Revision ID: 0001
Revises: None
"""

from pathlib import Path

import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = Path(__file__).with_suffix(".sql").read_text()
    op.get_bind().exec_driver_sql(sql)
    op.execute(
        sa.text("INSERT INTO organization (id, name) VALUES (1, :name)").bindparams(
            name=get_settings().organization_name
        )
    )


def downgrade() -> None:
    tables = (
        "event",
        "authoring_session",
        "decision_response",
        "decision",
        "response",
        "assignment",
        "ask_question",
        "ask_recipient",
        "ask",
        "question_option",
        "question",
        "question_template",
        "initiative",
        "membership",
        "project",
        "login_invitation",
        "contact_method",
        "actor",
        "organization",
    )
    for table in tables:
        op.execute(sa.text(f'DROP TABLE "{table}" CASCADE'))

    types = (
        "decision_response_role",
        "decision_statement_source",
        "decision_basis",
        "decision_state",
        "response_channel",
        "response_disposition",
        "assignment_state",
        "assignment_origin",
        "ask_status",
        "outcome_effect",
        "question_origin",
        "question_close_policy",
        "question_state",
        "response_visibility",
        "question_open_to",
        "question_primitive",
        "initiative_kind",
        "contact_kind",
        "organization_role",
        "actor_kind",
    )
    for type_name in types:
        op.execute(sa.text(f'DROP TYPE "{type_name}"'))
