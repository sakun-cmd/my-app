from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import pytest

from boat_analysis.models import Race
from boat_analysis.services.official_laps import (
    _fetch_boatcast_lap_page,
    boatcast_lap_fetch_due_at,
    parse_boatcast_lap,
)
from boat_analysis.services.official_results import OfficialResultParseError

THREE_COLUMN_LAP = """data=
1\t3
一　周\tまわり足\t直　線
1\t選手一\t37.20\t6.37\t7.30
2\t選手二\t37.10\t6.33\t7.20
3\t選手三\t36.97\t6.37\t7.26
4\t選手四\t37.00\t6.47\t7.17
5\t選手五\t36.90\t6.33\t7.30
6\t選手六\t36.60\t6.77\t7.03
"""

TWO_COLUMN_LAP = """data=
1\t2
一　周\tまわり足
1\t選手一\t36.86\t11.52
2\t選手二\t37.26\t11.38
3\t選手三\t37.47\t11.73
4\t選手四\t37.18\t11.37
5\t選手五\t37.50\t11.51
6\t選手六\t37.27\t11.62
"""

HALF_LAP = """data=
1\t3
半周ラップ\tまわり足\t直　線
1\t選手一\t18.32\t4.63\t7.66
2\t選手二\t18.26\t4.66\t7.51
3\t選手三\t18.38\t4.50\t7.65
4\t選手四\t18.54\t4.66\t7.71
5\t選手五\t18.46\t4.51\t7.58
6\t選手六\t18.44\t4.76\t7.62
"""


def test_parse_three_column_boatcast_lap() -> None:
    result = parse_boatcast_lap(THREE_COLUMN_LAP)

    assert result is not None
    by_lane = {entry.lane: entry for entry in result.entries}
    assert by_lane[1].lap_time_seconds == Decimal("37.20")
    assert by_lane[1].cornering_time_seconds == Decimal("6.37")
    assert by_lane[1].straight_time_seconds == Decimal("7.30")
    assert by_lane[1].half_lap_time_seconds is None


def test_parse_two_column_boatcast_lap() -> None:
    result = parse_boatcast_lap(TWO_COLUMN_LAP)

    assert result is not None
    by_lane = {entry.lane: entry for entry in result.entries}
    assert by_lane[4].lap_time_seconds == Decimal("37.18")
    assert by_lane[4].cornering_time_seconds == Decimal("11.37")
    assert by_lane[4].straight_time_seconds is None


def test_parse_half_lap_boatcast_data() -> None:
    result = parse_boatcast_lap(HALF_LAP)

    assert result is not None
    by_lane = {entry.lane: entry for entry in result.entries}
    assert by_lane[2].half_lap_time_seconds == Decimal("18.26")
    assert by_lane[2].lap_time_seconds is None


def test_boatcast_lap_without_data_is_pending() -> None:
    assert parse_boatcast_lap("data=\n") is None


@pytest.mark.parametrize("status", [403, 404])
def test_unpublished_boatcast_page_is_pending(status: int) -> None:
    error = HTTPError("https://example.invalid", status, "not found", None, None)
    race = Race(
        race_date=datetime(2026, 9, 12).date(),
        venue_code="24",
        race_number=12,
    )

    with patch("boat_analysis.services.official_laps.urlopen", side_effect=error):
        assert _fetch_boatcast_lap_page(race) is None


def test_scratched_boat_is_kept_with_missing_times() -> None:
    scratched = THREE_COLUMN_LAP.replace(
        "2\t選手二\t37.10\t6.33\t7.20",
        "2\t選手二\t欠　場\t\t",
    )

    result = parse_boatcast_lap(scratched)

    assert result is not None
    entry = next(entry for entry in result.entries if entry.lane == 2)
    assert entry.lap_time_seconds is None
    assert entry.cornering_time_seconds is None
    assert entry.straight_time_seconds is None


def test_incomplete_boatcast_lap_is_rejected() -> None:
    incomplete = THREE_COLUMN_LAP.replace(
        "6\t選手六\t36.60\t6.77\t7.03\n",
        "",
    )
    with pytest.raises(OfficialResultParseError, match="incomplete"):
        parse_boatcast_lap(incomplete)


def test_invalid_boatcast_lap_value_is_rejected() -> None:
    malformed = THREE_COLUMN_LAP.replace("37.20", "not-a-time")
    with pytest.raises(OfficialResultParseError, match="invalid"):
        parse_boatcast_lap(malformed)


def test_boatcast_lap_uses_exhibition_fetch_timing() -> None:
    scheduled = datetime(2026, 9, 12, 14, 23, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert boatcast_lap_fetch_due_at(scheduled) == datetime(
        2026,
        9,
        12,
        14,
        18,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
