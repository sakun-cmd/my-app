"""Store official place (複勝) result: the two boats and their payouts per 100 yen.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("race_results", schema="core")}
    definitions = {
        "place1_lane": sa.SmallInteger(),
        "place1_payout_yen": sa.Integer(),
        "place2_lane": sa.SmallInteger(),
        "place2_payout_yen": sa.Integer(),
    }
    for name, column_type in definitions.items():
        if name not in columns:
            op.add_column(
                "race_results",
                sa.Column(name, column_type, nullable=True),
                schema="core",
            )


def downgrade() -> None:
    for name in ("place2_payout_yen", "place2_lane", "place1_payout_yen", "place1_lane"):
        op.drop_column("race_results", name, schema="core")
