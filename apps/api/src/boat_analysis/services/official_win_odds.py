import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import permutations
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
from ..models import Race, RaceEntry, TrifectaOddsObservation, WinOddsObservation
from .official_results import (
    OFFICIAL_RESULT_SOURCE,
    OfficialResultParseError,
    _normalize_text,
    _parse_int,
    _ResultPageParser,
)

logger = logging.getLogger(__name__)

OFFICIAL_TRIFECTA_ODDS_URL = "https://www.boatrace.jp/owpc/pc/race/odds3t"
_TRIFECTA_ODDS_REFRESH_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class OfficialTrifectaSupport:
    lane: int
    implied_first_place_odds: Decimal
    popularity_rank: int


@dataclass(frozen=True, slots=True)
class OfficialTrifectaOdds:
    odds: dict[tuple[int, int, int], Decimal]
    support: tuple[OfficialTrifectaSupport, ...]


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
    if not normalized or normalized in {"-", "—", "欠場"}:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", normalized) is None:
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise OfficialResultParseError("invalid official trifecta odds") from exc


def _derive_support(
    odds: dict[tuple[int, int, int], Decimal],
    lanes: set[int],
) -> tuple[OfficialTrifectaSupport, ...]:
    support_by_lane = {
        lane: sum(
            (
                Decimal(1) / odds[(lane, second, third)]
                for second, third in permutations(lanes - {lane}, 2)
            ),
            start=Decimal(0),
        )
        for lane in lanes
    }
    popularity_by_lane = {
        lane: rank
        for rank, (lane, _) in enumerate(
            sorted(support_by_lane.items(), key=lambda item: (-item[1], item[0])),
            start=1,
        )
    }
    return tuple(
        OfficialTrifectaSupport(
            lane=lane,
            implied_first_place_odds=(Decimal(1) / support_by_lane[lane]).quantize(
                Decimal("0.1")
            ),
            popularity_rank=popularity_by_lane[lane],
        )
        for lane in sorted(lanes)
    )


def parse_official_trifecta_odds(html: str) -> OfficialTrifectaOdds | None:
    parser = _ResultPageParser()
    parser.feed(html)
    lanes = set(range(1, 7))
    required = set(permutations(lanes, 3))
    best: dict[tuple[int, int, int], Decimal] = {}

    for table in parser.tables:
        if len(table) < 2:
            continue
        header = table[0]
        first_lanes = [_parse_int(header[index]) for index in range(0, len(header), 2)]
        if first_lanes != [1, 2, 3, 4, 5, 6]:
            continue

        candidate: dict[tuple[int, int, int], Decimal] = {}
        second_lanes: dict[int, int] = {}
        for row in table[1:]:
            width = 3 if len(row) == 18 else 2 if len(row) == 12 else 0
            if width == 0:
                continue
            for group, first_lane in enumerate(first_lanes):
                offset = group * width
                if width == 3:
                    second_lane = _parse_int(row[offset])
                    third_index = offset + 1
                    if second_lane is not None:
                        second_lanes[group] = second_lane
                else:
                    second_lane = second_lanes.get(group)
                    third_index = offset
                third_lane = _parse_int(row[third_index])
                value = _decimal(row[third_index + 1])
                if (
                    second_lane is None
                    or third_lane is None
                    or len({first_lane, second_lane, third_lane}) != 3
                    or value is None
                    or value <= 0
                ):
                    continue
                candidate[(first_lane, second_lane, third_lane)] = value
        if len(candidate) > len(best):
            best = candidate

    if not best or not required.issubset(best):
        return None
    complete = {combination: best[combination] for combination in sorted(required)}
    return OfficialTrifectaOdds(
        odds=complete,
        support=_derive_support(complete, lanes),
    )


def trifecta_odds_fetch_due_at(scheduled_at: datetime) -> datetime:
    return scheduled_at - timedelta(
        minutes=get_settings().official_trifecta_odds_lead_minutes
    )


def win_odds_fetch_due_at(scheduled_at: datetime) -> datetime:
    return trifecta_odds_fetch_due_at(scheduled_at)


def _fetch_official_trifecta_odds_page(race: Race) -> str:
    settings = get_settings()
    query = urlencode(
        {
            "rno": race.race_number,
            "jcd": race.venue_code,
            "hd": race.race_date.strftime("%Y%m%d"),
        }
    )
    request = Request(
        f"{OFFICIAL_TRIFECTA_ODDS_URL}?{query}",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "BoatExhibitionAnalysis/0.1 local-trifecta-odds-checker",
        },
    )
    with urlopen(
        request,
        timeout=settings.official_trifecta_odds_timeout_seconds,
    ) as response:
        content = response.read(settings.official_result_max_response_bytes + 1)
        if len(content) > settings.official_result_max_response_bytes:
            raise RuntimeError("official trifecta odds response exceeded the size limit")
        charset = response.headers.get_content_charset() or "utf-8"
        return content.decode(charset, errors="strict")


