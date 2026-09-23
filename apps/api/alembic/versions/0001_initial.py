"""Create core application schemas.

Revision ID: 0001
Revises:
"""

from sqlalchemy import text

from alembic import op
from boat_analysis import models  # noqa: F401
from boat_analysis.database import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for schema in ("core", "analytics", "ops"):
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    Base.metadata.create_all(bind=connection, checkfirst=True)
    connection.execute(
        text(
            """
            INSERT INTO analytics.scoring_profiles (version, name, weights, active)
            VALUES (
                'exhibition-v1',
                '展示基本スコア',
                '{"exhibition_time": 50, "exhibition_start": 30,
                  "course_stability": 10, "data_completeness": 10}'::jsonb,
                true
            )
            ON CONFLICT (version) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    Base.metadata.drop_all(bind=connection, checkfirst=True)
    for schema in ("analytics", "core", "ops"):
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
