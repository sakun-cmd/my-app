"""Store official trifecta result details.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("race_results", schema="core")}
    definitions = {
        "trifecta_combination": sa.String(length=8),
        "trifecta_payout_yen": sa.Integer(),
        "trifecta_popularity_rank": sa.SmallInteger(),
    }
    for name, column_type in definitions.items():
        if name not in columns:
            op.add_column(
                "race_results",
                sa.Column(name, column_type, nullable=True),
                schema="core",
            )


def downgrade() -> None:
    for name in (
        "trifecta_popularity_rank",
        "trifecta_payout_yen",
        "trifecta_combination",
    ):
        op.drop_column("race_results", name, schema="core")
