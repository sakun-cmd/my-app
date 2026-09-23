import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..models import Race, RaceEntry, RaceResult
from ..schemas import EvaluationMetrics, EvaluationSummary
from .official_results import NO_RESULT_MARKERS
from .racer_stats import fetch_average_start_timings
from .scoring import DEFAULT_PROFILE_VERSION, ScoringInput, score_entries

logger = logging.getLogger(__name__)


def evaluate(
    db: Session,
    date_from: date | None = None,
    date_to: date | None = None,
) -> EvaluationSummary:
    today = datetime.now(ZoneInfo(get_settings().app_timezone)).date()
    filters = [
        Race.result.has(),
        or_(Race.race_date < today, Race.result.has(RaceResult.finalized_at.is_not(None))),
    ]
    if date_from:
        filters.append(Race.race_date >= date_from)
    if date_to:
        filters.append(Race.race_date <= date_to)
    races = db.scalars(
        select(Race)
        .where(*filters)
        .options(
            selectinload(Race.entries).selectinload(RaceEntry.exhibitions),
            selectinload(Race.result).selectinload(RaceResult.entries),
        )
        .order_by(Race.race_date, Race.venue_code, Race.race_number)
    ).all()

    average_start_timings: dict[str, dict[int, Decimal]] = {}
    if races:
        try:
            average_start_timings = fetch_average_start_timings(
                min(race.race_date for race in races),
                max(race.race_date for race in races),
            )
        except Exception:
            logger.exception("Failed to fetch racer average start timings")

    winner_ranks: list[int] = []
    lane_one_wins = 0
    skipped = 0
    cancelled = 0
    missing_schedule = 0
    for race in races:
        if race.result.winning_technique in NO_RESULT_MARKERS:
            cancelled += 1
            continue
        winner = next(
            (
                item.lane
                for item in race.result.entries
                if item.finish_position == 1 and item.status not in {"欠場", "失格"}
            ),
            None,
        )
        if winner is None or not race.entries:
            skipped += 1
            continue
        if race.scheduled_at is None:
            missing_schedule += 1
            continue
        cutoff = race.scheduled_at
        race_average_start_timings = average_start_timings.get(race.source_id, {})
        inputs: list[ScoringInput] = []
        for entry in race.entries:
            eligible = [
                observation
                for observation in entry.exhibitions
                if observation.observed_at <= cutoff
            ]
            latest = eligible[-1] if eligible else None
            inputs.append(
                ScoringInput(
                    lane=entry.lane,
                    exhibition_time_seconds=(latest.exhibition_time_seconds if latest else None),
                    exhibition_start_timing=(latest.exhibition_start_timing if latest else None),
                    exhibition_course=latest.exhibition_course if latest else None,
                    half_lap_time_seconds=latest.half_lap_time_seconds if latest else None,
                    lap_time_seconds=latest.lap_time_seconds if latest else None,
                    cornering_time_seconds=latest.cornering_time_seconds if latest else None,
                    straight_time_seconds=latest.straight_time_seconds if latest else None,
                    average_start_timing=race_average_start_timings.get(entry.lane),
                )
            )
        scored = score_entries(inputs, race.venue_code)
        winner_item = next((item for item in scored if item.lane == winner), None)
        if winner_item is None:
            skipped += 1
            continue
        winner_ranks.append(winner_item.rank)
        lane_one_wins += int(winner == 1)

    count = len(winner_ranks)
    divisor = count or 1
    metrics = EvaluationMetrics(
        race_count=count,
        top_1_accuracy=sum(rank == 1 for rank in winner_ranks) / divisor,
        top_2_coverage=sum(rank <= 2 for rank in winner_ranks) / divisor,
        top_3_coverage=sum(rank <= 3 for rank in winner_ranks) / divisor,
        average_winner_rank=sum(winner_ranks) / divisor if count else 0,
        lane_1_baseline_accuracy=lane_one_wins / divisor,
    )
    notes = [
        "各レースの発走予定時刻以前に観測された展示データだけを使用しています。",
        "評価値は過去データ上の結果であり、将来の成績や利益を保証しません。",
    ]
    if skipped:
        notes.append(f"確定着順または出走データ不足のため{skipped}レースを除外しました。")
    if cancelled:
        notes.append(f"中止・不成立のため{cancelled}レースを除外しました。")
    if missing_schedule:
        notes.append(f"発走予定時刻が不明なため{missing_schedule}レースを除外しました。")
    if count < 100:
        notes.append("評価対象が100レース未満のため、小標本として解釈してください。")
    return EvaluationSummary(
        date_from=date_from,
        date_to=date_to,
        profile_version=DEFAULT_PROFILE_VERSION,
        calculated_at=datetime.now(UTC),
        metrics=metrics,
        notes=notes,
    )
