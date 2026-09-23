from decimal import Decimal

from boat_analysis.services.two_boat_flow import (
    FlowBoat,
    _parse_win_odds,
    evaluate_two_boat_flow,
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


def test_lane_one_can_be_second_when_inside_escape_is_unlikely() -> None:
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
    assert any(ticket["combination"][1] == 1 for ticket in result["tickets"])


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
        boat(1, "6.80", "3.50"),
        boat(2, "6.95", "3.00"),
        boat(3, "6.70", "2.50"),
        boat(4, "6.90", "3.00"),
        boat(5, "7.00", "3.00"),
        boat(6, "7.05", "3.00"),
    ]
    preliminary = evaluate_two_boat_flow(boats)
    candidate = tuple(preliminary["tickets"][0]["combination"])
    other_candidate = tuple(preliminary["tickets"][1]["combination"])
    odds = {
        (1, 2, 3): Decimal("3.0"),
        (1, 3, 2): Decimal("5.0"),
        candidate: Decimal("12.0"),
        other_candidate: Decimal("12.0"),
        (6, 5, 4): Decimal("20.0"),
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
