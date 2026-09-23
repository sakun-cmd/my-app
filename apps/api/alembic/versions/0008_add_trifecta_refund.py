"""Track refunded official trifecta results.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("race_results", schema="core")}
    if "trifecta_refunded" not in columns:
        op.add_column(
            "race_results",
            sa.Column(
                "trifecta_refunded",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            schema="core",
        )


def downgrade() -> None:
    op.drop_column("race_results", "trifecta_refunded", schema="core")
