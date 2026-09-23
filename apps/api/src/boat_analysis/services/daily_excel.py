import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..database import engine
from ..models import Race, RaceEntry, RaceResult
from .official_results import NO_RESULT_MARKERS
from .scoring import ScoringInput, score_entries
from .two_boat_flow import analyze_races_two_boat_flow

logger = logging.getLogger(__name__)

_EXPORT_LOCK = Lock()
_HEADER_FILL = PatternFill("solid", fgColor="17365D")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_HIT_FILL = PatternFill("solid", fgColor="C6EFCE")


class DailyExcelNotReady(RuntimeError):
    pass


def daily_excel_path(race_date: date) -> Path:
    output_dir = get_settings().daily_excel_output_dir
    return output_dir / f"boat-race-daily-{race_date:%Y%m%d}.xlsx"


def _excel_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "はい" if value else "いいえ"
    return value


def _latest_before(items: list[Any], cutoff: datetime | None) -> Any | None:
    if cutoff is None:
        return None
    eligible = [item for item in items if item.observed_at <= cutoff]
    return eligible[-1] if eligible else None


def _flow_columns(flow: dict[str, Any] | None, race: Race) -> dict[str, Any]:
    result = race.result
    winning = result.trifecta_combination if result else None
    tickets = flow.get("tickets", []) if flow else []
    ticket_by_combination = {
        "-".join(str(lane) for lane in ticket["combination"]): ticket for ticket in tickets
    }
    hit_ticket = ticket_by_combination.get(winning) if winning else None
    stake = len(tickets) * 100
    payout = result.trifecta_payout_yen if result else None
    # Cancelled / void races are refunded in full, so they must not count as losses.
    refunded = bool(
        result and (result.trifecta_refunded or result.winning_technique in NO_RESULT_MARKERS)
    )
    return_yen = stake if refunded else payout if hit_ticket and payout is not None else 0
    if not result or result.finalized_at is None:
        hit_status = "結果未確定"
    elif not tickets:
        hit_status = "買い目なし"
    elif refunded:
        hit_status = "返還"
    elif hit_ticket:
        hit_status = "的中"
    else:
        hit_status = "不的中"
    return {
        "判定状態": flow.get("status") if flow else "データなし",
        "注目艇": ",".join(str(lane) for lane in flow.get("likely_lanes", [])) if flow else "",
        "外艇": flow.get("outer_lane") if flow else None,
        "外の外艇": flow.get("outer_outer_lane") if flow else None,
        "イン逃げ評価": flow.get("escape_assessment") if flow else None,
        "最終判断": flow.get("decision") if flow else None,
        "買い目": " / ".join(ticket_by_combination),
        "買い目詳細": " / ".join(
            (
                f"{combination}"
                f"(オッズ={ticket.get('odds') or '-'},人気={ticket.get('popularity_rank') or '-'})"
            )
            for combination, ticket in ticket_by_combination.items()
        ),
        "買い目数": len(tickets),
        "投資額_各100円": stake,
        "合成オッズ": flow.get("composite_odds") if flow else None,
        "判定手順": " | ".join(
            f"{step['number']}:{step['result']} {step['detail']}" for step in flow.get("steps", [])
        )
        if flow
        else "",
        "単勝オッズ出典": flow.get("win_odds_source") if flow else None,
        "単勝オッズ取得時刻": flow.get("win_odds_observed_at") if flow else None,
        "的中判定": hit_status,
        "的中買い目": winning if hit_ticket else None,
        "的中買い目オッズ": hit_ticket.get("odds") if hit_ticket else None,
        "的中買い目人気": hit_ticket.get("popularity_rank") if hit_ticket else None,
        "払戻額_100円": return_yen,
        "収支_各100円": return_yen - stake,
    }


