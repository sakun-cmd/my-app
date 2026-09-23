import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import engine
from ..models import Race, RaceResult, ResultEntry

logger = logging.getLogger(__name__)

OFFICIAL_RESULT_URL = "https://www.boatrace.jp/owpc/pc/race/raceresult"
OFFICIAL_RESULT_SOURCE = "boatrace.jp"
_RESULT_REFRESH_LOCK = Lock()
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_WINNING_TECHNIQUES = ("まくり差し", "逃げ", "差し", "まくり", "抜き", "恵まれ")
VOID_RACE_MARKER = "不成立"
CANCELLED_RACE_MARKER = "中止"
# Stored in RaceResult.winning_technique for races that ended without a result.
NO_RESULT_MARKERS = (VOID_RACE_MARKER, CANCELLED_RACE_MARKER)
_CANCELLED_PAGE_MARKER = "レース中止"


class OfficialResultParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OfficialResultEntry:
    lane: int
    finish_position: int | None
    actual_course: int | None
    actual_start_timing: Decimal | None
    status: str | None


@dataclass(frozen=True, slots=True)
class OfficialResult:
    winning_technique: str | None
    entries: tuple[OfficialResultEntry, ...]
    trifecta_combination: tuple[int, int, int] | None = None
    trifecta_payout_yen: int | None = None
    trifecta_popularity_rank: int | None = None
    trifecta_refunded: bool = False
    void_marker: str | None = None

    @property
    def void(self) -> bool:
        return self.void_marker is not None


@dataclass(frozen=True, slots=True)
class OfficialResultRefresh:
    eligible_races: int = 0
    checked_races: int = 0
    finalized_races: int = 0
    void_races: int = 0
    pending_races: int = 0
    errors_count: int = 0
    already_running: bool = False


class _ResultPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._rows: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            if self._table_depth == 0:
                self._rows = []
            self._table_depth += 1
        elif self._table_depth == 1 and tag == "tr":
            self._row = []
        elif self._table_depth == 1 and tag in {"th", "td"}:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._table_depth == 1 and tag in {"th", "td"}:
            if self._row is not None and self._cell_parts is not None:
                self._row.append(_normalize_text("".join(self._cell_parts)))
            self._cell_parts = None
        elif self._table_depth == 1 and tag == "tr":
            if self._rows is not None and self._row:
                self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0 and self._rows is not None:
                self.tables.append(self._rows)
                self._rows = None


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _parse_int(value: str) -> int | None:
    normalized = _normalize_text(value).translate(_FULLWIDTH_DIGITS)
    return int(normalized) if normalized.isdigit() else None


def _parse_start_timing(value: str) -> Decimal | None:
    match = re.search(r"(?P<marker>[FL])?\s*(?P<value>\.?\d{1,2})", value.upper())
    if match is None:
        return None
    raw = match.group("value")
    if raw.startswith("."):
        raw = f"0{raw}"
    try:
        timing = Decimal(raw)
    except InvalidOperation as exc:
        raise OfficialResultParseError("invalid official start timing") from exc
    return -timing if match.group("marker") == "F" else timing


def _parse_trifecta(
    tables: list[list[list[str]]],
) -> tuple[tuple[int, int, int] | None, int | None, int | None, bool]:
    payout_table = _find_table(tables, {"勝式", "組番", "払戻金", "人気"})
    if payout_table is None:
        return None, None, None, False
    table, header_index = payout_table
    for row in table[header_index + 1 :]:
        if len(row) < 4 or _normalize_text(row[0]) != "3連単":
            continue
        payout_text = _normalize_text(row[2]).translate(_FULLWIDTH_DIGITS)
        payout_digits = re.sub(r"\D", "", payout_text)
        payout = int(payout_digits) if payout_digits else None
        if "不成立" in _normalize_text(row[1]):
            return None, payout, None, True
        lanes = tuple(int(value) for value in re.findall(r"[1-6]", row[1]))
        if len(lanes) != 3 or len(set(lanes)) != 3:
            raise OfficialResultParseError("invalid official trifecta combination")
        popularity = _parse_int(row[3])
        return lanes, payout, popularity, False
    return None, None, None, False


