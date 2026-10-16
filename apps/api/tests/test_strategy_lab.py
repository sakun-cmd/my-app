from decimal import Decimal

from boat_analysis.services.strategy_lab import (
    build_strategy_tickets,
    calculate_threats,
)


def _flow(likely_lanes: list[int]) -> dict:
    metrics = []
    for lane in range(1, 7):
        metrics.append(
            {
                "lane": lane,
                "exhibition_rank": lane,
                "lap_rank": lane,
                "course_avg_start_rank": Decimal(str(lane)),
                "nationwide_win_rate": Decimal(str(7 - lane)),
                "course_top3_rate": Decimal(str(70 - lane)),
                "popularity_rank": lane,
                "exhibition_time_corrected": Decimal(f"6.{70 + lane}"),
            }
        )
    metrics[1].update(
        {
            "exhibition_rank": 1,
            "lap_rank": 1,
            "course_avg_start_rank": Decimal("0.5"),
            "nationwide_win_rate": Decimal("8.0"),
            "course_top3_rate": Decimal("80"),
            "popularity_rank": 1,
            "exhibition_time_corrected": Decimal("6.60"),
        }
    )
    return {
        "likely_lanes": likely_lanes,
        "metrics": metrics,
        "tickets": [
            {"combination": (1, 2, 3)},
            {"combination": (1, 3, 2)},
        ],
    }


def _popularity_flow(popularity: dict[int, int], likely_lanes: list[int]) -> dict:
    flow = _flow(likely_lanes)
    for item in flow["metrics"]:
        item["popularity_rank"] = popularity[item["lane"]]
    return flow


def test_popularity_formation_swaps_second_and_third_groups() -> None:
    # 2番人気=3号艇, 3番人気=2号艇, 4番人気=5号艇, 5番人気=4号艇, 6番人気=6号艇
    flow = _popularity_flow({1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 6}, [2])

    tickets, reason = build_strategy_tickets("popularity_formation", flow, calculate_threats(flow))

    assert reason is None
    assert tickets == sorted(
        [
            (1, 5, 3),
            (1, 5, 2),
            (1, 4, 3),
            (1, 4, 2),  # ① 2着4・5番人気 → 3着2・3番人気
            (1, 3, 5),
            (1, 3, 4),
            (1, 2, 5),
            (1, 2, 4),  # ② 2着2・3番人気 → 3着4・5番人気
        ]
    )


def test_popularity_formation_replaces_fifth_favorite_with_recommended_lane_six() -> None:
    flow = _popularity_flow({1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 6}, [3, 6])

    tickets, _ = build_strategy_tickets("popularity_formation", flow, calculate_threats(flow))

    assert len(tickets) == 8
    assert all(4 not in ticket for ticket in tickets)  # 5番人気(4号艇)を除外
    assert (1, 6, 3) in tickets and (1, 2, 6) in tickets


def test_popularity_formation_keeps_lane_six_when_already_selected() -> None:
    # 6号艇が2番人気ならそのまま(5番人気は差し替えない)
    flow = _popularity_flow({1: 1, 2: 3, 3: 4, 4: 5, 5: 6, 6: 2}, [6])

    tickets, _ = build_strategy_tickets("popularity_formation", flow, calculate_threats(flow))

    assert {lane for ticket in tickets for lane in ticket[1:]} == {6, 2, 3, 4}


def test_popularity_formation_requires_current_tickets_and_popularity() -> None:
    flow = _popularity_flow({1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}, [2])
    no_tickets = {**flow, "tickets": []}
    assert build_strategy_tickets("popularity_formation", no_tickets, calculate_threats(flow)) == (
        [],
        "現行買い目なし",
    )

    for item in flow["metrics"]:
        item["popularity_rank"] = None
    assert build_strategy_tickets("popularity_formation", flow, calculate_threats(flow)) == (
        [],
        "単勝人気が未取得のため見送り",
    )


def test_popularity_formation_v2_skips_when_lane_one_is_not_favorite() -> None:
    v2 = {"require_lane_one_favorite": True}
    flow = _popularity_flow({1: 2, 2: 1, 3: 3, 4: 4, 5: 5, 6: 6}, [2])
    threats = calculate_threats(flow)

    assert build_strategy_tickets("popularity_formation", flow, threats, v2) == (
        [],
        "1号艇が1番人気でないため見送り",
    )
    # v1(設定なし)は従来どおり買い目を作る
    assert len(build_strategy_tickets("popularity_formation", flow, threats)[0]) == 8

    favorite = _popularity_flow({1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 6}, [2])
    tickets, reason = build_strategy_tickets(
        "popularity_formation", favorite, calculate_threats(favorite), v2
    )
    assert reason is None and len(tickets) == 8


