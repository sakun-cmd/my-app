from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from boat_analysis.services.two_boat_flow import (
    FlowBoat,
    _apply_derived_course_stats,
    _live_saved_coverage,
    _parse_win_odds,
    _to_boat,
    evaluate_live_two_boat_strategy,
    evaluate_two_boat_flow,
    result_winning_combination,
)


def boat(
    lane: int,
    exhibition: str,
    start_rank: str,
    *,
    lap: str | None = None,
    win_rate: str = "5.00",
    top3: str = "50.00",
) -> FlowBoat:
    return FlowBoat(
        lane=lane,
        exhibition_time=Decimal(exhibition),
        lap_time=Decimal(lap) if lap else None,
        course_avg_start_rank=Decimal(start_rank),
        course_avg_start_timing=Decimal("0.15"),
        nationwide_win_rate=Decimal(win_rate),
        course_top3_rate=Decimal(top3),
    )


def test_no_adjacent_gap_passes() -> None:
    result = evaluate_two_boat_flow(
        [boat(lane, f"6.{70 + lane:02d}", "3.00") for lane in range(1, 7)]
    )
    assert result["status"] == "pass"
    assert result["steps"][0]["result"] == "no"


def test_second_exhibition_clock_is_ap_exception() -> None:
    boats = [
        boat(1, "6.90", "2.00"),
        boat(2, "6.75", "3.50"),
        boat(3, "6.70", "3.00"),
        boat(4, "6.95", "3.00"),
        boat(5, "7.00", "3.00"),
        boat(6, "7.05", "3.00"),
    ]
    result = evaluate_two_boat_flow(boats)
    assert result["status"] == "review"
    assert result["outer_lane"] == 2
    assert result["steps"][2]["number"] == 3
    assert result["steps"][2]["result"] == "yes"


def test_second_lap_clock_is_ap_exception() -> None:
    boats = [
        boat(1, "6.90", "2.00", lap="38.50"),
        boat(2, "6.75", "3.50", lap="38.10"),
        boat(3, "6.70", "3.00", lap="38.00"),
        boat(4, "6.95", "3.00", lap="38.60"),
        boat(5, "7.00", "3.00", lap="38.70"),
        boat(6, "7.05", "3.00", lap="38.80"),
    ]
    result = evaluate_two_boat_flow(boats)
    metric = next(item for item in result["metrics"] if item["lane"] == 2)
    assert metric["lap_rank"] == 2
    assert metric["ap"] is True


def test_weak_lane_six_with_exhibition_only_ap_is_excluded() -> None:
    boats = [
        boat(1, "6.70", "2.10", lap="37.10", win_rate="7.10", top3="72.00"),
        boat(2, "6.74", "2.50", lap="37.20", win_rate="6.80", top3="68.00"),
        boat(3, "6.75", "3.00", lap="37.30", win_rate="6.20", top3="55.00"),
        boat(4, "6.76", "3.20", lap="37.40", win_rate="5.90", top3="48.00"),
        boat(5, "6.82", "3.32", lap="37.50", win_rate="5.70", top3="42.00"),
        boat(6, "6.71", "4.72", lap="37.60", win_rate="5.53", top3="27.59"),
    ]

    result = evaluate_two_boat_flow(boats)

    assert result["status"] == "pass"
    assert result["outer_lane"] == 6
    assert result["likely_lanes"] == []
    assert result["tickets"] == []
    assert result["composite_odds"] is None
    exclusion = result["steps"][-1]
    assert exclusion["number"] == 4
    assert exclusion["result"] == "no"
    assert "候補から除外" in exclusion["detail"]


def test_lane_six_is_kept_when_course_top3_rate_is_top_two() -> None:
    boats = [
        boat(1, "6.70", "2.10", lap="37.10", win_rate="7.10", top3="72.00"),
        boat(2, "6.74", "2.50", lap="37.20", win_rate="6.80", top3="55.00"),
        boat(3, "6.75", "3.00", lap="37.30", win_rate="6.20", top3="48.00"),
        boat(4, "6.76", "3.20", lap="37.40", win_rate="5.90", top3="42.00"),
        boat(5, "6.82", "3.32", lap="37.50", win_rate="5.70", top3="38.00"),
        boat(6, "6.71", "4.72", lap="37.60", win_rate="5.53", top3="68.00"),
    ]

    result = evaluate_two_boat_flow(boats)

    assert result["status"] == "review"
    assert result["likely_lanes"] == [6]


