from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from boat_analysis.models import Race, TicketNotification, Venue, WeatherObservation
from boat_analysis.services.telegram_notifications import (
    _attempt_is_due,
    _odds_are_ready,
    format_ticket_notification,
)


def test_ticket_notification_includes_tickets_and_weather() -> None:
    race = Race(
        id=uuid4(),
        source_id="202610040201",
        race_date=date(2026, 10, 4),
        venue_code="02",
        race_number=1,
        scheduled_at=datetime(2026, 10, 4, 10, 47, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    race.venue = Venue(code="02", name="戸田")
    weather = WeatherObservation(
        race_id=race.id,
        weather="晴",
        air_temperature_c=Decimal("24.5"),
        water_temperature_c=Decimal("22.0"),
        wind_direction="北",
        wind_speed_mps=Decimal("3.0"),
        wave_height_cm=4,
        observed_at=datetime(2026, 10, 4, 10, 45, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    flow = {
        "tickets": [
            {
                "combination": (1, 2, 3),
                "odds": Decimal("12.4"),
                "popularity_rank": 5,
            }
        ],
        "likely_lanes": [2, 3],
        "likely_two_three_condition": True,
        "composite_odds": Decimal("12.4"),
    }

    message = format_ticket_notification(
        race,
        flow,
        weather,
        timezone=ZoneInfo("Asia/Tokyo"),
    )

    assert "戸田 1R" in message
    assert "締切予定: 10:47" in message
    assert "1-2-3（12.4倍 / 5番人気）" in message
    assert "注目条件: 1-2-3 / 1-3-2参考条件に該当" in message
    assert "LIVE検証では利益優位性を確認できていません" in message
    assert "天候: 晴" in message
    assert "気温/水温: 24.5℃ / 22.0℃" in message
    assert "風: 北 3.0m/s" in message
    assert "波高: 4cm" in message
    assert "的中・利益を保証しません" in message


def test_ticket_notification_marks_missing_weather() -> None:
    race = Race(
        id=uuid4(),
        source_id="202610040202",
        race_date=date(2026, 10, 4),
        venue_code="02",
        race_number=2,
        scheduled_at=datetime(2026, 10, 4, 11, 17, tzinfo=UTC),
    )
    race.venue = Venue(code="02", name="戸田")

    message = format_ticket_notification(
        race,
        {"tickets": [{"combination": (1, 2, 3)}], "likely_lanes": []},
        None,
        timezone=ZoneInfo("Asia/Tokyo"),
    )

    assert "気象: 未取得" in message


def test_sent_notification_is_never_retried() -> None:
    notification = TicketNotification(
        race_id=uuid4(),
        channel="telegram",
        status="sent",
        attempts=1,
        last_attempt_at=datetime.now(UTC) - timedelta(hours=1),
    )

    assert not _attempt_is_due(
        notification,
        retry_before=datetime.now(UTC),
    )


def test_failed_notification_retries_only_after_interval() -> None:
    now = datetime.now(UTC)
    notification = TicketNotification(
        race_id=uuid4(),
        channel="telegram",
        status="failed",
        attempts=1,
        last_attempt_at=now - timedelta(minutes=2),
    )

    assert not _attempt_is_due(
        notification,
        retry_before=now - timedelta(minutes=5),
    )
    notification.last_attempt_at = now - timedelta(minutes=6)
    assert _attempt_is_due(
        notification,
        retry_before=now - timedelta(minutes=5),
    )


def test_notification_waits_for_all_odds_data() -> None:
    race = Race(
        id=uuid4(),
        source_id="202610040203",
        race_date=date(2026, 10, 4),
        venue_code="02",
        race_number=3,
        scheduled_at=datetime(2026, 10, 4, 11, 48, tzinfo=UTC),
    )
    flow = {
        "win_odds_source": "boatrace.jp",
        "popularity_source": "official_trifecta",
        "tickets": [{"combination": (1, 2, 3), "odds": Decimal("12.4")}],
    }

    assert not _odds_are_ready(race, flow)

    race.official_trifecta_odds_fetched_at = datetime.now(UTC)
    assert _odds_are_ready(race, flow)

    flow["tickets"][0]["odds"] = None
    assert not _odds_are_ready(race, flow)

    flow["tickets"][0]["odds"] = Decimal("12.4")
    flow["popularity_source"] = "unavailable_zero_win_odds"
    assert not _odds_are_ready(race, flow)