def _upsert_official_trifecta_odds(
    session: Session,
    race: Race,
    parsed: OfficialTrifectaOdds,
    checked_at: datetime,
) -> None:
    entry_map = dict(
        session.execute(
            select(RaceEntry.lane, RaceEntry.id).where(RaceEntry.race_id == race.id)
        ).all()
    )
    if set(entry_map) != set(range(1, 7)):
        raise OfficialResultParseError("race entries are incomplete")
    if len(parsed.odds) != 120 or len(parsed.support) != 6:
        raise OfficialResultParseError("official trifecta odds table is incomplete")

    source_payload = {
        "source": OFFICIAL_RESULT_SOURCE,
        "page": "odds3t",
        "fetched_at": checked_at.isoformat(),
        "timing": "scheduled_at_minus_3_minutes",
    }
    odds_values = [
        {
            "race_id": race.id,
            "first_lane": combination[0],
            "second_lane": combination[1],
            "third_lane": combination[2],
            "odds": value,
            "observed_at": checked_at,
            "source_payload": source_payload,
        }
        for combination, value in parsed.odds.items()
    ]
    odds_statement = insert(TrifectaOddsObservation).values(odds_values)
    session.execute(
        odds_statement.on_conflict_do_update(
            index_elements=[
                "race_id",
                "first_lane",
                "second_lane",
                "third_lane",
            ],
            set_={
                "odds": odds_statement.excluded.odds,
                "observed_at": odds_statement.excluded.observed_at,
                "source_payload": odds_statement.excluded.source_payload,
            },
        )
    )

    support_values = [
        {
            "race_entry_id": entry_map[item.lane],
            "win_odds": item.implied_first_place_odds,
            "popularity_rank": item.popularity_rank,
            "observed_at": checked_at,
            "source_payload": {
                **source_payload,
                "popularity_source": "official_trifecta",
                "popularity_method": "sum_inverse_first_place_trifecta_odds",
                "value_name": "implied_first_place_odds",
            },
        }
        for item in parsed.support
    ]
    support_statement = insert(WinOddsObservation).values(support_values)
    session.execute(
        support_statement.on_conflict_do_update(
            index_elements=["race_entry_id"],
            set_={
                "win_odds": support_statement.excluded.win_odds,
                "popularity_rank": support_statement.excluded.popularity_rank,
                "observed_at": support_statement.excluded.observed_at,
                "source_payload": support_statement.excluded.source_payload,
            },
        )
    )


def refresh_official_trifecta_odds(
    race_date: date | None = None,
    *,
    now: datetime | None = None,
    fetch_page: Callable[[Race], str] = _fetch_official_trifecta_odds_page,
    sleep: Callable[[float], None] = time.sleep,
) -> OfficialWinOddsRefresh:
    if not _TRIFECTA_ODDS_REFRESH_LOCK.acquire(blocking=False):
        return OfficialWinOddsRefresh(already_running=True)

    settings = get_settings()
    timezone = ZoneInfo(settings.app_timezone)
    checked_at = now or datetime.now(timezone)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone)
    else:
        checked_at = checked_at.astimezone(timezone)
    target_date = race_date or checked_at.date()
    due_before = checked_at + timedelta(
        minutes=settings.official_trifecta_odds_lead_minutes
    )
    retry_before = checked_at - timedelta(
        minutes=settings.official_trifecta_odds_retry_minutes
    )
    checked = imported = pending = errors = 0
    try:
        with Session(engine) as session:
            races = session.scalars(
                select(Race)
                .where(
                    Race.race_date == target_date,
                    Race.scheduled_at.is_not(None),
                    Race.scheduled_at <= due_before,
                    Race.official_trifecta_odds_fetched_at.is_(None),
                    or_(
                        Race.official_trifecta_odds_checked_at.is_(None),
                        Race.official_trifecta_odds_checked_at <= retry_before,
                    ),
                )
                .order_by(
                    Race.scheduled_at.desc(),
                    Race.venue_code,
                    Race.race_number,
                )
                .limit(settings.official_trifecta_odds_max_requests_per_refresh)
            ).all()

            for index, race in enumerate(races):
                if index:
                    sleep(settings.official_trifecta_odds_request_interval_seconds)
                checked += 1
                try:
                    parsed = parse_official_trifecta_odds(fetch_page(race))
                    race.official_trifecta_odds_checked_at = checked_at
                    if parsed is None:
                        pending += 1
                    else:
                        _upsert_official_trifecta_odds(session, race, parsed, checked_at)
                        race.official_trifecta_odds_fetched_at = checked_at
                        imported += 1
                    session.commit()
                except Exception as exc:
                    session.rollback()
                    errors += 1
                    persisted_race = session.get(Race, race.id)
                    if persisted_race is not None:
                        persisted_race.official_trifecta_odds_checked_at = checked_at
                        session.commit()
                    logger.warning(
                        "Official trifecta odds check failed for %s venue=%s race=%s: %s",
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
        _TRIFECTA_ODDS_REFRESH_LOCK.release()


refresh_official_win_odds = refresh_official_trifecta_odds
