from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from boat_analysis.services.official_results import OfficialResultParseError
from boat_analysis.services.official_win_odds import (
    parse_official_win_odds,
    win_odds_fetch_due_at,
)

WIN_ODDS_HTML = """
<html>
  <body>
    <table>
      <thead>
        <tr><th></th><th>ボートレーサー</th><th>単勝オッズ</th></tr>
      </thead>
      <tbody><tr><td>1</td><td>選手一</td><td>1.2</td></tr></tbody>
      <tbody><tr><td>2</td><td>選手二</td><td>4.6</td></tr></tbody>
      <tbody><tr><td>3</td><td>選手三</td><td>8.9</td></tr></tbody>
      <tbody><tr><td>4</td><td>選手四</td><td>9.5</td></tr></tbody>
      <tbody><tr><td>5</td><td>選手五</td><td>20.5</td></tr></tbody>
      <tbody><tr><td>6</td><td>選手六</td><td>53.4</td></tr></tbody>
    </table>
  </body>
</html>
"""


def test_parse_official_win_odds() -> None:
    result = parse_official_win_odds(WIN_ODDS_HTML)

    assert result is not None
    assert len(result.entries) == 6
    by_lane = {entry.lane: entry for entry in result.entries}
    assert by_lane[1].win_odds == Decimal("1.2")
    assert by_lane[1].popularity_rank == 1
    assert by_lane[6].popularity_rank == 6


def test_win_odds_page_without_data_is_pending() -> None:
    assert parse_official_win_odds("<html><body>オッズは未掲載です</body></html>") is None


def test_incomplete_official_win_odds_is_rejected() -> None:
    incomplete = WIN_ODDS_HTML.replace(
        "<tbody><tr><td>6</td><td>選手六</td><td>53.4</td></tr></tbody>",
        "",
    )
    with pytest.raises(OfficialResultParseError, match="incomplete"):
        parse_official_win_odds(incomplete)


def test_zero_official_win_odds_is_ranked_last() -> None:
    zero_odds = WIN_ODDS_HTML.replace("<td>1.2</td>", "<td>0.0</td>")
    result = parse_official_win_odds(zero_odds)

    assert result is not None
    assert len(result.entries) == 6
    by_lane = {entry.lane: entry for entry in result.entries}
    assert by_lane[1].win_odds == Decimal("0.0")
    assert by_lane[1].popularity_rank == 6
    assert by_lane[2].popularity_rank == 1
    assert by_lane[6].popularity_rank == 5


def test_scratched_lane_is_excluded_but_others_still_parse() -> None:
    scratched = WIN_ODDS_HTML.replace("<td>1.2</td>", "<td>欠場</td>")
    result = parse_official_win_odds(scratched)

    assert result is not None
    assert len(result.entries) == 5
    by_lane = {entry.lane: entry for entry in result.entries}
    assert 1 not in by_lane
    assert by_lane[2].popularity_rank == 1


def test_equal_odds_use_lane_as_popularity_tiebreaker() -> None:
    tied = WIN_ODDS_HTML.replace("<td>4.6</td>", "<td>1.2</td>")
    result = parse_official_win_odds(tied)

    assert result is not None
    by_lane = {entry.lane: entry for entry in result.entries}
    assert by_lane[1].popularity_rank == 1
    assert by_lane[2].popularity_rank == 2


def test_win_odds_fetch_starts_three_minutes_before_close() -> None:
    scheduled = datetime(2026, 9, 12, 10, 2, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert win_odds_fetch_due_at(scheduled) == datetime(
        2026,
        9,
        12,
        9,
        59,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
