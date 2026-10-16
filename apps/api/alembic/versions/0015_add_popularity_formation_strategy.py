"""Add popularity formation strategy and make it the only active LAB strategy.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from alembic import op

revision = "0015"
down_revision = "0014"
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
PREVIOUS_STRATEGIES = (
    "current",
    "skip_single_likely",
    "recommended_threat_box",
    "strong_threat_top2_box",
)


def upgrade() -> None:
    op.execute(
        insert(strategies)
        .values(
            code="popularity_formation",
            version="1",
            name="人気フォーメーション",
            description=(
                "現行買い目が作成されたレースで、1号艇1着固定・"
                "①2着4・5番人気→3着2・3番人気、②2着2・3番人気→3着4・5番人気の8点を記録します。"
                "6号艇が注目艇なら5番人気を6号艇に差し替えます。"
            ),
            config={"unit_stake_yen": 100},
            active=True,
        )
        .on_conflict_do_nothing(index_elements=["code", "version"])
    )
    # 過去に停止済みの行が残っている場合も有効化する
    op.execute(
        sa.update(strategies)
        .where(strategies.c.code == "popularity_formation", strategies.c.version == "1")
        .values(active=True)
    )
    # 人気フォーメーションに一本化する。既存戦略は停止のみで、過去の記録・採点は残す。
    op.execute(
        sa.update(strategies)
        .where(strategies.c.code.in_(PREVIOUS_STRATEGIES))
        .values(active=False)
    )


def downgrade() -> None:
    op.execute(
        sa.update(strategies)
        .where(strategies.c.code.in_(PREVIOUS_STRATEGIES))
        .values(active=True)
    )
    op.execute(
        sa.text(
            "DELETE FROM analytics.lab_strategies "
            "WHERE code = 'popularity_formation' AND version = '1' "
            "AND NOT EXISTS (SELECT 1 FROM analytics.lab_predictions p "
            "WHERE p.strategy_id = analytics.lab_strategies.id)"
        )
    )
    # 記録があり削除できない場合も、旧コードが扱えないよう停止しておく
    op.execute(
        sa.update(strategies)
        .where(strategies.c.code == "popularity_formation", strategies.c.version == "1")
        .values(active=False)
    )