def _find_table(
    tables: list[list[list[str]]],
    required_headers: set[str],
) -> tuple[list[list[str]], int] | None:
    for table in tables:
        for index, row in enumerate(table):
            if required_headers.issubset(set(row)):
                return table, index
    return None


def parse_official_result(html: str) -> OfficialResult | None:
    parser = _ResultPageParser()
    parser.feed(html)

    finish_table = _find_table(parser.tables, {"着", "枠", "ボートレーサー"})
    if finish_table is None:
        for page_marker, void_marker in (
            (_CANCELLED_PAGE_MARKER, CANCELLED_RACE_MARKER),
            (VOID_RACE_MARKER, VOID_RACE_MARKER),
        ):
            if page_marker in html:
                return OfficialResult(winning_technique=None, entries=(), void_marker=void_marker)
        return None
    table, header_index = finish_table
    finish_rows: dict[int, tuple[int | None, str | None]] = {}
    for row in table[header_index + 1 :]:
        if len(row) < 2:
            continue
        lane = _parse_int(row[1])
        if lane is None or not 1 <= lane <= 6:
            continue
        position = _parse_int(row[0])
        status = None if position is not None else (_normalize_text(row[0]) or None)
        finish_rows[lane] = (position, status)

    if not finish_rows:
        return None
    if len(finish_rows) != 6:
        raise OfficialResultParseError("official result table is incomplete")

    start_table = _find_table(parser.tables, {"スタート情報"})
    starts: dict[int, tuple[int, Decimal | None]] = {}
    winning_technique = None
    if start_table is not None:
        table, header_index = start_table
        for course, row in enumerate(table[header_index + 1 :], start=1):
            text = _normalize_text(" ".join(row))
            match = re.match(r"^(?P<lane>[1-6])(?=\s|[FL]?\.)", text)
            if match is None:
                continue
            lane = int(match.group("lane"))
            starts[lane] = (course, _parse_start_timing(text[match.end() :]))
            if finish_rows[lane][0] == 1:
                winning_technique = next(
                    (technique for technique in _WINNING_TECHNIQUES if technique in text),
                    None,
                )

    entries = tuple(
        OfficialResultEntry(
            lane=lane,
            finish_position=finish_rows[lane][0],
            actual_course=starts.get(lane, (None, None))[0],
            actual_start_timing=starts.get(lane, (None, None))[1],
            status=finish_rows[lane][1],
        )
        for lane in sorted(finish_rows)
    )
    combination, payout, popularity, refunded = _parse_trifecta(parser.tables)
    return OfficialResult(
        winning_technique=winning_technique,
        entries=entries,
        trifecta_combination=combination,
        trifecta_payout_yen=payout,
        trifecta_popularity_rank=popularity,
        trifecta_refunded=refunded,
    )


def result_fetch_due_at(scheduled_at: datetime) -> datetime:
    return scheduled_at + timedelta(minutes=get_settings().official_result_delay_minutes)


def _fetch_official_result_page(race: Race) -> str:
    settings = get_settings()
    query = urlencode(
        {
            "rno": race.race_number,
            "jcd": race.venue_code,
            "hd": race.race_date.strftime("%Y%m%d"),
        }
    )
    request = Request(
        f"{OFFICIAL_RESULT_URL}?{query}",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "BoatExhibitionAnalysis/0.1 local-result-checker",
        },
    )
    with urlopen(request, timeout=settings.official_result_timeout_seconds) as response:
        content = response.read(settings.official_result_max_response_bytes + 1)
        if len(content) > settings.official_result_max_response_bytes:
            raise RuntimeError("official result response exceeded the size limit")
        charset = response.headers.get_content_charset() or "utf-8"
        return content.decode(charset, errors="strict")