def test_popularity_formation_v3_requires_lane_one_implied_odds_below_threshold() -> None:
    v3 = {"max_lane_one_implied_odds": "1.5"}

    def flow_with(lane_one_odds: str | None, source: str | None = "official_trifecta"):
        flow = _popularity_flow({1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 6}, [2])
        flow["popularity_source"] = source
        flow["metrics"][0]["win_odds"] = (
            Decimal(lane_one_odds) if lane_one_odds is not None else None
        )
        return flow

    tickets, reason = build_strategy_tickets(
        "popularity_formation", flow_with("1.4"), calculate_threats(flow_with("1.4")), v3
    )
    assert reason is None and len(tickets) == 8

    assert build_strategy_tickets(
        "popularity_formation", flow_with("1.5"), calculate_threats(flow_with("1.5")), v3
    ) == ([], "1号艇の1着支持換算値が1.5倍以上のため見送り")

    for missing in (flow_with(None), flow_with("1.2", source="source_database")):
        assert build_strategy_tickets(
            "popularity_formation", missing, calculate_threats(missing), v3
        ) == ([], "1号艇の1着支持換算値が未取得のため見送り")


def test_single_wide_strategy_widens_only_single_likely_races() -> None:
    config = {"max_lane_one_implied_odds": "1.5"}

    def flow_with(likely: list[int], lane_one_odds: str = "1.3"):
        flow = _popularity_flow({1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 6}, likely)
        flow["popularity_source"] = "official_trifecta"
        flow["metrics"][0]["win_odds"] = Decimal(lane_one_odds)
        return flow

    single = flow_with([3])
    tickets, reason = build_strategy_tickets(
        "popularity_formation_single_wide", single, calculate_threats(single), config
    )
    assert reason is None
    assert tickets == sorted(
        {(1, 3, other) for other in (2, 4, 5, 6)} | {(1, other, 3) for other in (2, 4, 5, 6)}
    )

    pair = flow_with([3, 4])
    assert build_strategy_tickets(
        "popularity_formation_single_wide", pair, calculate_threats(pair), config
    ) == build_strategy_tickets("popularity_formation", pair, calculate_threats(pair), config)

    skipped = flow_with([3], "1.5")
    assert build_strategy_tickets(
        "popularity_formation_single_wide", skipped, calculate_threats(skipped), config
    ) == ([], "1号艇の1着支持換算値が1.5倍以上のため見送り")


def test_calculate_threats_uses_seven_pre_race_signals() -> None:
    threats = calculate_threats(_flow([2]))

    assert threats["scores"][2] == 7
    assert threats["strong_lanes"] == [2]
    assert all(threats["reasons"][2].values())


def test_current_and_single_likely_strategies_are_separate() -> None:
    flow = _flow([2])
    threats = calculate_threats(flow)

    current, current_reason = build_strategy_tickets("current", flow, threats)
    skipped, skip_reason = build_strategy_tickets("skip_single_likely", flow, threats)

    assert current == [(1, 2, 3), (1, 3, 2)]
    assert current_reason is None
    assert skipped == []
    assert skip_reason == "注目艇が1艇のため見送り"


def test_recommended_strong_threat_builds_three_boat_box() -> None:
    flow = _flow([2])
    threats = calculate_threats(flow)

    tickets, reason = build_strategy_tickets("recommended_threat_box", flow, threats)

    assert reason is None
    assert len(tickets) == 6
    assert set(tickets) == {
        (1, 2, 3),
        (1, 3, 2),
        (2, 1, 3),
        (2, 3, 1),
        (3, 1, 2),
        (3, 2, 1),
    }


def test_recommended_threat_box_skips_when_recommendation_does_not_match() -> None:
    flow = _flow([3])
    threats = calculate_threats(flow)

    tickets, reason = build_strategy_tickets("recommended_threat_box", flow, threats)

    assert tickets == []
    assert reason == "おすすめ艇と強い脅威艇が一致しないため見送り"


def test_strong_threat_top_two_box_contains_lane_one() -> None:
    flow = _flow([2])
    threats = calculate_threats(flow)

    tickets, reason = build_strategy_tickets("strong_threat_top2_box", flow, threats)

    assert reason is None
    assert len(tickets) == 6
    assert {lane for ticket in tickets for lane in ticket} == {1, 2, 3}
