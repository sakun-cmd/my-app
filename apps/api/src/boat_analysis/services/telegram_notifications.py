import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..database import engine
from ..models import Race, TicketNotification, WeatherObservation
from .two_boat_flow import analyze_races_two_boat_flow

logger = logging.getLogger(__name__)

TELEGRAM_CHANNEL = "telegram"
_NOTIFICATION_LOCK = Lock()


class TelegramDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TicketNotificationRefresh:
    eligible_races: int = 0
    sent_notifications: int = 0
    skipped_notifications: int = 0
    errors_count: int = 0
    disabled: bool = False
    configuration_missing: bool = False
    already_running: bool = False


def _display_decimal(value: Decimal | str | int | None, suffix: str = "") -> str:
    if value is None:
        return "未取得"
    return f"{value}{suffix}"


def _latest_weather(race: Race) -> WeatherObservation | None:
    eligible = [
        observation
        for observation in race.weather_observations
        if race.scheduled_at is None or observation.observed_at <= race.scheduled_at
    ]
    return max(eligible, key=lambda item: item.observed_at) if eligible else None


def format_ticket_notification(
    race: Race,
    flow: dict,
    weather: WeatherObservation | None,
    *,
    timezone: ZoneInfo,
) -> str:
    scheduled = (
        race.scheduled_at.astimezone(timezone).strftime("%H:%M")
        if race.scheduled_at is not None
        else "未登録"
    )
    ticket_lines = []
    tickets = flow.get("tickets", [])
    for ticket in tickets[:20]:
        combination = "-".join(str(lane) for lane in ticket["combination"])
        details = []
        if ticket.get("odds") is not None:
            details.append(f"{ticket['odds']}倍")
        if ticket.get("popularity_rank") is not None:
            details.append(f"{ticket['popularity_rank']}番人気")
        ticket_lines.append(f"・{combination}" + (f"（{' / '.join(details)}）" if details else ""))
    if len(tickets) > 20:
        ticket_lines.append(f"・ほか{len(tickets) - 20}点")

    weather_lines = (
        [
            f"天候: {weather.weather or '未取得'}",
            (
                "気温/水温: "
                f"{_display_decimal(weather.air_temperature_c, '℃')} / "
                f"{_display_decimal(weather.water_temperature_c, '℃')}"
            ),
            (
                "風: "
                f"{weather.wind_direction or '未取得'} "
                f"{_display_decimal(weather.wind_speed_mps, 'm/s')}"
            ),
            f"波高: {_display_decimal(weather.wave_height_cm, 'cm')}",
        ]
        if weather is not None
        else ["気象: 未取得"]
    )
    likely_lanes = ",".join(str(lane) for lane in flow.get("likely_lanes", [])) or "なし"
    condition_lines = (
        [
            "注目条件: 1-2-3 / 1-3-2参考条件に該当",
            "※LIVE検証では利益優位性を確認できていません",
        ]
        if flow.get("likely_two_three_condition")
        else []
    )
    venue_name = race.venue.name if race.venue is not None else race.venue_code
    return "\n".join(
        [
            "🚤 買い目候補を作成しました",
            f"{race.race_date:%Y-%m-%d} {venue_name} {race.race_number}R",
            f"締切予定: {scheduled}",
            f"注目艇: {likely_lanes}",
            *condition_lines,
            f"買い目（3連単・{len(tickets)}点）",
            *ticket_lines,
            f"合成オッズ: {_display_decimal(flow.get('composite_odds'), '倍')}",
            "",
            "【気象状況】",
            *weather_lines,
            "",
            "統計的な判断材料であり、的中・利益を保証しません。",
        ]
    )


