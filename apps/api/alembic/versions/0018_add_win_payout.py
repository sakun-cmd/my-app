"""Store official win (単勝) result: winning lane and payout per 100 yen.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("race_results", schema="core")}
    definitions = {
        "win_lane": sa.SmallInteger(),
        "win_payout_yen": sa.Integer(),
    }
    for name, column_type in definitions.items():
        if name not in columns:
            op.add_column(
                "race_results",
                sa.Column(name, column_type, nullable=True),
                schema="core",
            )


def downgrade() -> None:
    for name in ("win_payout_yen", "win_lane"):
        op.drop_column("race_results", name, schema="core")
