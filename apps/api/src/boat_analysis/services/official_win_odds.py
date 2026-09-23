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

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import engine
from ..models import Race, RaceEntry, WinOddsObservation
from .official_results import (
    OFFICIAL_RESULT_SOURCE,
    OfficialResultParseError,
    _find_table,
    _normalize_text,
    _parse_int,
    _ResultPageParser,
)

logger = logging.getLogger(__name__)

OFFICIAL_WIN_ODDS_URL = "https://www.boatrace.jp/owpc/pc/race/oddstf"
_WIN_ODDS_REFRESH_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class OfficialWinOddsEntry:
    lane: int
    win_odds: Decimal
    popularity_rank: int


@dataclass(frozen=True, slots=True)
class OfficialWinOdds:
    entries: tuple[OfficialWinOddsEntry, ...]


@dataclass(frozen=True, slots=True)
class OfficialWinOddsRefresh:
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
    match = re.fullmatch(r"\d+(?:\.\d+)?", normalized)
    if match is None:
        return None
    try:
        parsed = Decimal(match.group())
    except InvalidOperation as exc:
        raise OfficialResultParseError("invalid official win odds") from exc
    return parsed


def parse_official_win_odds(html: str) -> OfficialWinOdds | None:
    parser = _ResultPageParser()
    parser.feed(html)

    odds_table = _find_table(parser.tables, {"ボートレーサー", "単勝オッズ"})
    if odds_table is None:
        return None
    table, header_index = odds_table
    headers = table[header_index]
    odds_index = headers.index("単勝オッズ")
    odds_by_lane: dict[int, Decimal] = {}
    scratched_lanes: set[int] = set()
    for row in table[header_index + 1 :]:
        if len(row) <= odds_index:
            continue
        lane = _parse_int(row[0])
        if lane is None or not 1 <= lane <= 6:
            continue
        if _normalize_text(row[odds_index]) == "欠場":
            scratched_lanes.add(lane)
            continue
        odds = _decimal(row[odds_index])
        if odds is None:
            continue
        odds_by_lane[lane] = odds

    if not odds_by_lane and not scratched_lanes:
        return None
    if len(odds_by_lane) + len(scratched_lanes) != 6:
        raise OfficialResultParseError("official win odds table is incomplete")

    ranked_lanes = {lane: odds for lane, odds in odds_by_lane.items() if odds > 0}
    zero_odds_lanes = [lane for lane, odds in odds_by_lane.items() if odds == 0]

    popularity_by_lane = {
        lane: rank
        for rank, (lane, _) in enumerate(
            sorted(ranked_lanes.items(), key=lambda item: (item[1], item[0])),
            start=1,
        )
    }
    for lane in zero_odds_lanes:
        popularity_by_lane[lane] = 6
    return OfficialWinOdds(
        entries=tuple(
            OfficialWinOddsEntry(
                lane=lane,
                win_odds=odds_by_lane[lane],
                popularity_rank=popularity_by_lane[lane],
            )
            for lane in sorted(odds_by_lane)
        )
    )


def win_odds_fetch_due_at(scheduled_at: datetime) -> datetime:
    return scheduled_at - timedelta(minutes=get_settings().official_win_odds_lead_minutes)


def _fetch_official_win_odds_page(race: Race) -> str:
    settings = get_settings()
    query = urlencode(
        {
            "rno": race.race_number,
            "jcd": race.venue_code,
            "hd": race.race_date.strftime("%Y%m%d"),
        }
    )
    request = Request(
        f"{OFFICIAL_WIN_ODDS_URL}?{query}",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "BoatExhibitionAnalysis/0.1 local-win-odds-checker",
        },
    )
    with urlopen(request, timeout=settings.official_win_odds_timeout_seconds) as response:
        content = response.read(settings.official_result_max_response_bytes + 1)
        if len(content) > settings.official_result_max_response_bytes:
            raise RuntimeError("official win odds response exceeded the size limit")
        charset = response.headers.get_content_charset() or "utf-8"
        return content.decode(charset, errors="strict")


