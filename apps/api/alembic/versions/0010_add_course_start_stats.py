"""Add derived racer course start statistics.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "racer_course_start_stats",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("racer_registration_number", sa.String(length=16), nullable=False),
        sa.Column("course_no", sa.SmallInteger(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("starts", sa.Integer(), nullable=False),
        sa.Column("average_start_timing", sa.Numeric(precision=5, scale=3), nullable=True),
        sa.Column("average_start_rank", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("top3_finishes", sa.Integer(), nullable=False),
        sa.Column("top3_rate", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("history_from", sa.Date(), nullable=False),
        sa.Column("history_through", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("course_no BETWEEN 1 AND 6"),
        sa.CheckConstraint("starts >= 0"),
        sa.CheckConstraint("top3_finishes >= 0 AND top3_finishes <= starts"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "racer_registration_number",
            "course_no",
            "snapshot_date",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_course_start_stats_snapshot",
        "racer_course_start_stats",
        ["snapshot_date"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_course_start_stats_snapshot",
        table_name="racer_course_start_stats",
        schema="analytics",
    )
    op.drop_table("racer_course_start_stats", schema="analytics")