def _upsert_official_result(
    session: Session,
    race: Race,
    parsed: OfficialResult,
    checked_at: datetime,
) -> None:
    result = session.scalar(select(RaceResult).where(RaceResult.race_id == race.id))
    if result is None:
        result = RaceResult(race_id=race.id)
        session.add(result)
        session.flush()
    result.winning_technique = parsed.void_marker or parsed.winning_technique
    result.trifecta_combination = (
        "-".join(str(lane) for lane in parsed.trifecta_combination)
        if parsed.trifecta_combination
        else None
    )
    result.trifecta_payout_yen = parsed.trifecta_payout_yen
    result.trifecta_popularity_rank = parsed.trifecta_popularity_rank
    result.trifecta_refunded = parsed.trifecta_refunded
    result.finalized_at = checked_at
    result.source = OFFICIAL_RESULT_SOURCE
    values = [
        {
            "race_result_id": result.id,
            "lane": entry.lane,
            "finish_position": entry.finish_position,
            "actual_course": entry.actual_course,
            "actual_start_timing": entry.actual_start_timing,
            "status": entry.status,
        }
        for entry in parsed.entries
    ]
    if values:
        statement = insert(ResultEntry).values(values)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["race_result_id", "lane"],
                set_={
                    "finish_position": statement.excluded.finish_position,
                    "actual_course": statement.excluded.actual_course,
                    "actual_start_timing": statement.excluded.actual_start_timing,
                    "status": statement.excluded.status,
                },
            )
        )


def refresh_official_results(
    race_date: date | None = None,
    *,
    now: datetime | None = None,
    fetch_page: Callable[[Race], str] = _fetch_official_result_page,
) -> OfficialResultRefresh:
    if not _RESULT_REFRESH_LOCK.acquire(blocking=False):
        return OfficialResultRefresh(already_running=True)

    settings = get_settings()
    timezone = ZoneInfo(settings.app_timezone)
    checked_at = now or datetime.now(timezone)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone)
    else:
        checked_at = checked_at.astimezone(timezone)
    target_date = race_date or checked_at.date()
    due_before = checked_at - timedelta(minutes=settings.official_result_delay_minutes)
    retry_before = checked_at - timedelta(minutes=settings.official_result_retry_minutes)
    checked = finalized = void = pending = errors = 0
    try:
        with Session(engine) as session:
            races = session.scalars(
                select(Race)
                .outerjoin(RaceResult, RaceResult.race_id == Race.id)
                .where(
                    Race.race_date == target_date,
                    Race.scheduled_at.is_not(None),
                    Race.scheduled_at <= due_before,
                    or_(
                        RaceResult.id.is_(None),
                        RaceResult.finalized_at.is_(None),
                        (
                            RaceResult.trifecta_payout_yen.is_(None)
                            & or_(
                                RaceResult.winning_technique.is_(None),
                                RaceResult.winning_technique.not_in(NO_RESULT_MARKERS),
                            )
                        ),
                    ),
                    or_(
                        Race.official_result_checked_at.is_(None),
                        Race.official_result_checked_at <= retry_before,
                    ),
                )
                .order_by(Race.scheduled_at, Race.venue_code, Race.race_number)
                .limit(settings.official_result_max_requests_per_refresh)
            ).all()

            for index, race in enumerate(races):
                if index:
                    time.sleep(settings.official_result_request_interval_seconds)
                checked += 1
                try:
                    parsed = parse_official_result(fetch_page(race))
                    race.official_result_checked_at = checked_at
                    if parsed is None:
                        pending += 1
                    elif parsed.void:
                        _upsert_official_result(session, race, parsed, checked_at)
                        void += 1
                    else:
                        _upsert_official_result(session, race, parsed, checked_at)
                        finalized += 1
                    session.commit()
                except Exception as exc:
                    session.rollback()
                    errors += 1
                    persisted_race = session.get(Race, race.id)
                    if persisted_race is not None:
                        persisted_race.official_result_checked_at = checked_at
                        session.commit()
                    logger.warning(
                        "Official result check failed for %s venue=%s race=%s: %s",
                        target_date.isoformat(),
                        race.venue_code,
                        race.race_number,
                        exc,
                    )

        return OfficialResultRefresh(
            eligible_races=len(races),
            checked_races=checked,
            finalized_races=finalized,
            void_races=void,
            pending_races=pending,
            errors_count=errors,
        )
    finally:
        _RESULT_REFRESH_LOCK.release()
