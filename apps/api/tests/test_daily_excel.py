from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from boat_analysis.services.daily_excel import (
    _comparison_row,
    _comparison_summary,
    _flow_columns,
    build_daily_workbook,
    generate_due_daily_excel,
)
from boat_analysis.services.two_boat_flow import FlowBoat


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


def test_unlikely_flow_is_exported_as_warning_without_stake() -> None:
    flow = {
        "status": "review",
        "escape_assessment": "unlikely",
        "tickets": [],
        "steps": [],
    }

    columns = _flow_columns(flow, _race_with_result())

    assert columns["注意喚起"] == "イン逃げ注意（買い目作成なし）"
    assert columns["買い目"] == ""
    assert columns["買い目数"] == 0
    assert columns["投資額_各100円"] == 0
    assert columns["的中判定"] == "買い目なし"


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


def _boat(lane: int, exhibition: str, finish: int | None = None) -> FlowBoat:
    return FlowBoat(
        lane=lane,
        exhibition_time=Decimal(exhibition),
        lap_time=Decimal("37.00"),
        course_avg_start_rank=Decimal("3"),
        course_avg_start_timing=None,
        nationwide_win_rate=None,
        course_top3_rate=None,
        finish_position=finish,
    )


def _comparison_race() -> SimpleNamespace:
    race = _race_with_result(trifecta_combination="1-2-3", trifecta_payout_yen=1200)
    race.race_date = date(2026, 9, 19)
    race.venue_code = "21"
    race.venue = SimpleNamespace(name="芦屋")
    race.race_number = 1
    race.entries = []
    return race


def _live_flow(source_flow: dict, source_boats: list[FlowBoat], live_tickets: list) -> dict:
    return {
        "status": "review",
        "likely_lanes": [2],
        "escape_assessment": "likely",
        "tickets": [{"combination": ticket} for ticket in live_tickets],
        "steps": [],
        "metrics": [
            {
                "lane": 2,
                "exhibition_time": Decimal("6.70"),
                "lap_time": Decimal("37.00"),
                "course_avg_start_rank": source_boats[1].course_avg_start_rank,
            },
            *(
                {
                    "lane": b.lane,
                    "exhibition_time": b.exhibition_time,
                    "lap_time": b.lap_time,
                    "course_avg_start_rank": b.course_avg_start_rank,
                }
                for b in source_boats
                if b.lane != 2
            ),
        ],
        "source_baseline": {
            "flow": source_flow,
            "boats": source_boats,
            "trifecta_odds": {(1, 2, 3): Decimal("15.0"), (1, 3, 2): Decimal("20.0")},
            "winning_combination": (1, 2, 3),
        },
    }


def test_comparison_row_attributes_ticket_difference_to_exhibition_gap() -> None:
    source_boats = [_boat(lane, "6.80", lane) for lane in range(1, 7)]
    source_flow = {
        "status": "pass",
        "likely_lanes": [],
        "escape_assessment": "not_assessed",
        "tickets": [],
    }
    flow = _live_flow(source_flow, source_boats, [[1, 2, 3], [1, 3, 2]])

    row = _comparison_row(_comparison_race(), flow)

    assert row is not None
    assert row["展示差_艇別(実-BT)"] == "2:-0.10"
    assert row["周回差_艇別(実-BT)"] == ""
    assert row["判定一致"] is False
    assert row["買い目一致"] is False
    assert row["実のみ買い目"] == "1-2-3 / 1-3-2"
    assert row["着順一致"] is True
    assert row["BT的中"] is False
    assert row["実的中判定"] == "的中"
    assert row["的中一致"] is False
    assert row["BT収支"] == 0
    assert row["実収支"] == 1000
    assert row["相違要因"] == "展示タイム差"


def test_comparison_row_attributes_decision_difference_to_recalculated_course_stats() -> None:
    source_boats = [_boat(lane, "6.80", lane) for lane in range(1, 7)]
    source_flow = {
        "status": "pass",
        "likely_lanes": [],
        "escape_assessment": "not_assessed",
        "tickets": [],
    }
    flow = _live_flow(source_flow, source_boats, [[1, 2, 3]])
    for metric in flow["metrics"]:
        metric["course_avg_start_rank"] = Decimal("2.50")

    row = _comparison_row(_comparison_race(), flow)

    assert row is not None
    assert row["相違要因"] == "展示タイム差 / コースST再計算差"


def test_comparison_row_flags_payout_difference_when_both_hit() -> None:
    source_boats = [_boat(lane, "6.80", lane) for lane in range(1, 7)]
    tickets = [[1, 2, 3], [1, 3, 2]]
    source_flow = {
        "status": "review",
        "likely_lanes": [2],
        "escape_assessment": "likely",
        "tickets": [{"combination": ticket} for ticket in tickets],
    }
    flow = _live_flow(source_flow, source_boats, tickets)

    row = _comparison_row(_comparison_race(), flow)
    summary = dict(_comparison_summary([row]))

    assert row is not None
    assert row["買い目一致"] is True
    assert row["BT払戻額(元DBオッズ)"] == Decimal("1500")
    assert row["実払戻額(公式払戻)"] == 1200
    assert row["収支差(実-BT)"] == Decimal("-300")
    assert row["相違要因"] == "オッズ・払戻差"
    assert summary["買い目一致"] == "1/1"
    assert summary["相違要因: オッズ・払戻差"] == 1


def test_comparison_row_skips_flow_without_baseline() -> None:
    assert _comparison_row(_comparison_race(), _FLOW) is None


def test_daily_workbook_adds_comparison_sheets() -> None:
    source_boats = [_boat(lane, "6.80", lane) for lane in range(1, 7)]
    source_flow = {"status": "pass", "likely_lanes": [], "tickets": []}
    row = _comparison_row(_comparison_race(), _live_flow(source_flow, source_boats, [[1, 2, 3]]))

    workbook = build_daily_workbook(
        [{"開催日": date(2026, 9, 19), "的中判定": "的中"}],
        date(2026, 9, 19),
        datetime(2026, 9, 20, 0, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
        [row],
    )
    sheet = workbook["バックテスト比較"]

    assert sheet.max_row == 2
    assert sheet["A2"].fill.fgColor.rgb == "00FFEB9C"
    assert workbook["比較集計"]["B2"].value == 1


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
