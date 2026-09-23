"""Track Boatcast lap exhibition retrieval.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("races", schema="core")}
    for name in ("boatcast_lap_checked_at", "boatcast_lap_fetched_at"):
        if name not in columns:
            op.add_column(
                "races",
                sa.Column(name, sa.DateTime(timezone=True), nullable=True),
                schema="core",
            )

    indexes = {index["name"] for index in inspector.get_indexes("races", schema="core")}
    if "ix_races_boatcast_lap_due" not in indexes:
        op.create_index(
            "ix_races_boatcast_lap_due",
            "races",
            [
                "race_date",
                "scheduled_at",
                "boatcast_lap_checked_at",
                "boatcast_lap_fetched_at",
            ],
            schema="core",
        )


def downgrade() -> None:
    op.drop_index(
        "ix_races_boatcast_lap_due",
        table_name="races",
        schema="core",
    )
    op.drop_column("races", "boatcast_lap_fetched_at", schema="core")
    op.drop_column("races", "boatcast_lap_checked_at", schema="core")