def _upsert_official_win_odds(
    session: Session,
    race: Race,
    parsed: OfficialWinOdds,
    checked_at: datetime,
) -> None:
    entry_map = dict(
        session.execute(
            select(RaceEntry.lane, RaceEntry.id).where(RaceEntry.race_id == race.id)
        ).all()
    )
    if set(entry_map) != set(range(1, 7)):
        raise OfficialResultParseError("race entries are incomplete")

    values = [
        {
            "race_entry_id": entry_map[entry.lane],
            "win_odds": entry.win_odds,
            "popularity_rank": entry.popularity_rank,
            "observed_at": checked_at,
            "source_payload": {
                "source": OFFICIAL_RESULT_SOURCE,
                "page": "oddstf",
                "fetched_at": checked_at.isoformat(),
                "timing": "scheduled_at_minus_3_minutes",
            },
        }
        for entry in parsed.entries
    ]
    statement = insert(WinOddsObservation).values(values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["race_entry_id", "observed_at"],
            set_={
                "win_odds": statement.excluded.win_odds,
                "popularity_rank": statement.excluded.popularity_rank,
                "source_payload": statement.excluded.source_payload,
            },
        )
    )


def refresh_official_win_odds(
    race_date: date | None = None,
    *,
    now: datetime | None = None,
    fetch_page: Callable[[Race], str] = _fetch_official_win_odds_page,
) -> OfficialWinOddsRefresh:
    if not _WIN_ODDS_REFRESH_LOCK.acquire(blocking=False):
        return OfficialWinOddsRefresh(already_running=True)

    settings = get_settings()
    timezone = ZoneInfo(settings.app_timezone)
    checked_at = now or datetime.now(timezone)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone)
    else:
        checked_at = checked_at.astimezone(timezone)
    target_date = race_date or checked_at.date()
    due_before = checked_at + timedelta(minutes=settings.official_win_odds_lead_minutes)
    retry_before = checked_at - timedelta(minutes=settings.official_win_odds_retry_minutes)
    checked = imported = pending = errors = 0
    try:
        with Session(engine) as session:
            races = session.scalars(
                select(Race)
                .where(
                    Race.race_date == target_date,
                    Race.scheduled_at.is_not(None),
                    Race.scheduled_at <= due_before,
                    Race.official_win_odds_fetched_at.is_(None),
                    or_(
                        Race.official_win_odds_checked_at.is_(None),
                        Race.official_win_odds_checked_at <= retry_before,
                    ),
                )
                .order_by(
                    Race.scheduled_at.desc(),
                    Race.venue_code,
                    Race.race_number,
                )
                .limit(settings.official_win_odds_max_requests_per_refresh)
            ).all()

            for index, race in enumerate(races):
                if index:
                    time.sleep(settings.official_win_odds_request_interval_seconds)
                checked += 1
                try:
                    parsed = parse_official_win_odds(fetch_page(race))
                    race.official_win_odds_checked_at = checked_at
                    if parsed is None:
                        pending += 1
                    else:
                        _upsert_official_win_odds(session, race, parsed, checked_at)
                        race.official_win_odds_fetched_at = checked_at
                        imported += 1
                    session.commit()
                except Exception as exc:
                    session.rollback()
                    errors += 1
                    persisted_race = session.get(Race, race.id)
                    if persisted_race is not None:
                        persisted_race.official_win_odds_checked_at = checked_at
                        session.commit()
                    logger.warning(
                        "Official win odds check failed for %s venue=%s race=%s: %s",
                        target_date.isoformat(),
                        race.venue_code,
                        race.race_number,
                        exc,
                    )
                    if isinstance(exc, (TimeoutError, URLError)):
                        break

        return OfficialWinOddsRefresh(
            eligible_races=len(races),
            checked_races=checked,
            imported_races=imported,
            pending_races=pending,
            errors_count=errors,
        )
    finally:
        _WIN_ODDS_REFRESH_LOCK.release()