def test_outer_outer_better_on_both_becomes_only_likely_boat() -> None:
    boats = [
        boat(1, "6.90", "2.00"),
        boat(2, "6.75", "2.50"),
        boat(3, "6.70", "2.40"),
        boat(4, "6.95", "3.00"),
        boat(5, "7.00", "3.00"),
        boat(6, "7.05", "3.00"),
    ]
    result = evaluate_two_boat_flow(boats)
    assert result["likely_lanes"] == [3]
    assert next(step for step in result["steps"] if step["number"] == 4)["result"] == "yes"


def test_higher_win_rate_is_advanced_appeal() -> None:
    boats = [
        boat(1, "6.90", "2.00", win_rate="4.00"),
        boat(2, "6.75", "2.50", win_rate="4.10"),
        boat(3, "6.80", "3.50", win_rate="7.00"),
        boat(4, "6.95", "3.00", win_rate="3.90"),
        boat(5, "7.00", "3.00", win_rate="3.80"),
        boat(6, "7.05", "3.00", win_rate="3.70"),
    ]
    result = evaluate_two_boat_flow(boats)
    assert result["likely_lanes"] == [2, 3]
    step = next(step for step in result["steps"] if step["number"] == 5)
    assert "全国勝率上位2艇" in step["detail"]


def test_likely_two_three_condition_is_identified() -> None:
    boats = [
        boat(1, "6.90", "2.00", win_rate="7.00"),
        boat(2, "6.75", "2.50", win_rate="6.00"),
        boat(3, "6.80", "3.50", win_rate="5.90"),
        boat(4, "6.95", "3.00", win_rate="5.00"),
        boat(5, "7.00", "3.00", win_rate="4.50"),
        boat(6, "7.05", "3.00", win_rate="4.00"),
    ]

    result = evaluate_two_boat_flow(boats)

    assert result["likely_lanes"] == [2, 3]
    assert result["escape_assessment"] == "likely"
    assert result["likely_two_three_condition"] is True


def test_likely_two_three_condition_requires_lane_one_top_two() -> None:
    boats = [
        boat(1, "6.90", "2.00", win_rate="4.00"),
        boat(2, "6.75", "2.50", win_rate="6.00"),
        boat(3, "6.80", "3.50", win_rate="5.90"),
        boat(4, "6.95", "3.00", win_rate="7.00"),
        boat(5, "7.00", "3.00", win_rate="4.50"),
        boat(6, "7.05", "3.00", win_rate="3.50"),
    ]

    result = evaluate_two_boat_flow(boats)

    assert result["likely_lanes"] == [2, 3]
    assert result["likely_two_three_condition"] is False


def test_missing_start_rank_is_insufficient_not_ap_exception() -> None:
    boats = [
        boat(1, "6.90", "2.00"),
        boat(2, "6.75", "3.50"),
        boat(3, "6.70", "3.00"),
        boat(4, "6.95", "3.00"),
        boat(5, "7.00", "3.00"),
        boat(6, "7.05", "3.00"),
    ]
    boats[1] = FlowBoat(
        **{
            **boats[1].__dict__,
            "course_avg_start_rank": None,
        }
    )
    result = evaluate_two_boat_flow(boats)
    assert result["status"] == "insufficient_data"
    assert result["steps"][1]["result"] == "unknown"
    assert result["tickets"] == []


def test_unlikely_escape_is_warning_only_without_tickets() -> None:
    boats = [
        boat(1, "6.80", "3.50"),
        boat(2, "6.95", "3.00"),
        boat(3, "6.70", "2.50"),
        boat(4, "6.90", "3.00"),
        boat(5, "7.00", "3.00"),
        boat(6, "7.05", "3.00"),
    ]
    result = evaluate_two_boat_flow(boats)
    assert result["escape_assessment"] == "unlikely"
    assert result["tickets"] == []
    assert result["composite_odds"] is None


