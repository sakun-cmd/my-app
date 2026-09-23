"""Allow zero official win odds.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

OLD_CONSTRAINT = "win_odds_observations_win_odds_check"
NEW_CONSTRAINT = "win_odds_observations_win_odds_check"


def upgrade() -> None:
    op.drop_constraint(OLD_CONSTRAINT, "win_odds_observations", schema="core", type_="check")
    op.create_check_constraint(
        NEW_CONSTRAINT,
        "win_odds_observations",
        "win_odds >= 0",
        schema="core",
    )


def downgrade() -> None:
    op.drop_constraint(NEW_CONSTRAINT, "win_odds_observations", schema="core", type_="check")
    op.create_check_constraint(
        OLD_CONSTRAINT,
        "win_odds_observations",
        "win_odds > 0",
        schema="core",
    )
