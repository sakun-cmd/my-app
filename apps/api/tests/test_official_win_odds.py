from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from boat_analysis.services.official_win_odds import (
    parse_official_trifecta_odds,
    trifecta_odds_fetch_due_at,
)


def trifecta_html(*, equal_odds: bool = False) -> str:
    header = "".join(f"<th>{lane}</th><th>選手{lane}</th>" for lane in range(1, 7))
    opponents = {
        lane: [other for other in range(1, 7) if other != lane]
        for lane in range(1, 7)
    }
    rows = []
    for second_index in range(5):
        second_by_first = {
            first: opponents[first][second_index] for first in range(1, 7)
        }
        thirds_by_first = {
            first: [
                lane
                for lane in range(1, 7)
                if lane not in {first, second_by_first[first]}
            ]
            for first in range(1, 7)
        }
        for third_index in range(4):
            cells = []
            for first in range(1, 7):
                second = second_by_first[first]
                third = thirds_by_first[first][third_index]
                odds = (
                    Decimal("10.0")
                    if equal_odds
                    else Decimal(first * 10 + second) + Decimal(third) / Decimal(10)
                )
                if third_index == 0:
                    cells.append(f'<td rowspan="4">{second}</td>')
                cells.extend([f"<td>{third}</td>", f'<td class="oddsPoint">{odds}</td>'])
            rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        "<html><body><div>3連単オッズ</div><table>"
        f"<thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody>"
        "</table></body></html>"
    )


def test_parse_official_trifecta_odds() -> None:
    result = parse_official_trifecta_odds(trifecta_html())

    assert result is not None
    assert len(result.odds) == 120
    assert result.odds[(1, 2, 3)] == Decimal("12.3")
    assert result.odds[(6, 5, 4)] == Decimal("65.4")
    by_lane = {item.lane: item for item in result.support}
    assert by_lane[1].popularity_rank == 1
    assert by_lane[6].popularity_rank == 6
    assert by_lane[1].implied_first_place_odds > 0


def test_equal_trifecta_support_uses_lane_as_tiebreaker() -> None:
    result = parse_official_trifecta_odds(trifecta_html(equal_odds=True))

    assert result is not None
    by_lane = {item.lane: item for item in result.support}
    assert by_lane[1].popularity_rank == 1
    assert by_lane[6].popularity_rank == 6


def test_incomplete_trifecta_odds_stays_pending() -> None:
    incomplete = trifecta_html().replace(
        '<td class="oddsPoint">12.3</td>',
        '<td class="oddsPoint">0</td>',
        1,
    )

    assert parse_official_trifecta_odds(incomplete) is None


def test_trifecta_page_without_data_is_pending() -> None:
    assert (
        parse_official_trifecta_odds(
            "<html><body>3連単オッズは未掲載です</body></html>"
        )
        is None
    )


def test_trifecta_odds_fetch_starts_three_minutes_before_close() -> None:
    scheduled = datetime(2026, 9, 12, 10, 2, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert trifecta_odds_fetch_due_at(scheduled) == datetime(
        2026,
        9,
        12,
        9,
        59,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