def test_lane_one_last_reference_rank_with_false_start_and_slow_exhibition_is_skipped() -> None:
    boats = [
        boat(1, "6.96", "2.27", lap="18.96", win_rate="4.08"),
        boat(2, "6.72", "3.38", lap="18.47", win_rate="6.10"),
        boat(3, "6.78", "3.33", lap="18.93", win_rate="4.84"),
        boat(4, "6.77", "2.98", lap="19.06", win_rate="6.84"),
        boat(5, "6.84", "3.92", lap="19.06", win_rate="4.05"),
        boat(6, "6.91", "3.19", lap="19.70", win_rate="2.05"),
    ]

    result = evaluate_two_boat_flow(
        boats,
        reference_ranks={1: 6, 2: 1, 3: 2, 4: 4, 5: 3, 6: 5},
        exhibition_start_timings={
            1: Decimal("-0.20"),
            2: Decimal("0.01"),
            3: Decimal("-0.03"),
            4: Decimal("-0.08"),
            5: Decimal("0.09"),
            6: Decimal("0.14"),
        },
    )

    assert result["escape_assessment"] == "low_confidence"
    assert result["tickets"] == []
    assert result["composite_odds"] is None
    assert result["likely_two_three_condition"] is False
    assert "参考順位最下位" in result["steps"][-1]["detail"]
    lane_one = next(metric for metric in result["metrics"] if metric["lane"] == 1)
    assert lane_one["reference_rank"] == 6
    assert lane_one["exhibition_start_timing"] == Decimal("-0.20")


def test_lane_one_low_confidence_requires_all_three_conditions() -> None:
    boats = [
        boat(1, "6.96", "2.27", lap="37.50"),
        boat(2, "6.72", "3.38", lap="37.60"),
        boat(3, "6.78", "3.33", lap="37.70"),
        boat(4, "6.77", "2.98", lap="37.80"),
        boat(5, "6.84", "3.92", lap="37.90"),
        boat(6, "6.91", "3.19", lap="38.00"),
    ]

    result = evaluate_two_boat_flow(
        boats,
        reference_ranks={1: 5, 2: 1, 3: 2, 4: 4, 5: 3, 6: 6},
        exhibition_start_timings={1: Decimal("-0.20")},
    )

    assert result["escape_assessment"] == "likely"
    assert result["tickets"]


def _lap_test_boats(laps: dict[int, str | None]) -> list[FlowBoat]:
    # 2号艇→3号艇の展示差で3号艇が注目艇、1号艇はイン逃げ寄り
    exhibitions = {1: "6.80", 2: "6.95", 3: "6.70", 4: "6.90", 5: "7.00", 6: "7.05"}
    starts = {1: "2.00", 2: "3.00", 3: "2.50", 4: "3.00", 5: "3.00", 6: "3.00"}
    return [boat(lane, exhibitions[lane], starts[lane], lap=laps[lane]) for lane in range(1, 7)]


def test_companions_are_chosen_by_lap_time_order() -> None:
    # 注目艇3・4号艇を除くと、展示タイム順の紐は2・5号艇、一周タイム順は6・5号艇
    laps = {1: "37.50", 2: "37.90", 3: "37.60", 4: "38.00", 5: "37.80", 6: "37.70"}

    result = evaluate_two_boat_flow(_lap_test_boats(laps))

    assert result["likely_lanes"] == [3, 4]
    lanes = {lane for t in result["tickets"] for lane in t["combination"][1:]}
    assert lanes == {3, 4, 5, 6}
    assert len(result["tickets"]) == 10


def test_weak_lane_six_companion_is_replaced_by_combined_rank() -> None:
    # びわこ2026-10-13 1R相当: 紐候補4・5・6号艇のうち一周タイム上位は5・6号艇だが、
    # 6号艇は全国勝率・コース3連率が最下位で、総合順位は4号艇・5号艇が上
    boats = [
        boat(1, "6.76", "3.58", lap="36.50", win_rate="4.43", top3="73.68"),
        boat(2, "6.67", "4.29", lap="37.37", win_rate="3.22", top3="16.13"),
        boat(3, "6.69", "3.46", lap="37.53", win_rate="6.03", top3="70.73"),
        boat(4, "6.77", "2.62", lap="38.21", win_rate="6.18", top3="73.53"),
        boat(5, "6.85", "3.39", lap="37.80", win_rate="4.12", top3="21.43"),
        boat(6, "6.79", "3.51", lap="38.10", win_rate="1.54", top3="1.20"),
    ]

    result = evaluate_two_boat_flow(boats, venue_code="11")

    assert result["likely_lanes"] == [2, 3]
    lanes = {lane for t in result["tickets"] for lane in t["combination"][1:]}
    assert lanes == {2, 3, 4, 5}
    assert "4号艇に入れ替えました" in result["steps"][-1]["detail"]