def _race_row(race: Race, flow: dict[str, Any] | None) -> dict[str, Any]:
    weather = _latest_before(race.weather_observations, race.scheduled_at)
    result_by_lane = {entry.lane: entry for entry in race.result.entries} if race.result else {}
    metric_by_lane = {metric["lane"]: metric for metric in flow.get("metrics", [])} if flow else {}
    latest_exhibitions = {
        entry.lane: _latest_before(entry.exhibitions, race.scheduled_at) for entry in race.entries
    }
    scored = score_entries(
        [
            ScoringInput(
                lane=entry.lane,
                exhibition_time_seconds=(
                    latest_exhibitions[entry.lane].exhibition_time_seconds
                    if latest_exhibitions[entry.lane]
                    else None
                ),
                exhibition_start_timing=(
                    latest_exhibitions[entry.lane].exhibition_start_timing
                    if latest_exhibitions[entry.lane]
                    else None
                ),
                exhibition_course=(
                    latest_exhibitions[entry.lane].exhibition_course
                    if latest_exhibitions[entry.lane]
                    else None
                ),
                half_lap_time_seconds=(
                    latest_exhibitions[entry.lane].half_lap_time_seconds
                    if latest_exhibitions[entry.lane]
                    else None
                ),
                lap_time_seconds=(
                    latest_exhibitions[entry.lane].lap_time_seconds
                    if latest_exhibitions[entry.lane]
                    else None
                ),
                cornering_time_seconds=(
                    latest_exhibitions[entry.lane].cornering_time_seconds
                    if latest_exhibitions[entry.lane]
                    else None
                ),
                straight_time_seconds=(
                    latest_exhibitions[entry.lane].straight_time_seconds
                    if latest_exhibitions[entry.lane]
                    else None
                ),
            )
            for entry in race.entries
        ],
        race.venue_code,
    )
    score_by_lane = {item.lane: item for item in scored}
    row: dict[str, Any] = {
        "開催日": race.race_date,
        "場コード": race.venue_code,
        "場名": race.venue.name,
        "レース": race.race_number,
        "締切予定": race.scheduled_at,
        "グレード": race.grade,
        "距離m": race.distance_m,
        "結果確定時刻": race.result.finalized_at if race.result else None,
        "結果出典": race.result.source if race.result else None,
        "決まり手": race.result.winning_technique if race.result else None,
        "3連単結果": race.result.trifecta_combination if race.result else None,
        "3連単払戻円": race.result.trifecta_payout_yen if race.result else None,
        "3連単人気": race.result.trifecta_popularity_rank if race.result else None,
        "3連単返還": race.result.trifecta_refunded if race.result else None,
        "天候": weather.weather if weather else None,
        "気温C": weather.air_temperature_c if weather else None,
        "水温C": weather.water_temperature_c if weather else None,
        "風向": weather.wind_direction if weather else None,
        "風速m_s": weather.wind_speed_mps if weather else None,
        "波高cm": weather.wave_height_cm if weather else None,
    }
    row.update(_flow_columns(flow, race))

    entries = {entry.lane: entry for entry in race.entries}
    for lane in range(1, 7):
        entry = entries.get(lane)
        prefix = f"{lane}号艇_"
        exhibition = latest_exhibitions.get(lane)
        win_odds = _latest_before(entry.win_odds_observations, race.scheduled_at) if entry else None
        metric = metric_by_lane.get(lane, {})
        score = score_by_lane.get(lane)
        race_result = result_by_lane.get(lane)
        replacements = (
            " / ".join(f"{part.part_name}x{part.quantity}" for part in entry.part_replacements)
            if entry
            else ""
        )
        row.update(
            {
                f"{prefix}登録番号": entry.racer_registration_number if entry else None,
                f"{prefix}選手名": entry.racer.name if entry and entry.racer else None,
                f"{prefix}級別": entry.class_name if entry else None,
                f"{prefix}モーター": entry.motor_number if entry else None,
                f"{prefix}ボート": entry.boat_number if entry else None,
                f"{prefix}体重kg": entry.weight_kg if entry else None,
                f"{prefix}単勝オッズ": (win_odds.win_odds if win_odds else metric.get("win_odds")),
                f"{prefix}単勝人気": (
                    win_odds.popularity_rank if win_odds else metric.get("popularity_rank")
                ),
                f"{prefix}展示進入": exhibition.exhibition_course if exhibition else None,
                f"{prefix}展示ST": exhibition.exhibition_start_timing if exhibition else None,
                f"{prefix}展示タイム": exhibition.exhibition_time_seconds if exhibition else None,
                f"{prefix}展示補正後": metric.get("exhibition_time_corrected"),
                f"{prefix}展示順位": metric.get("exhibition_rank"),
                f"{prefix}チルト": exhibition.tilt if exhibition else None,
                f"{prefix}半周": exhibition.half_lap_time_seconds if exhibition else None,
                f"{prefix}一周": exhibition.lap_time_seconds if exhibition else None,
                f"{prefix}周回比較値": metric.get("lap_time"),
                f"{prefix}周回補正後": metric.get("lap_time_corrected"),
                f"{prefix}周回順位": metric.get("lap_rank"),
                f"{prefix}まわり足": exhibition.cornering_time_seconds if exhibition else None,
                f"{prefix}直線": exhibition.straight_time_seconds if exhibition else None,
                f"{prefix}展示出典": exhibition.source if exhibition else None,
                f"{prefix}周回出典": exhibition.lap_source if exhibition else None,
                f"{prefix}AP": metric.get("ap"),
                f"{prefix}参考スコア": score.score if score else None,
                f"{prefix}参考順位": score.rank if score else None,
                f"{prefix}信頼度": score.confidence if score else None,
                f"{prefix}警告": " / ".join(score.warnings) if score else None,
                f"{prefix}コース平均ST順位": metric.get("course_avg_start_rank"),
                f"{prefix}コース平均ST": metric.get("course_avg_start_timing"),
                f"{prefix}全国勝率": metric.get("nationwide_win_rate"),
                f"{prefix}コース3連率": metric.get("course_top3_rate"),
                f"{prefix}コース進入数": metric.get("course_starts"),
                f"{prefix}コース成績基準日": metric.get("course_stats_snapshot_date"),
                f"{prefix}部品交換": replacements,
                f"{prefix}着順": race_result.finish_position if race_result else None,
                f"{prefix}本番進入": race_result.actual_course if race_result else None,
                f"{prefix}本番ST": race_result.actual_start_timing if race_result else None,
                f"{prefix}結果状態": race_result.status if race_result else None,
            }
        )
    return row


