"""Add venue-specific lap exhibition metrics.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {
        column["name"] for column in inspector.get_columns("exhibition_observations", schema="core")
    }
    for name in (
        "half_lap_time_seconds",
        "lap_time_seconds",
        "cornering_time_seconds",
        "straight_time_seconds",
    ):
        if name not in existing:
            op.add_column(
                "exhibition_observations",
                sa.Column(name, sa.Numeric(6, 3), nullable=True),
                schema="core",
            )
    if "lap_source_payload" not in existing:
        op.add_column(
            "exhibition_observations",
            sa.Column("lap_source_payload", sa.JSON(), nullable=True),
            schema="core",
        )
    op.execute(
        """
        INSERT INTO analytics.scoring_profiles (version, name, weights, active)
        VALUES (
            'exhibition-v2',
            '周回展示統合スコア',
            '{"exhibition_time": 30, "exhibition_start": 20,
              "course_stability": 10, "lap_or_half_lap": 15,
              "cornering": 15, "straight": 10}'::jsonb,
            true
        )
        ON CONFLICT (version) DO UPDATE SET
            name = EXCLUDED.name,
            weights = EXCLUDED.weights,
            active = true
        """
    )
    op.execute(
        "UPDATE analytics.scoring_profiles SET active = false WHERE version <> 'exhibition-v2'"
    )


def downgrade() -> None:
    op.execute("DELETE FROM analytics.scoring_profiles WHERE version = 'exhibition-v2'")
    op.execute(
        "UPDATE analytics.scoring_profiles SET active = true WHERE version = 'exhibition-v1'"
    )
    op.drop_column("exhibition_observations", "lap_source_payload", schema="core")
    for name in (
        "straight_time_seconds",
        "cornering_time_seconds",
        "lap_time_seconds",
        "half_lap_time_seconds",
    ):
        op.drop_column("exhibition_observations", name, schema="core")
