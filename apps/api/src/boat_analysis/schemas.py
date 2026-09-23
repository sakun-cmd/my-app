from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VenueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str


class ExhibitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    exhibition_course: int | None
    exhibition_start_timing: Decimal | None
    exhibition_time_seconds: Decimal | None
    tilt: Decimal | None
    half_lap_time_seconds: Decimal | None
    lap_time_seconds: Decimal | None
    cornering_time_seconds: Decimal | None
    straight_time_seconds: Decimal | None
    observed_at: datetime
    source: str | None
    lap_source: str | None


class PartReplacementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    part_name: str
    quantity: int
    replaced_at: datetime


class WeatherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    weather: str | None
    air_temperature_c: Decimal | None
    water_temperature_c: Decimal | None
    wind_direction: str | None
    wind_speed_mps: Decimal | None
    wave_height_cm: int | None
    observed_at: datetime


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    lane: int
    racer_registration_number: str | None
    racer_name: str | None = None
    class_name: str | None
    motor_number: int | None
    boat_number: int | None
    weight_kg: Decimal | None
    exhibition: ExhibitionOut | None = None
    part_replacements: list[PartReplacementOut] = Field(default_factory=list)


class ResultEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    lane: int
    finish_position: int | None
    actual_course: int | None
    actual_start_timing: Decimal | None
    status: str | None


class RaceResultOut(BaseModel):
    winning_technique: str | None
    trifecta_combination: str | None
    trifecta_payout_yen: int | None
    trifecta_popularity_rank: int | None
    trifecta_refunded: bool
    finalized_at: datetime | None
    source: str | None
    entries: list[ResultEntryOut]


class RaceSummary(BaseModel):
    id: UUID
    race_date: date
    venue: VenueOut
    race_number: int
    scheduled_at: datetime | None
    grade: str | None
    data_completeness: int = Field(ge=0, le=100)
    status: str


class RaceListResponse(BaseModel):
    items: list[RaceSummary]
    total: int
    page: int
    page_size: int


class RaceDetail(RaceSummary):
    distance_m: int | None
    weather: WeatherOut | None
    entries: list[EntryOut]
    result: RaceResultOut | None


class Contribution(BaseModel):
    key: str
    label: str
    raw_value: Decimal | None
    points: Decimal
    explanation: str


class AnalysisItem(BaseModel):
    lane: int
    rank: int
    score: Decimal
    confidence: str
    contributions: list[Contribution]
    warnings: list[str]


class RaceAnalysis(BaseModel):
    race_id: UUID
    profile_version: str
    calculated_at: datetime
    data_cutoff_at: datetime
    items: list[AnalysisItem]
    disclaimer: str


class SourceColumn(BaseModel):
    name: str
    data_type: str
    nullable: bool
    null_fraction: float | None = None
    distinct_estimate: float | None = None


class SourceTable(BaseModel):
    schema_name: str
    table_name: str
    estimated_rows: int | None
    columns: list[SourceColumn]
    primary_key: list[str]


class SourceInspection(BaseModel):
    inspected_at: datetime
    database_name: str
    tables: list[SourceTable]


class ImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    rows_read: int
    rows_written: int
    errors_count: int
    high_water_mark: str | None


class OfficialResultRefreshOut(BaseModel):
    eligible_races: int
    checked_races: int
    finalized_races: int
    pending_races: int
    errors_count: int
    already_running: bool


class OfficialExhibitionRefreshOut(BaseModel):
    eligible_races: int
    checked_races: int
    imported_races: int
    pending_races: int
    errors_count: int
    already_running: bool


class OfficialWinOddsRefreshOut(BaseModel):
    eligible_races: int
    checked_races: int
    imported_races: int
    pending_races: int
    errors_count: int
    already_running: bool


class BoatcastLapRefreshOut(BaseModel):
    eligible_races: int
    checked_races: int
    imported_races: int
    pending_races: int
    errors_count: int
    already_running: bool


class LiveRefreshOut(ImportBatchOut):
    official_results: OfficialResultRefreshOut
    official_exhibitions: OfficialExhibitionRefreshOut
    official_win_odds: OfficialWinOddsRefreshOut
    boatcast_laps: BoatcastLapRefreshOut


class EvaluationMetrics(BaseModel):
    race_count: int
    top_1_accuracy: float
    top_2_coverage: float
    top_3_coverage: float
    average_winner_rank: float
    lane_1_baseline_accuracy: float


class EvaluationSummary(BaseModel):
    date_from: date | None
    date_to: date | None
    profile_version: str
    calculated_at: datetime
    metrics: EvaluationMetrics
    notes: list[str]


class TwoBoatMetric(BaseModel):
    lane: int
    popularity_rank: int | None
    win_odds: Decimal | None
    exhibition_time: Decimal | None
    lap_time: Decimal | None
    exhibition_time_corrected: Decimal | None = None
    lap_time_corrected: Decimal | None = None
    exhibition_rank: int | None
    lap_rank: int | None
    course_avg_start_rank: Decimal | None
    course_avg_start_timing: Decimal | None
    nationwide_win_rate: Decimal | None
    course_top3_rate: Decimal | None
    course_starts: int | None
    course_stats_snapshot_date: date | None
    ap: bool


class FlowStep(BaseModel):
    number: int
    result: str
    detail: str


class FlowTicket(BaseModel):
    combination: tuple[int, int, int]
    odds: Decimal | None
    popularity_rank: int | None


class TwoBoatFlowAnalysis(BaseModel):
    race_id: UUID
    win_odds_source: str | None
    win_odds_observed_at: datetime | None
    status: str
    outer_lane: int | None
    outer_outer_lane: int | None
    likely_lanes: list[int]
    escape_assessment: str
    metrics: list[TwoBoatMetric]
    steps: list[FlowStep]
    tickets: list[FlowTicket]
    composite_odds: Decimal | None
    decision: str
    disclaimer: str


class TwoBoatEvaluation(BaseModel):
    date_from: date
    date_to: date
    total_finalized_races: int
    gap_triggered_races: int
    insufficient_data_races: int
    triggered_races: int
    trigger_rate: float | None
    likely_boat_win_rate: float | None
    likely_boat_top3_rate: float | None
    triggered_lane_1_win_rate: float | None
    ticket_generated_races: int
    ticket_hit_rate: float | None
    average_ticket_count: float | None
    escape_assessment_accuracy: float | None
    escape_assessed_races: int
    course_stats_covered_races: int
    course_stats_coverage_rate: float | None
    course_stats_history_available_from: date
    course_stats_initial_snapshot_uncertain_through: date
    snapshot_lag_days_min: int | None
    snapshot_lag_days_median: float | None
    snapshot_lag_days_max: int | None
    odds_covered_races: int
    flat_stake_return_rate: float | None
    notes: list[str]
