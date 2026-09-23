import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import engine
from ..models import ExhibitionObservation, Race, RaceEntry
from .official_results import OfficialResultParseError
from .scoring import NO_LAP_EXHIBITION_VENUES

logger = logging.getLogger(__name__)

BOATCAST_LAP_SOURCE = "race.boatcast.jp"
BOATCAST_LAP_URL = "https://race.boatcast.jp/txt"
_BOATCAST_LAP_REFRESH_LOCK = Lock()
_FIELD_BY_HEADER = {
    "半周": "half_lap_time_seconds",
    "半周ラップ": "half_lap_time_seconds",
    "一周": "lap_time_seconds",
    "まわり足": "cornering_time_seconds",
    "直線": "straight_time_seconds",
}


@dataclass(frozen=True, slots=True)
class BoatcastLapEntry:
    lane: int
    half_lap_time_seconds: Decimal | None = None
    lap_time_seconds: Decimal | None = None
    cornering_time_seconds: Decimal | None = None
    straight_time_seconds: Decimal | None = None


@dataclass(frozen=True, slots=True)
class BoatcastLap:
    entries: tuple[BoatcastLapEntry, ...]


@dataclass(frozen=True, slots=True)
class BoatcastLapRefresh:
    eligible_races: int = 0
    checked_races: int = 0
    imported_races: int = 0
    pending_races: int = 0
    errors_count: int = 0
    already_running: bool = False


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", "", value.replace("\u3000", ""))


def _decimal(value: str) -> Decimal | None:
    normalized = re.sub(r"\s+", "", value)
    if not normalized or normalized in {"-", "—", "欠場"}:
        return None
    try:
        parsed = Decimal(normalized)
    except InvalidOperation as exc:
        raise OfficialResultParseError("invalid Boatcast lap value") from exc
    return parsed if parsed > 0 else None


def parse_boatcast_lap(text: str) -> BoatcastLap | None:
    lines = [line.strip("\ufeff\r\n") for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if any(_normalize_header(cell) in _FIELD_BY_HEADER for cell in line.split("\t"))
        ),
        None,
    )
    if header_index is None:
        return None

    headers = lines[header_index].split("\t")
    fields = [_FIELD_BY_HEADER.get(_normalize_header(header)) for header in headers]
    if not any(field in {"half_lap_time_seconds", "lap_time_seconds"} for field in fields):
        raise OfficialResultParseError("Boatcast lap segment column is missing")
    if "cornering_time_seconds" not in fields:
        raise OfficialResultParseError("Boatcast cornering column is missing")

    entries: dict[int, BoatcastLapEntry] = {}
    for line in lines[header_index + 1 :]:
        cells = line.split("\t")
        if len(cells) < len(headers) + 2 or not cells[0].strip().isdigit():
            continue
        lane = int(cells[0].strip())
        if not 1 <= lane <= 6:
            continue
        values = {
            field: _decimal(cells[index + 2])
            for index, field in enumerate(fields)
            if field is not None
        }
        entries[lane] = BoatcastLapEntry(lane=lane, **values)

    if not entries:
        return None
    if len(entries) != 6:
        raise OfficialResultParseError("Boatcast lap table is incomplete")
    return BoatcastLap(entries=tuple(entries[lane] for lane in sorted(entries)))


def boatcast_lap_fetch_due_at(scheduled_at: datetime) -> datetime:
    return scheduled_at - timedelta(minutes=get_settings().official_exhibition_lead_minutes)


def _fetch_boatcast_lap_page(race: Race) -> str | None:
    settings = get_settings()
    venue = race.venue_code.zfill(2)
    filename = f"bc_oriten_{race.race_date:%Y%m%d}_{venue}_{race.race_number:02d}.txt"
    request = Request(
        f"{BOATCAST_LAP_URL}/{venue}/{filename}",
        headers={
            "Accept": "text/plain",
            "User-Agent": "BoatExhibitionAnalysis/0.1 local-lap-checker",
        },
    )
    try:
        with urlopen(request, timeout=settings.boatcast_lap_timeout_seconds) as response:
            content = response.read(settings.official_result_max_response_bytes + 1)
            if len(content) > settings.official_result_max_response_bytes:
                raise RuntimeError("Boatcast lap response exceeded the size limit")
            charset = response.headers.get_content_charset() or "utf-8"
            return content.decode(charset, errors="strict")
    except HTTPError as exc:
        if exc.code in {403, 404}:
            return None
        raise


def _upsert_boatcast_lap(
    session: Session,
    race: Race,
    parsed: BoatcastLap,
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
            "half_lap_time_seconds": entry.half_lap_time_seconds,
            "lap_time_seconds": entry.lap_time_seconds,
            "cornering_time_seconds": entry.cornering_time_seconds,
            "straight_time_seconds": entry.straight_time_seconds,
            "observed_at": race.scheduled_at,
            "source_payload": {},
            "lap_source_payload": {
                "source": BOATCAST_LAP_SOURCE,
                "page": "bc_oriten",
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
                "half_lap_time_seconds": statement.excluded.half_lap_time_seconds,
                "lap_time_seconds": statement.excluded.lap_time_seconds,
                "cornering_time_seconds": statement.excluded.cornering_time_seconds,
                "straight_time_seconds": statement.excluded.straight_time_seconds,
                "lap_source_payload": statement.excluded.lap_source_payload,
            },
        )
    )


def refresh_boatcast_laps(
    race_date: date | None = None,
    *,
    now: datetime | None = None,
    fetch_page: Callable[[Race], str | None] = _fetch_boatcast_lap_page,
) -> BoatcastLapRefresh:
    if not _BOATCAST_LAP_REFRESH_LOCK.acquire(blocking=False):
        return BoatcastLapRefresh(already_running=True)

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
                    Race.venue_code.not_in(NO_LAP_EXHIBITION_VENUES),
                    Race.scheduled_at.is_not(None),
                    Race.scheduled_at <= due_before,
                    Race.boatcast_lap_fetched_at.is_(None),
                    or_(
                        Race.boatcast_lap_checked_at.is_(None),
                        Race.boatcast_lap_checked_at <= retry_before,
                    ),
                )
                .order_by(
                    Race.scheduled_at.desc(),
                    Race.venue_code,
                    Race.race_number,
                )
                .limit(settings.boatcast_lap_max_requests_per_refresh)
            ).all()

            for index, race in enumerate(races):
                if index:
                    time.sleep(settings.boatcast_lap_request_interval_seconds)
                checked += 1
                try:
                    content = fetch_page(race)
                    parsed = parse_boatcast_lap(content) if content is not None else None
                    race.boatcast_lap_checked_at = checked_at
                    if parsed is None:
                        pending += 1
                    else:
                        _upsert_boatcast_lap(session, race, parsed, checked_at)
                        race.boatcast_lap_fetched_at = checked_at
                        imported += 1
                    session.commit()
                except Exception as exc:
                    session.rollback()
                    errors += 1
                    persisted_race = session.get(Race, race.id)
                    if persisted_race is not None:
                        persisted_race.boatcast_lap_checked_at = checked_at
                        session.commit()
                    logger.warning(
                        "Boatcast lap check failed for %s venue=%s race=%s: %s",
                        target_date.isoformat(),
                        race.venue_code,
                        race.race_number,
                        exc,
                    )
                    if isinstance(exc, (TimeoutError, URLError)):
                        break

        return BoatcastLapRefresh(
            eligible_races=len(races),
            checked_races=checked,
            imported_races=imported,
            pending_races=pending,
            errors_count=errors,
        )
    finally:
        _BOATCAST_LAP_REFRESH_LOCK.release()
