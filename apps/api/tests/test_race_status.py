from datetime import UTC, datetime, timedelta

import pytest

from boat_analysis.models import Race, RaceResult
from boat_analysis.routers.races import _race_status


def _race(winning_technique: str | None, *, finalized: bool) -> Race:
    race = Race(
        race_date=datetime.now(UTC).date(),
        scheduled_at=datetime.now(UTC) - timedelta(hours=3),
    )
    race.result = RaceResult(
        winning_technique=winning_technique,
        finalized_at=datetime.now(UTC) if finalized else None,
    )
    return race


@pytest.mark.parametrize(
    ("marker", "expected"),
    [("中止", "cancelled"), ("不成立", "void")],
)
def test_finalized_no_result_race_has_its_own_status(marker: str, expected: str) -> None:
    assert _race_status(_race(marker, finalized=True)) == expected


def test_unfinalized_cancelled_marker_is_still_pending() -> None:
    assert _race_status(_race("中止", finalized=False)) == "pending_result"


def test_past_race_without_result_is_pending() -> None:
    race = Race(
        race_date=datetime.now(UTC).date(),
        scheduled_at=datetime.now(UTC) - timedelta(hours=3),
    )

    assert _race_status(race) == "pending_result"
