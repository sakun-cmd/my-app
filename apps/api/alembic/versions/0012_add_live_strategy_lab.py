"""Add immutable LIVE strategy lab predictions and settlements.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lab_strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version"),
        schema="analytics",
    )
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
    op.bulk_insert(
        strategies,
        [
            {
                "code": "current",
                "version": "1",
                "name": "現行買い目",
                "description": "現在の1号艇固定買い目を変更せず記録します。",
                "config": {"unit_stake_yen": 100},
                "active": True,
            },
            {
                "code": "skip_single_likely",
                "version": "1",
                "name": "単独注目艇を見送り",
                "description": (
                    "注目艇が1艇だけのレースを見送り、その他は現行買い目を使います。"
                ),
                "config": {"unit_stake_yen": 100},
                "active": True,
            },
            {
                "code": "recommended_threat_box",
                "version": "1",
                "name": "おすすめ艇兼強い脅威3艇BOX",
                "description": (
                    "おすすめ艇と6点以上の強い脅威艇が一致した場合だけ3艇BOXを記録します。"
                ),
                "config": {"unit_stake_yen": 100, "threat_threshold": 6},
                "active": True,
            },
            {
                "code": "strong_threat_top2_box",
                "version": "1",
                "name": "強い脅威上位2艇BOX",
                "description": (
                    "6点以上の強い脅威がある場合、"
                    "1号艇と脅威得点上位2艇の3艇BOXを記録します。"
                ),
                "config": {"unit_stake_yen": 100, "threat_threshold": 6},
                "active": True,
            },
        ],
    )

    op.create_table(
        "lab_predictions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("race_id", sa.UUID(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("data_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('ready', 'skipped')"),
        sa.ForeignKeyConstraint(
            ["race_id"], ["core.races.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["analytics.lab_strategies.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("race_id", "strategy_id"),
        schema="analytics",
    )
    op.create_index(
        "ix_lab_predictions_created",
        "lab_predictions",
        ["created_at"],
        schema="analytics",
    )
    op.create_table(
        "lab_tickets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("prediction_id", sa.UUID(), nullable=False),
        sa.Column("first_lane", sa.SmallInteger(), nullable=False),
        sa.Column("second_lane", sa.SmallInteger(), nullable=False),
        sa.Column("third_lane", sa.SmallInteger(), nullable=False),
        sa.Column("stake_yen", sa.Integer(), nullable=False),
        sa.CheckConstraint("first_lane BETWEEN 1 AND 6"),
        sa.CheckConstraint("second_lane BETWEEN 1 AND 6"),
        sa.CheckConstraint("third_lane BETWEEN 1 AND 6"),
        sa.CheckConstraint(
            "first_lane <> second_lane "
            "AND first_lane <> third_lane "
            "AND second_lane <> third_lane"
        ),
        sa.CheckConstraint("stake_yen > 0"),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["analytics.lab_predictions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "prediction_id",
            "first_lane",
            "second_lane",
            "third_lane",
        ),
        schema="analytics",
    )
    op.create_table(
        "lab_settlements",
        sa.Column("prediction_id", sa.UUID(), nullable=False),
        sa.Column("result_finalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("winning_combination", sa.String(length=8), nullable=True),
        sa.Column("trifecta_payout_yen", sa.Integer(), nullable=True),
        sa.Column("refunded", sa.Boolean(), nullable=False),
        sa.Column("hit", sa.Boolean(), nullable=True),
        sa.Column("stake_yen", sa.Integer(), nullable=False),
        sa.Column("returned_yen", sa.Integer(), nullable=False),
        sa.Column("profit_yen", sa.Integer(), nullable=False),
        sa.Column(
            "settled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("stake_yen >= 0"),
        sa.CheckConstraint("returned_yen >= 0"),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["analytics.lab_predictions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("prediction_id"),
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_table("lab_settlements", schema="analytics")
    op.drop_table("lab_tickets", schema="analytics")
    op.drop_index(
        "ix_lab_predictions_created",
        table_name="lab_predictions",
        schema="analytics",
    )
    op.drop_table("lab_predictions", schema="analytics")
    op.drop_table("lab_strategies", schema="analytics")