def _safe_delivery_error(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"Telegram HTTP {exc.code}"
    if isinstance(exc, (TimeoutError, URLError)):
        return "Telegram network error"
    if isinstance(exc, TelegramDeliveryError):
        return str(exc)
    return f"Telegram {type(exc).__name__}"


def _send_telegram_message(token: str, chat_id: str, text: str, timeout: float) -> None:
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urlencode(
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "BoatExhibitionAnalysis/0.1 telegram-notifier",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(65_537)
            if len(payload) > 65_536:
                raise TelegramDeliveryError("Telegram response exceeded the size limit")
    except Exception as exc:
        raise TelegramDeliveryError(_safe_delivery_error(exc)) from exc

    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TelegramDeliveryError("Telegram returned an invalid response") from exc
    if not decoded.get("ok"):
        raise TelegramDeliveryError("Telegram rejected the notification")


def _attempt_is_due(
    notification: TicketNotification,
    *,
    retry_before: datetime,
) -> bool:
    if notification.status == "sent":
        return False
    if notification.last_attempt_at is None:
        return True
    return notification.last_attempt_at <= retry_before


def _odds_are_ready(race: Race, flow: dict) -> bool:
    tickets = flow.get("tickets", [])
    return bool(
        race.official_trifecta_odds_fetched_at is not None
        and flow.get("win_odds_source") == "boatrace.jp"
        and flow.get("popularity_source") == "official_trifecta"
        and tickets
        and all(ticket.get("odds") is not None for ticket in tickets)
    )


def refresh_ticket_notifications(
    race_date: date | None = None,
    *,
    now: datetime | None = None,
    send_message: Callable[[str, str, str, float], None] = _send_telegram_message,
) -> TicketNotificationRefresh:
    settings = get_settings()
    if not settings.telegram_notifications_enabled:
        return TicketNotificationRefresh(disabled=True)
    if (
        settings.telegram_bot_token is None
        or not settings.telegram_bot_token.get_secret_value()
        or not settings.telegram_chat_id
    ):
        return TicketNotificationRefresh(configuration_missing=True)
    if not _NOTIFICATION_LOCK.acquire(blocking=False):
        return TicketNotificationRefresh(already_running=True)

    timezone = ZoneInfo(settings.app_timezone)
    checked_at = now or datetime.now(timezone)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone)
    else:
        checked_at = checked_at.astimezone(timezone)
    target_date = race_date or checked_at.date()
    retry_before = checked_at - timedelta(
        minutes=settings.telegram_notification_retry_minutes
    )
    late_cutoff = checked_at - timedelta(
        minutes=settings.telegram_notification_late_grace_minutes
    )
    sent = skipped = errors = 0
    token = settings.telegram_bot_token.get_secret_value()

    try:
        with Session(engine) as session:
            races = list(
                session.scalars(
                    select(Race)
                    .where(
                        Race.race_date == target_date,
                        Race.scheduled_at.is_not(None),
                        Race.scheduled_at >= late_cutoff,
                    )
                    .options(
                        selectinload(Race.venue),
                        selectinload(Race.weather_observations),
                        selectinload(Race.result),
                    )
                    .order_by(Race.scheduled_at, Race.venue_code, Race.race_number)
                ).all()
            )
            flows = analyze_races_two_boat_flow(races, session)
            existing = {
                notification.race_id: notification
                for notification in session.scalars(
                    select(TicketNotification).where(
                        TicketNotification.race_id.in_([race.id for race in races]),
                        TicketNotification.channel == TELEGRAM_CHANNEL,
                    )
                ).all()
            }

            eligible = 0
            for race in races:
                flow = flows.get(race.id)
                if (
                    not flow
                    or not flow.get("tickets")
                    or not _odds_are_ready(race, flow)
                    or (race.result is not None and race.result.finalized_at is not None)
                ):
                    continue
                eligible += 1
                notification = existing.get(race.id)
                if notification is not None and not _attempt_is_due(
                    notification,
                    retry_before=retry_before,
                ):
                    skipped += 1
                    continue

                if notification is None:
                    notification_id = session.scalar(
                        insert(TicketNotification)
                        .values(
                            race_id=race.id,
                            channel=TELEGRAM_CHANNEL,
                            status="pending",
                            attempts=1,
                            first_detected_at=checked_at,
                            last_attempt_at=checked_at,
                        )
                        .on_conflict_do_nothing(
                            index_elements=["race_id", "channel"],
                        )
                        .returning(TicketNotification.id)
                    )
                    session.commit()
                    if notification_id is None:
                        skipped += 1
                        continue
                    notification = session.get(TicketNotification, notification_id)
                    existing[race.id] = notification
                else:
                    notification.status = "pending"
                    notification.attempts += 1
                    notification.last_attempt_at = checked_at
                    notification.last_error = None
                    session.commit()

                message = format_ticket_notification(
                    race,
                    flow,
                    _latest_weather(race),
                    timezone=timezone,
                )
                try:
                    send_message(
                        token,
                        settings.telegram_chat_id,
                        message,
                        settings.telegram_notification_timeout_seconds,
                    )
                    notification.status = "sent"
                    notification.sent_at = checked_at
                    notification.last_error = None
                    sent += 1
                except Exception as exc:
                    notification.status = "failed"
                    notification.last_error = _safe_delivery_error(exc)
                    errors += 1
                    logger.warning(
                        "Telegram ticket notification failed for %s venue=%s race=%s: %s",
                        race.race_date.isoformat(),
                        race.venue_code,
                        race.race_number,
                        notification.last_error,
                    )
                session.commit()

            return TicketNotificationRefresh(
                eligible_races=eligible,
                sent_notifications=sent,
                skipped_notifications=skipped,
                errors_count=errors,
            )
    finally:
        _NOTIFICATION_LOCK.release()
