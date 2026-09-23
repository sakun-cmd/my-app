from decimal import Decimal

from boat_analysis.services.scoring import (
    ScoringInput,
    expected_lap_fields,
    score_entries,
)


def test_scoring_prefers_faster_complete_entry() -> None:
    result = score_entries(
        [
            ScoringInput(1, Decimal("6.70"), Decimal("0.08"), 1),
            ScoringInput(2, Decimal("6.85"), Decimal("0.18"), 2),
        ]
    )
    assert [item.lane for item in result] == [1, 2]
    assert result[0].score > result[1].score
    assert result[0].confidence == "高"


def test_scoring_reports_missing_data() -> None:
    result = score_entries([ScoringInput(1, None, None, None)])
    assert result[0].score == Decimal("0.00")
    assert result[0].confidence == "低"
    assert result[0].warnings


def test_negative_start_is_penalized() -> None:
    result = score_entries(
        [
            ScoringInput(1, Decimal("6.80"), Decimal("-0.01"), 1),
            ScoringInput(2, Decimal("6.80"), Decimal("0.01"), 2),
        ]
    )
    first = next(item for item in result if item.lane == 1)
    second = next(item for item in result if item.lane == 2)
    assert first.score < second.score
    assert any("負値" in warning for warning in first.warnings)


def test_start_deviation_from_average_is_penalized() -> None:
    # 展示STは選手の平均STよりおよそ0.08秒タイトに出る傾向があるため、
    # その傾向どおりの艇(1号艇)は減点されず、傾向から外れた艇(2号艇)が減点される。
    result = score_entries(
        [
            ScoringInput(
                1,
                Decimal("6.80"),
                Decimal("0.07"),
                1,
                average_start_timing=Decimal("0.15"),
            ),
            ScoringInput(
                2,
                Decimal("6.80"),
                Decimal("0.20"),
                2,
                average_start_timing=Decimal("0.15"),
            ),
        ]
    )
    first = next(item for item in result if item.lane == 1)
    second = next(item for item in result if item.lane == 2)
    assert first.score > second.score
    assert any("平均ST" in warning for warning in second.warnings)
    assert not first.warnings


def test_scoring_uses_lap_exhibition() -> None:
    result = score_entries(
        [
            ScoringInput(
                1,
                Decimal("6.80"),
                Decimal("0.10"),
                1,
                lap_time_seconds=Decimal("38.50"),
                cornering_time_seconds=Decimal("6.20"),
                straight_time_seconds=Decimal("7.80"),
            ),
            ScoringInput(
                2,
                Decimal("6.80"),
                Decimal("0.10"),
                2,
                lap_time_seconds=Decimal("38.10"),
                cornering_time_seconds=Decimal("5.80"),
                straight_time_seconds=Decimal("7.60"),
            ),
        ],
        "04",
    )
    assert [item.lane for item in result] == [2, 1]
    assert {part.key for part in result[0].contributions} >= {
        "lap",
        "cornering",
        "straight",
    }


def test_venue_specific_lap_fields() -> None:
    assert expected_lap_fields("01") == (
        "half_lap_time_seconds",
        "cornering_time_seconds",
        "straight_time_seconds",
    )
    assert expected_lap_fields("12") == (
        "lap_time_seconds",
        "cornering_time_seconds",
    )
    assert expected_lap_fields("03") == ()


def test_single_lap_value_is_not_scored() -> None:
    # venue_codeは指定しない: スタンダード版補正が展示タイム比較に影響し、
    # このテストが検証したい「単独値は配点対象外」という論点と無関係な差が
    # 生まれてしまうのを避けるため。
    result = score_entries(
        [
            ScoringInput(
                1,
                Decimal("6.80"),
                Decimal("0.10"),
                1,
                lap_time_seconds=Decimal("38.10"),
            ),
            ScoringInput(2, Decimal("6.80"), Decimal("0.10"), 2),
        ],
    )
    assert result[0].lane == 1
    assert result[0].score == result[1].score
    lap = next(part for part in result[0].contributions if part.key == "lap")
    assert lap.points == Decimal("0.00")


def test_missing_lap_data_uses_neutral_score() -> None:
    # venue_codeは指定しない(理由はtest_single_lap_value_is_not_scoredと同様)。
    result = score_entries(
        [
            ScoringInput(
                1,
                Decimal("6.80"),
                Decimal("0.10"),
                1,
                lap_time_seconds=Decimal("38.00"),
                cornering_time_seconds=Decimal("5.80"),
                straight_time_seconds=Decimal("7.60"),
            ),
            ScoringInput(
                2,
                Decimal("6.80"),
                Decimal("0.10"),
                2,
                lap_time_seconds=Decimal("38.40"),
                cornering_time_seconds=Decimal("6.20"),
                straight_time_seconds=Decimal("7.90"),
            ),
            ScoringInput(3, Decimal("6.80"), Decimal("0.10"), 3),
        ],
    )
    scores = {item.lane: item.score for item in result}
    assert scores[1] > scores[3] > scores[2]
    missing = next(item for item in result if item.lane == 3)
    assert missing.confidence == "低"
    assert any("周回展示データが未到着" in warning for warning in missing.warnings)


def test_standard_correction_can_flip_exhibition_ranking() -> None:
    # 平和島(04)の展示タイム補正は2号艇-0.02秒。生タイムでは1号艇の方が速いが、
    # 補正後は2号艇の方が速くなることを確認する。
    result = score_entries(
        [
            ScoringInput(1, Decimal("6.80"), Decimal("0.10"), 1),
            ScoringInput(2, Decimal("6.81"), Decimal("0.10"), 2),
        ],
        "04",
    )
    contributions = {
        item.lane: next(part for part in item.contributions if part.key == "exhibition_time")
        for item in result
    }
    assert contributions[2].points > contributions[1].points
    assert contributions[1].raw_value == Decimal("6.80")
    assert "スタンダード版補正" not in contributions[1].explanation
    assert "スタンダード版補正(-0.02秒)" in contributions[2].explanation


def test_standard_correction_unknown_venue_is_noop() -> None:
    result = score_entries(
        [
            ScoringInput(1, Decimal("6.80"), Decimal("0.10"), 1),
            ScoringInput(2, Decimal("6.81"), Decimal("0.10"), 2),
        ],
        "99",
    )
    contributions = {
        item.lane: next(part for part in item.contributions if part.key == "exhibition_time")
        for item in result
    }
    assert contributions[1].points > contributions[2].points
