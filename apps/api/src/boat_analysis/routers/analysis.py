import logging
from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..database import DbSession
from ..models import Race, RaceEntry, RaceResult
from ..schemas import RaceAnalysis, TwoBoatFlowAnalysis, TwoBoatFlowSummary
from ..services.racer_stats import fetch_average_start_timings
from ..services.scoring import (
    DEFAULT_PROFILE_VERSION,
    DISCLAIMER,
    ScoringInput,
    score_entries,
)
from ..services.two_boat_flow import (
    analyze_race_two_boat_flow,
    analyze_races_two_boat_flow,
    result_winning_combination,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])
logger = logging.getLogger(__name__)


@router.get("/races/{race_id}", response_model=RaceAnalysis)
def analyze_race(race_id: UUID, db: DbSession) -> RaceAnalysis:
    race = db.scalar(
        select(Race)
        .where(Race.id == race_id)
        .options(selectinload(Race.entries).selectinload(RaceEntry.exhibitions))
    )
    if race is None:
        raise HTTPException(status_code=404, detail="Race not found")
    if race.scheduled_at is None:
        raise HTTPException(
            status_code=422,
            detail="発走予定時刻が未登録のため、安全なデータ締切を判定できません",
        )
    cutoff = race.scheduled_at
    today = datetime.now(ZoneInfo(get_settings().app_timezone)).date()
    try:
        average_start_timings = fetch_average_start_timings(race.race_date, race.race_date).get(
            race.source_id, {}
        )
    except Exception:
        logger.exception("Failed to fetch racer average start timings")
        average_start_timings = {}
    inputs: list[ScoringInput] = []
    for entry in race.entries:
        eligible = [item for item in entry.exhibitions if item.observed_at <= cutoff]
        latest = eligible[-1] if eligible else None
        use_lap = bool(
            latest and (race.race_date < today or latest.lap_source == "race.boatcast.jp")
        )
        inputs.append(
            ScoringInput(
                lane=entry.lane,
                exhibition_time_seconds=latest.exhibition_time_seconds if latest else None,
                exhibition_start_timing=latest.exhibition_start_timing if latest else None,
                exhibition_course=latest.exhibition_course if latest else None,
                half_lap_time_seconds=(
                    latest.half_lap_time_seconds if use_lap and latest else None
                ),
                lap_time_seconds=latest.lap_time_seconds if use_lap and latest else None,
                cornering_time_seconds=(
                    latest.cornering_time_seconds if use_lap and latest else None
                ),
                straight_time_seconds=(
                    latest.straight_time_seconds if use_lap and latest else None
                ),
                average_start_timing=average_start_timings.get(entry.lane),
            )
        )
    return RaceAnalysis(
        race_id=race.id,
        profile_version=DEFAULT_PROFILE_VERSION,
        calculated_at=datetime.now(UTC),
        data_cutoff_at=cutoff,
        items=score_entries(inputs, race.venue_code),
        disclaimer=DISCLAIMER,
    )


@router.get("/races/{race_id}/two-boat-flow", response_model=TwoBoatFlowAnalysis)
def analyze_two_boat_flow(race_id: UUID, db: DbSession) -> TwoBoatFlowAnalysis:
    try:
        return TwoBoatFlowAnalysis.model_validate(analyze_race_two_boat_flow(race_id, db))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/two-boat-flow/summary", response_model=list[TwoBoatFlowSummary])
def two_boat_flow_summary(race_date: date, db: DbSession) -> list[TwoBoatFlowSummary]:
    races = list(
        db.scalars(
            select(Race)
            .where(Race.race_date == race_date)
            .options(selectinload(Race.result).selectinload(RaceResult.entries))
        ).all()
    )
    flows = analyze_races_two_boat_flow(races, db)
    races_by_id = {race.id: race for race in races}
    summaries = []
    for race_id, flow in flows.items():
        race = races_by_id[race_id]
        tickets = [tuple(row["combination"]) for row in flow["tickets"]]
        hit = None
        if tickets and race.result and race.result.finalized_at is not None:
            winning = result_winning_combination(
                [(item.lane, item.finish_position) for item in race.result.entries]
            )
            if winning is not None:
                hit = winning in tickets
        summaries.append(
            TwoBoatFlowSummary(
                race_id=race_id,
                has_tickets=bool(tickets),
                ticket_count=len(tickets),
                hit=hit,
            )
        )
    return summaries
