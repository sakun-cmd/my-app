import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from threading import Lock
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import engine
from ..models import ExhibitionObservation, Race, RaceEntry
from .official_results import (
    OFFICIAL_RESULT_SOURCE,
    OfficialResultParseError,
    _find_table,
    _normalize_text,
    _parse_int,
    _parse_start_timing,
    _ResultPageParser,
)

logger = logging.getLogger(__name__)

OFFICIAL_EXHIBITION_URL = "https://www.boatrace.jp/owpc/pc/race/beforeinfo"
_EXHIBITION_REFRESH_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class OfficialExhibitionEntry:
    lane: int
    exhibition_time_seconds: Decimal
    tilt: Decimal | None
    exhibition_course: int | None
    exhibition_start_timing: Decimal | None


@dataclass(frozen=True, slots=True)
class OfficialExhibition:
    entries: tuple[OfficialExhibitionEntry, ...]


@dataclass(frozen=True, slots=True)
class OfficialExhibitionRefresh:
    eligible_races: int = 0
    checked_races: int = 0
    imported_races: int = 0
    pending_races: int = 0
    errors_count: int = 0
    already_running: bool = False


def _decimal(value: str) -> Decimal | None:
    normalized = _normalize_text(value)
    if not normalized or normalized in {"-", "—"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if match is None:
        return None
    try:
        return Decimal(match.group())
    except InvalidOperation as exc:
        raise OfficialResultParseError("invalid official exhibition number") from exc


def parse_official_exhibition(html: str) -> OfficialExhibition | None:
    parser = _ResultPageParser()
    parser.feed(html)

    detail_table = _find_table(parser.tables, {"枠", "展示タイム", "チルト"})
    if detail_table is None:
        return None
    table, header_index = detail_table
    headers = table[header_index]
    lane_index = headers.index("枠")
    time_index = headers.index("展示タイム")
    tilt_index = headers.index("チルト")
    details: dict[int, tuple[Decimal, Decimal | None]] = {}
    for row in table[header_index + 1 :]:
        if len(row) <= max(lane_index, time_index, tilt_index):
            continue
        lane = _parse_int(row[lane_index])
        exhibition_time = _decimal(row[time_index])
        if lane is None or not 1 <= lane <= 6 or exhibition_time is None:
            continue
        details[lane] = (exhibition_time, _decimal(row[tilt_index]))

    if not details:
        return None
    if len(details) != 6:
        raise OfficialResultParseError("official exhibition table is incomplete")

    starts: dict[int, tuple[int, Decimal | None]] = {}
    start_table = _find_table(parser.tables, {"スタート展示"})
    if start_table is not None:
        table, header_index = start_table
        for row in table[header_index + 1 :]:
            text = _normalize_text(" ".join(row))
            match = re.match(r"^(?P<lane>[1-6])(?=\s|[FL]?\.)", text)
            if match is None:
                continue
            lane = int(match.group("lane"))
            starts[lane] = (
                len(starts) + 1,
                _parse_start_timing(text[match.end() :]),
            )

    return OfficialExhibition(
        entries=tuple(
            OfficialExhibitionEntry(
                lane=lane,
                exhibition_time_seconds=details[lane][0],
                tilt=details[lane][1],
                exhibition_course=starts.get(lane, (None, None))[0],
                exhibition_start_timing=starts.get(lane, (None, None))[1],
            )
            for lane in sorted(details)
        )
    )


def exhibition_fetch_due_at(scheduled_at: datetime) -> datetime:
    return scheduled_at - timedelta(minutes=get_settings().official_exhibition_lead_minutes)


def _fetch_official_exhibition_page(race: Race) -> str:
    settings = get_settings()
    query = urlencode(
        {
            "rno": race.race_number,
            "jcd": race.venue_code,
            "hd": race.race_date.strftime("%Y%m%d"),
        }
    )
    request = Request(
        f"{OFFICIAL_EXHIBITION_URL}?{query}",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "BoatExhibitionAnalysis/0.1 local-exhibition-checker",
        },
    )
    with urlopen(request, timeout=settings.official_exhibition_timeout_seconds) as response:
        content = response.read(settings.official_result_max_response_bytes + 1)
        if len(content) > settings.official_result_max_response_bytes:
            raise RuntimeError("official exhibition response exceeded the size limit")
        charset = response.headers.get_content_charset() or "utf-8"
        return content.decode(charset, errors="strict")


