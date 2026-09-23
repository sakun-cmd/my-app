from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from boat_analysis.services.daily_excel import (
    _flow_columns,
    build_daily_workbook,
    generate_due_daily_excel,
)


def _race_with_result(**overrides: object) -> SimpleNamespace:
    result = {
        "winning_technique": "逃げ",
        "trifecta_combination": "2-1-3",
        "trifecta_payout_yen": 1830,
        "trifecta_refunded": False,
        "finalized_at": datetime(2026, 9, 21, 20, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    }
    result.update(overrides)
    return SimpleNamespace(result=SimpleNamespace(**result))


_FLOW = {"status": "pass", "tickets": [{"combination": [1, 2, 3]}], "steps": []}


@pytest.mark.parametrize("marker", ["中止", "不成立"])
def test_cancelled_or_void_race_is_refunded_not_a_loss(marker: str) -> None:
    race = _race_with_result(
        winning_technique=marker,
        trifecta_combination=None,
        trifecta_payout_yen=None,
    )

    columns = _flow_columns(_FLOW, race)

    assert columns["的中判定"] == "返還"
    assert columns["投資額_各100円"] == 100
    assert columns["払戻額_100円"] == 100
    assert columns["収支_各100円"] == 0


def test_finished_race_without_hit_is_still_a_loss() -> None:
    columns = _flow_columns(_FLOW, _race_with_result())

    assert columns["的中判定"] == "不的中"
    assert columns["収支_各100円"] == -100


def test_daily_workbook_has_one_race_per_row_and_hit_highlight() -> None:
    rows = [
        {
            "開催日": date(2026, 9, 19),
            "場名": "芦屋",
            "レース": 1,
            "買い目": "1-2-3 / 1-3-2",
            "3連単結果": "1-3-2",
            "的中判定": "的中",
            "払戻額_100円": 1830,
        },
        {
            "開催日": date(2026, 9, 19),
            "場名": "芦屋",
            "レース": 2,
            "買い目": "",
            "3連単結果": "2-1-3",
            "的中判定": "買い目なし",
            "払戻額_100円": 0,
        },
    ]

    workbook = build_daily_workbook(
        rows,
        date(2026, 9, 19),
        datetime(2026, 9, 20, 0, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    sheet = workbook["レース結果"]

    assert sheet.max_row == 3
    assert sheet.max_column == len(rows[0])
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == sheet.dimensions
    assert sheet["A2"].value == "2026-09-19"
    assert sheet["F2"].value == "的中"
    assert sheet["A2"].fill.fgColor.rgb == "00C6EFCE"
    assert workbook["説明"]["B2"].value == "2026-09-19"


def test_daily_export_runs_for_previous_day_after_configured_time() -> None:
    expected = Path("exports/boat-race-daily-20260919.xlsx")
    now = datetime(2026, 9, 20, 0, 30, tzinfo=ZoneInfo("Asia/Tokyo"))

    with (
        patch(
            "boat_analysis.services.daily_excel.daily_excel_path",
            return_value=expected,
        ),
        patch(
            "boat_analysis.services.daily_excel.generate_daily_excel",
            return_value=expected,
        ) as generate,
        patch.object(Path, "exists", return_value=False),
    ):
        assert generate_due_daily_excel(now) == expected

    generate.assert_called_once_with(date(2026, 9, 19))
