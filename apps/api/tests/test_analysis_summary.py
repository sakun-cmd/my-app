from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from boat_analysis.routers import analysis


@pytest.mark.parametrize(
    ("refunded", "winning_technique", "expected_hit"),
    [
        (True, "逃げ", None),
        (False, "中止", None),
        (False, "不成立", None),
        (False, "逃げ", True),
    ],
)
def test_two_boat_flow_summary_ignores_refunded_and_no_result_races(
    monkeypatch: pytest.MonkeyPatch,
    refunded: bool,
    winning_technique: str,
    expected_hit: bool | None,
) -> None:
    race_id = uuid4()
    race = SimpleNamespace(
        id=race_id,
        result=SimpleNamespace(
            finalized_at=datetime.now(UTC),
            trifecta_refunded=refunded,
            winning_technique=winning_technique,
            entries=[
                SimpleNamespace(lane=1, finish_position=1),
                SimpleNamespace(lane=2, finish_position=2),
                SimpleNamespace(lane=3, finish_position=3),
            ],
        ),
    )
    db = Mock()
    db.scalars.return_value.all.return_value = [race]
    monkeypatch.setattr(
        analysis,
        "analyze_races_two_boat_flow",
        lambda _races, _db: {
            race_id: {
                "escape_assessment": "likely",
                "tickets": [{"combination": [1, 2, 3]}],
            }
        },
    )

    summaries = analysis.two_boat_flow_summary(date(2026, 10, 1), db)

    assert summaries[0].hit is expected_hit
    assert summaries[0].escape_assessment == "likely"