def test_strong_lane_six_companion_is_kept() -> None:
    boats = [
        boat(1, "6.76", "3.58", lap="36.50", win_rate="4.43", top3="73.68"),
        boat(2, "6.67", "4.29", lap="37.37", win_rate="3.22", top3="16.13"),
        boat(3, "6.69", "3.46", lap="37.53", win_rate="6.03", top3="70.73"),
        boat(4, "6.77", "2.62", lap="38.21", win_rate="4.18", top3="23.53"),
        boat(5, "6.85", "3.39", lap="37.80", win_rate="4.12", top3="21.43"),
        boat(6, "6.79", "3.51", lap="38.10", win_rate="6.54", top3="51.20"),
    ]

    result = evaluate_two_boat_flow(boats, venue_code="11")

    lanes = {lane for t in result["tickets"] for lane in t["combination"][1:]}
    assert lanes == {2, 3, 5, 6}
    assert all("入れ替え" not in step["detail"] for step in result["steps"])


def test_tickets_are_skipped_when_any_lap_time_is_missing() -> None:
    laps = {1: "37.50", 2: "37.90", 3: "37.60", 4: None, 5: "37.80", 6: "37.70"}

    result = evaluate_two_boat_flow(_lap_test_boats(laps))

    assert result["escape_assessment"] == "likely"
    assert result["tickets"] == []
    assert result["composite_odds"] is None
    assert "6艇揃わない" in result["steps"][-1]["detail"]


def test_edogawa_never_creates_tickets() -> None:
    laps = {lane: f"37.{lane}0" for lane in range(1, 7)}

    result = evaluate_two_boat_flow(_lap_test_boats(laps), venue_code="03")

    assert result["tickets"] == []
    assert "江戸川は参加対象外" in result["steps"][-1]["detail"]


def test_kiryu_source_rows_use_half_lap_time() -> None:
    row = {
        "teiban": "2", "kyoteijo_code": "01", "tenji_time": "678",
        "hanshu": "1850", "isshu": None, "zenkoku_ritsu_1": "550",
    }

    assert _to_boat(row).lap_time == Decimal("18.50")
    assert _to_boat({**row, "kyoteijo_code": "02", "isshu": "3720"}).lap_time == Decimal(
        "37.20"
    )


def test_standard_correction_can_create_the_exhibition_gap_trigger() -> None:
    # 平和島(04): 2号艇の展示補正は-0.02秒。生タイム差0.09秒が補正後は0.11秒になる。
    boats = [
        boat(1, "6.89", "2.00"),
        boat(2, "6.80", "3.50"),
        boat(3, "6.95", "3.00"),
        boat(4, "6.95", "3.00"),
        boat(5, "7.00", "3.00"),
        boat(6, "7.05", "3.00"),
    ]

    raw = evaluate_two_boat_flow(boats)
    corrected = evaluate_two_boat_flow(boats, venue_code="04")

    assert raw["status"] == "pass"
    assert raw["steps"][0]["result"] == "no"
    assert corrected["status"] == "review"
    assert corrected["outer_lane"] == 2
    detail = corrected["steps"][0]["detail"]
    assert "スタンダード版補正後" in detail
    assert "0.11秒" in detail
    assert "生タイム差0.09秒" in detail


def test_standard_correction_keeps_raw_times_and_exposes_corrected_times() -> None:
    boats = [boat(lane, f"6.{70 + lane:02d}", "3.00", lap=f"37.{lane}0") for lane in range(1, 7)]

    result = evaluate_two_boat_flow(boats, venue_code="04")
    metrics = {metric["lane"]: metric for metric in result["metrics"]}

    assert metrics[1]["exhibition_time"] == Decimal("6.71")
    assert metrics[1]["exhibition_time_corrected"] == Decimal("6.71")
    assert metrics[3]["exhibition_time"] == Decimal("6.73")
    assert metrics[3]["exhibition_time_corrected"] == Decimal("6.69")
    assert metrics[3]["lap_time"] == Decimal("37.30")
    assert metrics[3]["lap_time_corrected"] == Decimal("36.95")


