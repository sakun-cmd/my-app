from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..database import DbSession
from ..models import ExhibitionObservation, Race, RaceEntry, RaceResult
from ..schemas import (
    EntryOut,
    ExhibitionOut,
    PartReplacementOut,
    RaceDetail,
    RaceListResponse,
    RaceResultOut,
    RaceSummary,
    ResultEntryOut,
    VenueOut,
    WeatherOut,
)
from ..services.official_results import CANCELLED_RACE_MARKER, VOID_RACE_MARKER
from ..services.scoring import expected_lap_fields

router = APIRouter(prefix="/races", tags=["races"])


def _latest_exhibition(entry: RaceEntry, cutoff: datetime | None) -> ExhibitionObservation | None:
    if cutoff is None:
        return None
    eligible = [
        observation for observation in entry.exhibitions if observation.observed_at <= cutoff
    ]
    return eligible[-1] if eligible else None


def _exhibition_out(
    observation: ExhibitionObservation,
    *,
    allow_database_laps: bool,
) -> ExhibitionOut:
    result = ExhibitionOut.model_validate(observation)
    if allow_database_laps or observation.lap_source == "race.boatcast.jp":
        return result
    return result.model_copy(
        update={
            "half_lap_time_seconds": None,
            "lap_time_seconds": None,
            "cornering_time_seconds": None,
            "straight_time_seconds": None,
            "lap_source": None,
        }
    )


def _completeness(race: Race) -> int:
    if not race.entries:
        return 0
    today = datetime.now(ZoneInfo(get_settings().app_timezone)).date()
    allow_database_laps = race.race_date < today
    lap_fields = expected_lap_fields(race.venue_code)
    present = 0
    total = len(race.entries) * (3 + len(lap_fields))
    for entry in race.entries:
        exhibition = _latest_exhibition(entry, race.scheduled_at)
        if exhibition:
            present += sum(
                value is not None
                for value in (
                    exhibition.exhibition_course,
                    exhibition.exhibition_start_timing,
                    exhibition.exhibition_time_seconds,
                )
            )
            if allow_database_laps or exhibition.lap_source == "race.boatcast.jp":
                present += sum(getattr(exhibition, field) is not None for field in lap_fields)
    return round(present / total * 100)


def _race_status(race: Race) -> str:
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo(get_settings().app_timezone)).date()
    if race.result and race.result.finalized_at is not None:
        if race.result.winning_technique == CANCELLED_RACE_MARKER:
            return "cancelled"
        if race.result.winning_technique == VOID_RACE_MARKER:
            return "void"
    if (
        race.result
        and any(item.finish_position is not None for item in race.result.entries)
        and (race.race_date < today or race.result.finalized_at is not None)
    ):
        return "final"
    if race.scheduled_at is None:
        return "unknown"
    if race.scheduled_at > now:
        return "upcoming"
    if race.scheduled_at + timedelta(hours=1) >= now:
        return "live"
    return "pending_result"


def _summary(race: Race) -> RaceSummary:
    return RaceSummary(
        id=race.id,
        race_date=race.race_date,
        venue=VenueOut.model_validate(race.venue),
        race_number=race.race_number,
        scheduled_at=race.scheduled_at,
        grade=race.grade,
        data_completeness=_completeness(race),
        status=_race_status(race),
    )


@router.get("", response_model=RaceListResponse)
def list_races(
    db: DbSession,
    race_date: date | None = None,
    venue_code: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 20,
) -> RaceListResponse:
    filters = []
    if race_date:
        filters.append(Race.race_date == race_date)
    if venue_code:
        filters.append(Race.venue_code == venue_code)
    total = db.scalar(select(func.count()).select_from(Race).where(*filters)) or 0
    races = db.scalars(
        select(Race)
        .where(*filters)
        .options(
            selectinload(Race.venue),
            selectinload(Race.entries).selectinload(RaceEntry.exhibitions),
            selectinload(Race.result).selectinload(RaceResult.entries),
        )
        .order_by(Race.race_date.desc(), Race.venue_code, Race.race_number)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return RaceListResponse(
        items=[_summary(race) for race in races],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{race_id}", response_model=RaceDetail)
def get_race(race_id: UUID, db: DbSession) -> RaceDetail:
    race = db.scalar(
        select(Race)
        .where(Race.id == race_id)
        .options(
            selectinload(Race.venue),
            selectinload(Race.entries).selectinload(RaceEntry.racer),
            selectinload(Race.entries).selectinload(RaceEntry.exhibitions),
            selectinload(Race.entries).selectinload(RaceEntry.part_replacements),
            selectinload(Race.weather_observations),
            selectinload(Race.result).selectinload(RaceResult.entries),
        )
    )
    if race is None:
        raise HTTPException(status_code=404, detail="Race not found")
    summary = _summary(race)
    today = datetime.now(ZoneInfo(get_settings().app_timezone)).date()
    entries = []
    for entry in race.entries:
        exhibition = _latest_exhibition(entry, race.scheduled_at)
        entries.append(
            EntryOut(
                lane=entry.lane,
                racer_registration_number=entry.racer_registration_number,
                racer_name=entry.racer.name if entry.racer else None,
                class_name=entry.class_name,
                motor_number=entry.motor_number,
                boat_number=entry.boat_number,
                weight_kg=entry.weight_kg,
                exhibition=(
                    _exhibition_out(
                        exhibition,
                        allow_database_laps=race.race_date < today,
                    )
                    if exhibition
                    else None
                ),
                part_replacements=[
                    PartReplacementOut.model_validate(item)
                    for item in entry.part_replacements
                    if race.scheduled_at is not None and item.replaced_at <= race.scheduled_at
                ],
            )
        )
    eligible_weather = [
        item
        for item in race.weather_observations
        if race.scheduled_at is not None and item.observed_at <= race.scheduled_at
    ]
    return RaceDetail(
        **summary.model_dump(),
        distance_m=race.distance_m,
        weather=(WeatherOut.model_validate(eligible_weather[-1]) if eligible_weather else None),
        entries=entries,
        result=(
            RaceResultOut(
                winning_technique=race.result.winning_technique,
                trifecta_combination=race.result.trifecta_combination,
                trifecta_payout_yen=race.result.trifecta_payout_yen,
                trifecta_popularity_rank=race.result.trifecta_popularity_rank,
                trifecta_refunded=race.result.trifecta_refunded,
                finalized_at=race.result.finalized_at,
                source=race.result.source,
                entries=[ResultEntryOut.model_validate(item) for item in race.result.entries],
            )
            if race.result and summary.status == "final"
            else None
        ),
    )