def build_daily_workbook(
    rows: list[dict[str, Any]],
    race_date: date,
    generated_at: datetime,
) -> Workbook:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "レース結果"
    headers = list(rows[0]) if rows else []
    sheet.append(headers)
    for row in rows:
        sheet.append([_excel_value(row.get(header)) for header in headers])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.row_dimensions[1].height = 32
    for cell in sheet[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    hit_column = headers.index("的中判定") + 1 if "的中判定" in headers else None
    if hit_column:
        for row_number in range(2, sheet.max_row + 1):
            if sheet.cell(row=row_number, column=hit_column).value == "的中":
                for cell in sheet[row_number]:
                    cell.fill = _HIT_FILL
    for index, header in enumerate(headers, start=1):
        width = 14
        if header in {"買い目", "買い目詳細", "判定手順"}:
            width = 42
        elif header.endswith("選手名") or header.endswith("部品交換"):
            width = 18
        sheet.column_dimensions[get_column_letter(index)].width = width

    info = workbook.create_sheet("説明")
    info.append(["項目", "内容"])
    info.append(["対象日", race_date.isoformat()])
    info.append(["生成時刻", generated_at.isoformat()])
    info.append(["単位", "買い目は各100円。払戻額は公式3連単の100円払戻。"])
    info.append(
        [
            "買い目",
            "2艇判定フローを締切前に保存された展示・周回・単勝オッズから日次再計算。",
        ]
    )
    info.append(
        [
            "注意",
            "統計的な判断支援用です。的中・利益を保証せず、自動投票は行いません。",
        ]
    )
    for cell in info[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
    info.column_dimensions["A"].width = 18
    info.column_dimensions["B"].width = 90
    return workbook


def generate_daily_excel(
    race_date: date,
    *,
    require_complete: bool = True,
    force: bool = False,
) -> Path:
    path = daily_excel_path(race_date)
    if path.exists() and not force:
        return path
    if not _EXPORT_LOCK.acquire(blocking=False):
        raise RuntimeError("daily Excel export is already running")
    try:
        with Session(engine) as session:
            races = session.scalars(
                select(Race)
                .where(Race.race_date == race_date)
                .options(
                    selectinload(Race.venue),
                    selectinload(Race.entries).selectinload(RaceEntry.racer),
                    selectinload(Race.entries).selectinload(RaceEntry.exhibitions),
                    selectinload(Race.entries).selectinload(RaceEntry.part_replacements),
                    selectinload(Race.entries).selectinload(RaceEntry.win_odds_observations),
                    selectinload(Race.weather_observations),
                    selectinload(Race.result).selectinload(RaceResult.entries),
                )
                .order_by(Race.scheduled_at, Race.venue_code, Race.race_number)
            ).all()
            if not races:
                raise DailyExcelNotReady(f"{race_date.isoformat()}のレースがありません")
            incomplete = [
                race
                for race in races
                if race.result is None
                or race.result.finalized_at is None
                or (
                    race.result.winning_technique not in NO_RESULT_MARKERS
                    and race.result.trifecta_payout_yen is None
                )
            ]
            if require_complete and incomplete:
                raise DailyExcelNotReady(
                    f"{race_date.isoformat()}は未確定または払戻未取得が{len(incomplete)}レースあります"
                )
            flows = analyze_races_two_boat_flow(races, session)
            rows = [_race_row(race, flows.get(race.id)) for race in races]

        generated_at = datetime.now(ZoneInfo(get_settings().app_timezone))
        workbook = build_daily_workbook(rows, race_date, generated_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp.xlsx")
        workbook.save(temporary)
        temporary.replace(path)
        logger.info("Daily Excel exported date=%s races=%s", race_date, len(rows))
        return path
    finally:
        _EXPORT_LOCK.release()


def generate_due_daily_excel(now: datetime | None = None) -> Path | None:
    settings = get_settings()
    if not settings.daily_excel_enabled:
        return None
    timezone = ZoneInfo(settings.app_timezone)
    current = now or datetime.now(timezone)
    current = (
        current.replace(tzinfo=timezone) if current.tzinfo is None else current.astimezone(timezone)
    )
    scheduled = datetime.combine(
        current.date(),
        time(settings.daily_excel_hour_jst, settings.daily_excel_minute_jst),
        timezone,
    )
    if current < scheduled:
        return None
    target_date = current.date() - timedelta(days=1)
    path = daily_excel_path(target_date)
    if path.exists():
        return path
    return generate_daily_excel(target_date)
