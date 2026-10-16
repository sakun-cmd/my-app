"""Make official odds imports idempotent across concurrent workers.

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM core.trifecta_odds_observations AS older
        USING core.trifecta_odds_observations AS newer
        WHERE older.race_id = newer.race_id
          AND older.first_lane = newer.first_lane
          AND older.second_lane = newer.second_lane
          AND older.third_lane = newer.third_lane
          AND (
            older.observed_at < newer.observed_at
            OR (older.observed_at = newer.observed_at AND older.id < newer.id)
          )
        """
    )
    op.drop_constraint(
        "trifecta_odds_observations_race_id_first_lane_second_lane_t_key",
        "trifecta_odds_observations",
        schema="core",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_trifecta_odds_race_combination",
        "trifecta_odds_observations",
        ["race_id", "first_lane", "second_lane", "third_lane"],
        schema="core",
    )

    op.execute(
        """
        DELETE FROM core.win_odds_observations AS older
        USING core.win_odds_observations AS newer
        WHERE older.race_entry_id = newer.race_entry_id
          AND (
            older.observed_at < newer.observed_at
            OR (older.observed_at = newer.observed_at AND older.id < newer.id)
          )
        """
    )
    op.drop_constraint(
        "win_odds_observations_race_entry_id_observed_at_key",
        "win_odds_observations",
        schema="core",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_win_odds_entry",
        "win_odds_observations",
        ["race_entry_id"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_win_odds_entry",
        "win_odds_observations",
        schema="core",
        type_="unique",
    )
    op.create_unique_constraint(
        "win_odds_observations_race_entry_id_observed_at_key",
        "win_odds_observations",
        ["race_entry_id", "observed_at"],
        schema="core",
    )
    op.drop_constraint(
        "uq_trifecta_odds_race_combination",
        "trifecta_odds_observations",
        schema="core",
        type_="unique",
    )
    op.create_unique_constraint(
        "trifecta_odds_observations_race_id_first_lane_second_lane_t_key",
        "trifecta_odds_observations",
        [
            "race_id",
            "first_lane",
            "second_lane",
            "third_lane",
            "observed_at",
        ],
        schema="core",
    )
