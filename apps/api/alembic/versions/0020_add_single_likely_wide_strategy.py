"""Add a LAB strategy that widens single-likely races to 8 tickets alongside v3.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from alembic import op

revision = "0020"
down_revision = "0019"
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
CODE = "popularity_formation_single_wide"


def upgrade() -> None:
    op.execute(
        insert(strategies)
        .values(
            code=CODE,
            version="1",
            name="v3対象・注目艇1艇は全流し8点",
            description=(
                "人気フォーメーションv3と同じレース(現行買い目あり、公式3連単による"
                "1号艇の1着支持換算値が1.5倍未満)を対象にします。注目艇が1艇のときは"
                "1-注目艇-残り4艇、1-残り4艇-注目艇の8点、2艇のときはv3と同じ8点を記録します。"
            ),
            config={"unit_stake_yen": 100, "max_lane_one_implied_odds": "1.5"},
            active=True,
        )
        .on_conflict_do_nothing(index_elements=["code", "version"])
    )
    # v3 は停止せず並行記録する(停止済みの行が残っていても有効化)
    op.execute(
        sa.update(strategies)
        .where(strategies.c.code == CODE, strategies.c.version == "1")
        .values(active=True)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"DELETE FROM analytics.lab_strategies WHERE code = '{CODE}' AND version = '1' "
            "AND NOT EXISTS (SELECT 1 FROM analytics.lab_predictions p "
            "WHERE p.strategy_id = analytics.lab_strategies.id)"
        )
    )
    op.execute(
        sa.update(strategies)
        .where(strategies.c.code == CODE, strategies.c.version == "1")
        .values(active=False)
    )
