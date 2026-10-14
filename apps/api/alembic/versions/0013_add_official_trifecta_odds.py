"""Store official trifecta odds and fetch state.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "races",
        sa.Column(
            "official_trifecta_odds_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="core",
    )
    op.add_column(
        "races",
        sa.Column(
            "official_trifecta_odds_fetched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="core",
    )
    op.drop_index(
        "ix_races_official_win_odds_due",
        table_name="races",
        schema="core",
    )
    op.create_index(
        "ix_races_official_trifecta_odds_due",
        "races",
        [
            "race_date",
            "scheduled_at",
            "official_trifecta_odds_checked_at",
            "official_trifecta_odds_fetched_at",
        ],
        schema="core",
    )
    op.create_table(
        "trifecta_odds_observations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("race_id", sa.UUID(), nullable=False),
        sa.Column("first_lane", sa.SmallInteger(), nullable=False),
        sa.Column("second_lane", sa.SmallInteger(), nullable=False),
        sa.Column("third_lane", sa.SmallInteger(), nullable=False),
        sa.Column("odds", sa.Numeric(precision=8, scale=1), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.CheckConstraint("first_lane BETWEEN 1 AND 6"),
        sa.CheckConstraint("second_lane BETWEEN 1 AND 6"),
        sa.CheckConstraint("third_lane BETWEEN 1 AND 6"),
        sa.CheckConstraint(
            "first_lane <> second_lane "
            "AND first_lane <> third_lane "
            "AND second_lane <> third_lane"
        ),
        sa.CheckConstraint("odds > 0"),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["core.races.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "race_id",
            "first_lane",
            "second_lane",
            "third_lane",
            "observed_at",
        ),
        schema="core",
    )
    op.create_index(
        "ix_trifecta_odds_race_latest",
        "trifecta_odds_observations",
        ["race_id", "observed_at"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trifecta_odds_race_latest",
        table_name="trifecta_odds_observations",
        schema="core",
    )
    op.drop_table("trifecta_odds_observations", schema="core")
    op.drop_index(
        "ix_races_official_trifecta_odds_due",
        table_name="races",
        schema="core",
    )
    op.create_index(
        "ix_races_official_win_odds_due",
        "races",
        [
            "race_date",
            "scheduled_at",
            "official_win_odds_checked_at",
            "official_win_odds_fetched_at",
        ],
        schema="core",
    )
    op.drop_column(
        "races",
        "official_trifecta_odds_fetched_at",
        schema="core",
    )
    op.drop_column(
        "races",
        "official_trifecta_odds_checked_at",
        schema="core",
    )
