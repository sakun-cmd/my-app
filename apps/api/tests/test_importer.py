from datetime import UTC, datetime

from boat_analysis.services.importer import _as_datetime


def test_naive_source_timestamp_uses_configured_timezone() -> None:
    value = _as_datetime(datetime(2026, 9, 9, 10, 0))
    assert value.utcoffset().total_seconds() == 9 * 60 * 60


def test_aware_source_timestamp_is_preserved() -> None:
    value = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    assert _as_datetime(value) is value