def test_standard_correction_changes_lap_rank_and_ap() -> None:
    # 平和島(04)の一周補正は外枠ほど大きなマイナス。生タイムでは1号艇が最速でも
    # 補正後は3号艇・2号艇が1・2番時計になる。
    boats = [
        boat(lane, f"6.{70 + lane:02d}", "3.00", lap=f"37.{lane - 1}0") for lane in range(1, 7)
    ]

    raw = {m["lane"]: m for m in evaluate_two_boat_flow(boats)["metrics"]}
    corrected = {m["lane"]: m for m in evaluate_two_boat_flow(boats, venue_code="04")["metrics"]}

    assert raw[1]["lap_rank"] == 1
    assert corrected[3]["lap_rank"] == 1
    assert corrected[2]["lap_rank"] == 2
    assert corrected[1]["lap_rank"] > 2


def test_standard_correction_can_flip_outer_outer_comparison() -> None:
    # 平和島(04): 3号艇の展示補正(-0.04)が2号艇(-0.02)より大きく、
    # 生タイムでは2号艇が速くても補正後は3号艇が上回る。
    boats = [
        boat(1, "6.90", "2.00"),
        boat(2, "6.75", "2.50"),
        boat(3, "6.76", "2.40"),
        boat(4, "6.95", "3.00"),
        boat(5, "7.00", "3.00"),
        boat(6, "7.05", "3.00"),
    ]

    raw = evaluate_two_boat_flow(boats)
    corrected = evaluate_two_boat_flow(boats, venue_code="04")

    assert next(step for step in raw["steps"] if step["number"] == 4)["result"] == "no"
    assert next(step for step in corrected["steps"] if step["number"] == 4)["result"] == "yes"
    assert corrected["likely_lanes"] == [3]


def test_no_venue_code_applies_no_correction() -> None:
    boats = [boat(lane, f"6.{70 + lane:02d}", "3.00", lap="37.00") for lane in range(1, 7)]

    result = evaluate_two_boat_flow(boats)

    for metric in result["metrics"]:
        assert metric["exhibition_time_corrected"] == metric["exhibition_time"]
        assert metric["lap_time_corrected"] == metric["lap_time"]
    assert "スタンダード版補正" not in result["steps"][0]["detail"]


def test_ticket_popularity_rank_uses_all_available_odds() -> None:
    boats = [
        boat(1, "6.80", "2.00", lap="37.50"),
        boat(2, "6.95", "3.00", lap="37.60"),
        boat(3, "6.70", "2.50", lap="37.70"),
        boat(4, "6.90", "3.00", lap="37.80"),
        boat(5, "7.00", "3.00", lap="37.90"),
        boat(6, "7.05", "3.00", lap="38.00"),
    ]
    preliminary = evaluate_two_boat_flow(boats)
    candidate = tuple(preliminary["tickets"][0]["combination"])
    other_candidate = tuple(preliminary["tickets"][1]["combination"])
    odds = {
        (6, 5, 4): Decimal("3.0"),
        (6, 4, 5): Decimal("5.0"),
        candidate: Decimal("12.0"),
        other_candidate: Decimal("12.0"),
        (5, 6, 4): Decimal("20.0"),
    }

    result = evaluate_two_boat_flow(boats, odds)
    ranked = {tuple(ticket["combination"]): ticket for ticket in result["tickets"]}

    assert {
        ranked[candidate]["popularity_rank"],
        ranked[other_candidate]["popularity_rank"],
    } == {3, 4}
    assert ranked[candidate]["odds"] == Decimal("12.0")


def test_win_popularity_uses_closing_win_odds_and_lane_tiebreaker() -> None:
    packed = "".join(
        [
            "1000025",
            "2000018",
            "3000040",
            "4000018",
            "5000060",
            "6000080",
        ]
    )
    win_odds = _parse_win_odds(packed)
    boats = [boat(lane, f"6.{70 + lane:02d}", "3.00") for lane in range(1, 7)]

    result = evaluate_two_boat_flow(boats, win_odds=win_odds)
    metrics = {metric["lane"]: metric for metric in result["metrics"]}

    assert metrics[2]["popularity_rank"] == 1
    assert metrics[4]["popularity_rank"] == 2
    assert metrics[1]["popularity_rank"] == 3
    assert metrics[1]["win_odds"] == Decimal("2.5")


