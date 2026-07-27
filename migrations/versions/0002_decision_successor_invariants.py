"""Enforce Decision successor invariants.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "decision_no_self_supersession",
        "decision",
        "supersedes_decision_id IS NULL OR supersedes_decision_id <> id",
    )
    op.create_index(
        "decision_one_successor",
        "decision",
        ["supersedes_decision_id"],
        unique=True,
        postgresql_where="supersedes_decision_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("decision_one_successor", table_name="decision")
    op.drop_constraint("decision_no_self_supersession", "decision", type_="check")