def _upsert_official_exhibition(
    session: Session,
    race: Race,
    parsed: OfficialExhibition,
    checked_at: datetime,
) -> None:
    entry_map = dict(
        session.execute(
            select(RaceEntry.lane, RaceEntry.id).where(RaceEntry.race_id == race.id)
        ).all()
    )
    if set(entry_map) != set(range(1, 7)):
        raise OfficialResultParseError("race entries are incomplete")
    if race.scheduled_at is None:
        raise OfficialResultParseError("race is missing scheduled_at")

    values = [
        {
            "race_entry_id": entry_map[entry.lane],
            "exhibition_course": entry.exhibition_course,
            "exhibition_start_timing": entry.exhibition_start_timing,
            "exhibition_time_seconds": entry.exhibition_time_seconds,
            "tilt": entry.tilt,
            "observed_at": race.scheduled_at,
            "source_payload": {
                "source": OFFICIAL_RESULT_SOURCE,
                "page": "beforeinfo",
                "fetched_at": checked_at.isoformat(),
                "observed_at_strategy": "scheduled_at",
            },
        }
        for entry in parsed.entries
    ]
    statement = insert(ExhibitionObservation).values(values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["race_entry_id", "observed_at"],
            set_={
                "exhibition_course": func.coalesce(
                    statement.excluded.exhibition_course,
                    ExhibitionObservation.exhibition_course,
                ),
                "exhibition_start_timing": func.coalesce(
                    statement.excluded.exhibition_start_timing,
                    ExhibitionObservation.exhibition_start_timing,
                ),
                "exhibition_time_seconds": statement.excluded.exhibition_time_seconds,
                "tilt": func.coalesce(statement.excluded.tilt, ExhibitionObservation.tilt),
                "source_payload": statement.excluded.source_payload,
            },
        )
    )


def refresh_official_exhibitions(
    race_date: date | None = None,
    *,
    now: datetime | None = None,
    fetch_page: Callable[[Race], str] = _fetch_official_exhibition_page,
) -> OfficialExhibitionRefresh:
    if not _EXHIBITION_REFRESH_LOCK.acquire(blocking=False):
        return OfficialExhibitionRefresh(already_running=True)

    settings = get_settings()
    timezone = ZoneInfo(settings.app_timezone)
    checked_at = now or datetime.now(timezone)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone)
    else:
        checked_at = checked_at.astimezone(timezone)
    target_date = race_date or checked_at.date()
    due_before = checked_at + timedelta(minutes=settings.official_exhibition_lead_minutes)
    retry_before = checked_at - timedelta(minutes=settings.official_exhibition_retry_minutes)
    checked = imported = pending = errors = 0
    try:
        with Session(engine) as session:
            races = session.scalars(
                select(Race)
                .where(
                    Race.race_date == target_date,
                    Race.scheduled_at.is_not(None),
                    Race.scheduled_at <= due_before,
                    Race.official_exhibition_fetched_at.is_(None),
                    or_(
                        Race.official_exhibition_checked_at.is_(None),
                        Race.official_exhibition_checked_at <= retry_before,
                    ),
                )
                .order_by(
                    Race.scheduled_at.desc(),
                    Race.venue_code,
                    Race.race_number,
                )
                .limit(settings.official_exhibition_max_requests_per_refresh)
            ).all()

            for index, race in enumerate(races):
                if index:
                    time.sleep(settings.official_exhibition_request_interval_seconds)
                checked += 1
                try:
                    parsed = parse_official_exhibition(fetch_page(race))
                    race.official_exhibition_checked_at = checked_at
                    if parsed is None:
                        pending += 1
                    else:
                        _upsert_official_exhibition(session, race, parsed, checked_at)
                        race.official_exhibition_fetched_at = checked_at
                        imported += 1
                    session.commit()
                except Exception as exc:
                    session.rollback()
                    errors += 1
                    persisted_race = session.get(Race, race.id)
                    if persisted_race is not None:
                        persisted_race.official_exhibition_checked_at = checked_at
                        session.commit()
                    logger.warning(
                        "Official exhibition check failed for %s venue=%s race=%s: %s",
                        target_date.isoformat(),
                        race.venue_code,
                        race.race_number,
                        exc,
                    )
                    if isinstance(exc, (TimeoutError, URLError)):
                        break

        return OfficialExhibitionRefresh(
            eligible_races=len(races),
            checked_races=checked,
            imported_races=imported,
            pending_races=pending,
            errors_count=errors,
        )
    finally:
        _EXHIBITION_REFRESH_LOCK.release()