def test_win_popularity_ranks_zero_odds_last() -> None:
    win_odds = {
        1: Decimal("0.0"),
        2: Decimal("1.3"),
        3: Decimal("3.8"),
        4: Decimal("11.5"),
        5: Decimal("19.2"),
        6: Decimal("5.2"),
    }
    boats = [boat(lane, f"6.{70 + lane:02d}", "3.00") for lane in range(1, 7)]

    result = evaluate_two_boat_flow(boats, win_odds=win_odds)
    metrics = {metric["lane"]: metric for metric in result["metrics"]}

    assert metrics[1]["popularity_rank"] == 6
    assert metrics[2]["popularity_rank"] == 1
    assert metrics[6]["popularity_rank"] == 3


def test_stored_popularity_overrides_zero_win_odds_ranking() -> None:
    win_odds = {
        1: Decimal("0.0"),
        2: Decimal("1.3"),
        3: Decimal("3.8"),
        4: Decimal("11.5"),
        5: Decimal("19.2"),
        6: Decimal("5.2"),
    }
    exacta_popularity = {1: 2, 2: 1, 3: 3, 4: 5, 5: 6, 6: 4}
    boats = [boat(lane, f"6.{70 + lane:02d}", "3.00") for lane in range(1, 7)]

    result = evaluate_two_boat_flow(
        boats,
        win_odds=win_odds,
        popularity_ranks=exacta_popularity,
    )
    metrics = {metric["lane"]: metric for metric in result["metrics"]}

    assert metrics[1]["win_odds"] == Decimal("0.0")
    assert metrics[1]["popularity_rank"] == 2
    assert metrics[6]["popularity_rank"] == 4


def test_result_winning_combination_orders_by_finish_position() -> None:
    entries = [(3, 2), (1, 3), (5, 1), (2, None), (4, None), (6, None)]

    assert result_winning_combination(entries) == (5, 3, 1)


def test_result_winning_combination_requires_top_three() -> None:
    entries = [(1, 1), (2, 2), (3, None), (4, None), (5, None), (6, None)]

    assert result_winning_combination(entries) is None


def test_result_winning_combination_requires_a_first_place() -> None:
    entries = [(1, 2), (2, 3), (3, 4), (4, None), (5, None), (6, None)]

    assert result_winning_combination(entries) is None


def test_derived_course_stats_replace_fixed_snapshot_values() -> None:
    boats = [boat(1, "6.80", "4.80", top3="20.00")]
    rows = [{"teiban": "1", "toroku_bango": "4321"}]
    stats = {
        ("4321", 1): SimpleNamespace(
            starts=24,
            average_start_rank=Decimal("2.75"),
            average_start_timing=Decimal("0.143"),
            top3_rate=Decimal("62.50"),
            history_through=date(2026, 10, 3),
            source="source_raw_results_365d",
        )
    }

    result = _apply_derived_course_stats(boats, rows, stats)

    assert result[0].course_avg_start_rank == Decimal("2.75")
    assert result[0].course_avg_start_timing == Decimal("0.143")
    assert result[0].course_top3_rate == Decimal("62.50")
    assert result[0].course_starts == 24
    assert result[0].course_stats_snapshot_date == date(2026, 10, 3)
    assert result[0].course_stats_source == "source_raw_results_365d"


def test_derived_course_stats_clear_fixed_values_when_sample_is_too_small() -> None:
    boats = [boat(2, "6.80", "1.25", top3="80.00")]
    rows = [{"teiban": "2", "toroku_bango": "4321"}]
    stats = {
        ("4321", 2): SimpleNamespace(
            starts=9,
            average_start_rank=Decimal("2.00"),
            average_start_timing=Decimal("0.120"),
            top3_rate=Decimal("70.00"),
            history_through=date(2026, 10, 2),
            source="source_raw_results_365d",
        )
    }

    result = _apply_derived_course_stats(boats, rows, stats)

    assert result[0].course_avg_start_rank is None
    assert result[0].course_avg_start_timing is None
    assert result[0].course_top3_rate is None
    assert result[0].course_starts == 9
    assert result[0].course_stats_source == "source_raw_results_365d"


