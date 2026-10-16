"""Add idempotent ticket notification tracking.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket_notifications",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("race_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "first_detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("attempts >= 0"),
        sa.CheckConstraint("status IN ('pending', 'sent', 'failed')"),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["core.races.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("race_id", "channel"),
        schema="ops",
    )
    op.create_index(
        "ix_ticket_notifications_retry",
        "ticket_notifications",
        ["status", "last_attempt_at"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ticket_notifications_retry",
        table_name="ticket_notifications",
        schema="ops",
    )
    op.drop_table("ticket_notifications", schema="ops")
