from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from boat_analysis.services.official_exhibitions import (
    exhibition_fetch_due_at,
    parse_official_exhibition,
)
from boat_analysis.services.official_results import OfficialResultParseError

EXHIBITION_HTML = """
<html>
  <body>
    <table>
      <thead>
        <tr>
          <th>枠</th><th>写真</th><th>ボートレーサー</th><th>体重</th>
          <th>展示<br />タイム</th><th>チルト</th><th>プロペラ</th>
        </tr>
      </thead>
      <tbody><tr><td>1</td><td></td><td>選手一</td><td>52.0kg</td><td>6.71</td><td>0.0</td><td></td></tr></tbody>
      <tbody><tr><td>2</td><td></td><td>選手二</td><td>52.0kg</td><td>6.62</td><td>0.0</td><td></td></tr></tbody>
      <tbody><tr><td>3</td><td></td><td>選手三</td><td>52.0kg</td><td>6.76</td><td>0.0</td><td></td></tr></tbody>
      <tbody><tr><td>4</td><td></td><td>選手四</td><td>52.0kg</td><td>6.65</td><td>-0.5</td><td></td></tr></tbody>
      <tbody><tr><td>5</td><td></td><td>選手五</td><td>52.0kg</td><td>6.60</td><td>0.0</td><td></td></tr></tbody>
      <tbody><tr><td>6</td><td></td><td>選手六</td><td>52.0kg</td><td>6.65</td><td>-0.5</td><td></td></tr></tbody>
    </table>
    <table>
      <thead>
        <tr><th colspan="3">スタート展示</th></tr>
        <tr><th>コース</th><th>並び</th><th>ST</th></tr>
      </thead>
      <tbody><tr><td colspan="3"><span>1</span><span>.06</span></td></tr></tbody>
      <tbody><tr><td colspan="3"><span>3</span><span>F.03</span></td></tr></tbody>
      <tbody><tr><td colspan="3"><span>2</span><span>F.01</span></td></tr></tbody>
      <tbody><tr><td colspan="3"><span>4</span><span>.03</span></td></tr></tbody>
      <tbody><tr><td colspan="3"><span>5</span><span>.00</span></td></tr></tbody>
      <tbody><tr><td colspan="3"><span>6</span><span>F.03</span></td></tr></tbody>
    </table>
  </body>
</html>
"""


def test_parse_official_exhibition() -> None:
    result = parse_official_exhibition(EXHIBITION_HTML)

    assert result is not None
    assert len(result.entries) == 6
    by_lane = {entry.lane: entry for entry in result.entries}
    assert by_lane[2].exhibition_time_seconds == Decimal("6.62")
    assert by_lane[4].tilt == Decimal("-0.5")
    assert by_lane[3].exhibition_course == 2
    assert by_lane[3].exhibition_start_timing == Decimal("-0.03")
    assert by_lane[2].exhibition_course == 3


def test_exhibition_page_without_data_is_pending() -> None:
    assert parse_official_exhibition("<html><body>展示情報は未掲載です</body></html>") is None


def test_incomplete_official_exhibition_is_rejected() -> None:
    incomplete = EXHIBITION_HTML.replace(
        "<tbody><tr><td>6</td><td></td><td>選手六</td><td>52.0kg</td><td>6.65</td><td>-0.5</td><td></td></tr></tbody>",
        "",
    )
    with pytest.raises(OfficialResultParseError, match="incomplete"):
        parse_official_exhibition(incomplete)


def test_exhibition_fetch_starts_five_minutes_before_close() -> None:
    scheduled = datetime(2026, 9, 11, 10, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert exhibition_fetch_due_at(scheduled) == datetime(
        2026,
        9,
        11,
        10,
        25,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