def _live_entry(
    lane: int,
    cutoff: datetime,
    *,
    include_lap: bool = True,
    observed_at: datetime | None = None,
) -> SimpleNamespace:
    observation = SimpleNamespace(
        observed_at=observed_at or cutoff,
        source="boatrace.jp",
        exhibition_time_seconds=Decimal("6.70"),
        lap_source="race.boatcast.jp" if include_lap else None,
        half_lap_time_seconds=Decimal("18.20") if include_lap else None,
        lap_time_seconds=None,
    )
    odds = SimpleNamespace(
        observed_at=cutoff - timedelta(minutes=3),
        source="boatrace.jp",
        popularity_rank=lane,
    )
    return SimpleNamespace(
        lane=lane,
        exhibitions=[observation],
        win_odds_observations=[odds],
    )


def test_live_saved_coverage_requires_pre_race_six_lane_inputs() -> None:
    cutoff = datetime(2026, 10, 6, 12, tzinfo=UTC)
    race = SimpleNamespace(
        scheduled_at=cutoff,
        venue_code="01",
        entries=[
            _live_entry(
                lane,
                cutoff,
                observed_at=(
                    cutoff + timedelta(minutes=1) if lane == 6 else cutoff
                ),
            )
            for lane in range(1, 7)
        ],
    )

    coverage = _live_saved_coverage(race)

    assert coverage["official_exhibition"] is False
    assert coverage["boatcast_lap"] is False
    assert coverage["popularity"] is True
    assert coverage["complete"] is False


def test_live_saved_coverage_does_not_require_laps_at_edogawa() -> None:
    cutoff = datetime(2026, 10, 6, 12, tzinfo=UTC)
    race = SimpleNamespace(
        scheduled_at=cutoff,
        venue_code="03",
        entries=[
            _live_entry(lane, cutoff, include_lap=False)
            for lane in range(1, 7)
        ],
    )

    coverage = _live_saved_coverage(race)

    assert coverage == {
        "official_exhibition": True,
        "boatcast_lap": True,
        "popularity": True,
        "complete": True,
    }


def test_live_evaluation_uses_saved_inputs_and_official_payout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutoff = datetime(2026, 10, 6, 12, tzinfo=UTC)
    race_id = uuid4()
    result = SimpleNamespace(
        finalized_at=cutoff + timedelta(minutes=10),
        trifecta_refunded=False,
        winning_technique="逃げ",
        trifecta_payout_yen=1500,
        entries=[
            SimpleNamespace(lane=1, finish_position=1),
            SimpleNamespace(lane=2, finish_position=2),
            SimpleNamespace(lane=3, finish_position=3),
        ],
    )
    race = SimpleNamespace(
        id=race_id,
        race_date=date(2026, 10, 6),
        venue_code="01",
        race_number=1,
        scheduled_at=cutoff,
        entries=[_live_entry(lane, cutoff) for lane in range(1, 7)],
        result=result,
    )
    db = Mock()
    db.scalars.return_value.all.return_value = [race]
    snapshot = date(2026, 10, 5)
    flow = {
        "status": "review",
        "steps": [{"number": 1, "result": "yes", "detail": "trigger"}],
        "likely_lanes": [2, 3],
        "escape_assessment": "likely",
        "tickets": [
            {"combination": (1, 2, 3)},
            {"combination": (1, 3, 2)},
        ],
        "metrics": [
            {
                "lane": lane,
                "course_avg_start_rank": Decimal("3.00"),
                "course_stats_snapshot_date": snapshot,
            }
            for lane in range(1, 7)
        ],
    }
    monkeypatch.setattr(
        "boat_analysis.services.two_boat_flow.analyze_races_two_boat_flow",
        lambda races, session: {race_id: flow},
    )

    evaluated = evaluate_live_two_boat_strategy(
        date(2026, 10, 6),
        date(2026, 10, 6),
        db,
    )

    assert evaluated["data_source"] == "live_saved"
    assert evaluated["result_available_races"] == 1
    assert evaluated["live_complete_races"] == 1
    assert evaluated["excluded_incomplete_live_races"] == 0
    assert evaluated["ticket_generated_races"] == 1
    assert evaluated["ticket_hit_rate"] == 1
    assert evaluated["flat_stake_return_rate"] == 7.5
