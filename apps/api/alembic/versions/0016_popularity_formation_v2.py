"""Switch popularity formation to v2 (skip races where lane 1 is not the favorite).

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

strategies = sa.table(
    "lab_strategies",
    sa.column("code", sa.String()),
    sa.column("version", sa.String()),
    sa.column("name", sa.String()),
    sa.column("description", sa.Text()),
    sa.column("config", sa.JSON()),
    sa.column("active", sa.Boolean()),
    schema="analytics",
)


def _set_active(version: str, active: bool) -> None:
    op.execute(
        sa.update(strategies)
        .where(strategies.c.code == "popularity_formation", strategies.c.version == version)
        .values(active=active)
    )


def upgrade() -> None:
    op.execute(
        insert(strategies)
        .values(
            code="popularity_formation",
            version="2",
            name="人気フォーメーション(1号艇1番人気のみ)",
            description=(
                "現行買い目が作成され、1号艇が1番人気のレースで、1号艇1着固定・"
                "①2着4・5番人気→3着2・3番人気、②2着2・3番人気→3着4・5番人気の8点を記録します。"
                "6号艇が注目艇なら5番人気を6号艇に差し替えます。"
            ),
            config={"unit_stake_yen": 100, "require_lane_one_favorite": True},
            active=True,
        )
        .on_conflict_do_nothing(index_elements=["code", "version"])
    )
    # v1 の記録は残し、新規の予想は v2 だけで作る(停止済みの v2 行が残っていても有効化)
    _set_active("2", True)
    _set_active("1", False)


def downgrade() -> None:
    _set_active("1", True)
    op.execute(
        sa.text(
            "DELETE FROM analytics.lab_strategies "
            "WHERE code = 'popularity_formation' AND version = '2' "
            "AND NOT EXISTS (SELECT 1 FROM analytics.lab_predictions p "
            "WHERE p.strategy_id = analytics.lab_strategies.id)"
        )
    )
    _set_active("2", False)
