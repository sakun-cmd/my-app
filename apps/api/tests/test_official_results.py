from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from boat_analysis.services.official_results import (
    OfficialResultParseError,
    parse_official_result,
    result_fetch_due_at,
)

RESULT_HTML = """
<html>
  <body>
    <table>
      <thead><tr><th>着</th><th>枠</th><th>ボートレーサー</th><th>レースタイム</th></tr></thead>
      <tbody><tr><td>１</td><td>1</td><td>1111 選手一</td><td>1'48"2</td></tr></tbody>
      <tbody><tr><td>２</td><td>3</td><td>3333 選手三</td><td>1'49"4</td></tr></tbody>
      <tbody><tr><td>３</td><td>6</td><td>6666 選手六</td><td>1'51"2</td></tr></tbody>
      <tbody><tr><td>４</td><td>5</td><td>5555 選手五</td><td>1'52"2</td></tr></tbody>
      <tbody><tr><td>５</td><td>2</td><td>2222 選手二</td><td></td></tr></tbody>
      <tbody><tr><td>６</td><td>4</td><td>4444 選手四</td><td></td></tr></tbody>
    </table>
    <table>
      <thead><tr><th>スタート情報</th></tr></thead>
      <tbody><tr><td><span>1</span><span>.05 逃げ</span></td></tr></tbody>
      <tbody><tr><td><span>2</span><span>.13</span></td></tr></tbody>
      <tbody><tr><td><span>3</span><span>F.07</span></td></tr></tbody>
      <tbody><tr><td><span>5</span><span>.04</span></td></tr></tbody>
      <tbody><tr><td><span>6</span><span>.10</span></td></tr></tbody>
      <tbody><tr><td><span>4</span><span>.11</span></td></tr></tbody>
    </table>
    <table>
      <thead><tr><th>勝式</th><th>組番</th><th>払戻金</th><th>人気</th></tr></thead>
      <tbody><tr><td>3連単</td><td>1 - 3 - 6</td><td>￥1,830</td><td>12</td></tr></tbody>
      <tbody><tr><td rowspan="2">単勝</td><td><span>1</span></td><td><span>&yen;150</span></td><td></td></tr>
        <tr><td>&nbsp;</td><td></td><td></td></tr></tbody>
      <tbody><tr><td rowspan="2">複勝</td><td><span>1</span></td><td>&yen;110</td><td></td></tr>
        <tr><td><span>3</span></td><td>&yen;130</td><td></td></tr></tbody>
    </table>
  </body>
</html>
"""


def test_parse_official_result() -> None:
    result = parse_official_result(RESULT_HTML)

    assert result is not None
    assert result.winning_technique == "逃げ"
    assert [(entry.lane, entry.finish_position) for entry in result.entries] == [
        (1, 1),
        (2, 5),
        (3, 2),
        (4, 6),
        (5, 4),
        (6, 3),
    ]
    by_lane = {entry.lane: entry for entry in result.entries}
    assert by_lane[4].actual_course == 6
    assert by_lane[5].actual_course == 4
    assert by_lane[3].actual_start_timing == Decimal("-0.07")
    assert result.trifecta_combination == (1, 3, 6)
    assert result.trifecta_payout_yen == 1830
    assert result.trifecta_popularity_rank == 12
    assert result.win_lane == 1
    assert result.win_payout_yen == 150
    assert result.place_payouts == ((1, 110), (3, 130))


def test_result_without_win_row_leaves_win_empty() -> None:
    no_win = RESULT_HTML.split("<tbody><tr><td rowspan=\"2\">単勝</td>")[0] + "</table></body></html>"
    result = parse_official_result(no_win)

    assert result is not None
    assert result.trifecta_payout_yen == 1830
    assert result.win_lane is None and result.win_payout_yen is None
    assert result.place_payouts == ()


def test_result_page_without_result_is_pending() -> None:
    assert parse_official_result("<html><body>結果はまだありません</body></html>") is None


def test_void_race_is_detected_and_not_pending() -> None:
    result = parse_official_result("<html><body>レース不成立</body></html>")

    assert result is not None
    assert result.void is True
    assert result.void_marker == "不成立"
    assert result.entries == ()


# Structure of https://www.boatrace.jp/owpc/pc/race/raceresult for a cancelled race
# (observed 2026-09-21, e.g. Toda 1R / Tsu 5R / Mikuni 10R).
CANCELLED_HTML = """
<html>
  <body>
    <ul><li><span class="tab2_inner">9月21日<span>順延</span></span></li></ul>
    <div class="title12"><h3 class="title12_title is-type1">レース中止</h3></div>
  </body>
</html>
"""


def test_cancelled_race_is_detected_and_not_pending() -> None:
    result = parse_official_result(CANCELLED_HTML)

    assert result is not None
    assert result.void is True
    assert result.void_marker == "中止"
    assert result.entries == ()
    assert result.trifecta_combination is None


def test_finished_race_is_not_mistaken_for_void() -> None:
    result = parse_official_result(RESULT_HTML)

    assert result is not None
    assert result.void is False
    assert result.void_marker is None


def test_refunded_trifecta_with_only_two_finishers_is_final() -> None:
    refunded = (
        RESULT_HTML.replace("<td>３</td>", "<td>Ｆ</td>")
        .replace("<td>４</td>", "<td>Ｆ</td>")
        .replace("<td>５</td>", "<td>Ｆ</td>")
        .replace("<td>６</td>", "<td>Ｆ</td>")
        .replace(
            "<td>1 - 3 - 6</td><td>￥1,830</td><td>12</td>",
            "<td>不成立</td><td>￥100</td><td></td>",
        )
    )

    result = parse_official_result(refunded)

    assert result is not None
    assert result.trifecta_combination is None
    assert result.trifecta_payout_yen == 100
    assert result.trifecta_popularity_rank is None
    assert result.trifecta_refunded is True


def test_incomplete_official_result_is_rejected() -> None:
    incomplete = RESULT_HTML.replace(
        "<tbody><tr><td>６</td><td>4</td><td>4444 選手四</td><td></td></tr></tbody>",
        "",
    )
    with pytest.raises(OfficialResultParseError, match="incomplete"):
        parse_official_result(incomplete)


def test_result_fetch_starts_fifteen_minutes_after_close() -> None:
    scheduled = datetime(2026, 9, 11, 10, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert result_fetch_due_at(scheduled) == datetime(
        2026,
        9,
        11,
        10,
        45,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
