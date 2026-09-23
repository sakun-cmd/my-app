"""Track official live result retrieval.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    race_columns = {column["name"] for column in inspector.get_columns("races", schema="core")}
    if "official_result_checked_at" not in race_columns:
        op.add_column(
            "races",
            sa.Column(
                "official_result_checked_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            schema="core",
        )

    result_columns = {
        column["name"] for column in inspector.get_columns("race_results", schema="core")
    }
    if "source" not in result_columns:
        op.add_column(
            "race_results",
            sa.Column("source", sa.String(length=40), nullable=True),
            schema="core",
        )

    race_indexes = {index["name"] for index in inspector.get_indexes("races", schema="core")}
    if "ix_races_official_result_due" not in race_indexes:
        op.create_index(
            "ix_races_official_result_due",
            "races",
            ["race_date", "scheduled_at", "official_result_checked_at"],
            schema="core",
        )


def downgrade() -> None:
    op.drop_index("ix_races_official_result_due", table_name="races", schema="core")
    op.drop_column("race_results", "source", schema="core")
    op.drop_column("races", "official_result_checked_at", schema="core")
