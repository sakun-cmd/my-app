"""Track official live exhibition retrieval.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("races", schema="core")}
    for name in ("official_exhibition_checked_at", "official_exhibition_fetched_at"):
        if name not in columns:
            op.add_column(
                "races",
                sa.Column(name, sa.DateTime(timezone=True), nullable=True),
                schema="core",
            )

    indexes = {index["name"] for index in inspector.get_indexes("races", schema="core")}
    if "ix_races_official_exhibition_due" not in indexes:
        op.create_index(
            "ix_races_official_exhibition_due",
            "races",
            [
                "race_date",
                "scheduled_at",
                "official_exhibition_checked_at",
                "official_exhibition_fetched_at",
            ],
            schema="core",
        )


def downgrade() -> None:
    op.drop_index(
        "ix_races_official_exhibition_due",
        table_name="races",
        schema="core",
    )
    op.drop_column("races", "official_exhibition_fetched_at", schema="core")
    op.drop_column("races", "official_exhibition_checked_at", schema="core")
