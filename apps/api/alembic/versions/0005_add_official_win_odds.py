"""Store official live win odds.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    race_columns = {column["name"] for column in inspector.get_columns("races", schema="core")}
    for name in ("official_win_odds_checked_at", "official_win_odds_fetched_at"):
        if name not in race_columns:
            op.add_column(
                "races",
                sa.Column(name, sa.DateTime(timezone=True), nullable=True),
                schema="core",
            )

    race_indexes = {index["name"] for index in inspector.get_indexes("races", schema="core")}
    if "ix_races_official_win_odds_due" not in race_indexes:
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

    if "win_odds_observations" not in inspector.get_table_names(schema="core"):
        op.create_table(
            "win_odds_observations",
            sa.Column("id", sa.BigInteger(), nullable=False),
            sa.Column("race_entry_id", sa.BigInteger(), nullable=False),
            sa.Column("win_odds", sa.Numeric(8, 1), nullable=False),
            sa.Column("popularity_rank", sa.SmallInteger(), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_payload", sa.JSON(), nullable=False),
            sa.CheckConstraint("win_odds > 0"),
            sa.CheckConstraint("popularity_rank BETWEEN 1 AND 6"),
            sa.ForeignKeyConstraint(
                ["race_entry_id"],
                ["core.race_entries.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("race_entry_id", "observed_at"),
            schema="core",
        )
        op.create_index(
            "ix_win_odds_entry_latest",
            "win_odds_observations",
            ["race_entry_id", "observed_at"],
            schema="core",
        )


def downgrade() -> None:
    op.drop_table("win_odds_observations", schema="core")
    op.drop_index(
        "ix_races_official_win_odds_due",
        table_name="races",
        schema="core",
    )
    op.drop_column("races", "official_win_odds_fetched_at", schema="core")
    op.drop_column("races", "official_win_odds_checked_at", schema="core")
