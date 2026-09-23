import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class ImportStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Venue(Base):
    __tablename__ = "venues"
    __table_args__ = {"schema": "core"}

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))


class Race(Base):
    __tablename__ = "races"
    __table_args__ = (
        UniqueConstraint("race_date", "venue_code", "race_number"),
        CheckConstraint("race_number BETWEEN 1 AND 12"),
        Index("ix_races_date_venue", "race_date", "venue_code"),
        Index(
            "ix_races_official_result_due",
            "race_date",
            "scheduled_at",
            "official_result_checked_at",
        ),
        Index(
            "ix_races_official_exhibition_due",
            "race_date",
            "scheduled_at",
            "official_exhibition_checked_at",
            "official_exhibition_fetched_at",
        ),
        Index(
            "ix_races_official_win_odds_due",
            "race_date",
            "scheduled_at",
            "official_win_odds_checked_at",
            "official_win_odds_fetched_at",
        ),
        Index(
            "ix_races_boatcast_lap_due",
            "race_date",
            "scheduled_at",
            "boatcast_lap_checked_at",
            "boatcast_lap_fetched_at",
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(160), unique=True)
    race_date: Mapped[date] = mapped_column(Date)
    venue_code: Mapped[str] = mapped_column(ForeignKey("core.venues.code"))
    race_number: Mapped[int] = mapped_column(SmallInteger)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grade: Mapped[str | None] = mapped_column(String(20))
    distance_m: Mapped[int | None] = mapped_column(SmallInteger)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    official_result_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    official_exhibition_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    official_exhibition_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    official_win_odds_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    official_win_odds_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    boatcast_lap_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    boatcast_lap_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    venue: Mapped[Venue] = relationship()
    entries: Mapped[list["RaceEntry"]] = relationship(
        back_populates="race", order_by="RaceEntry.lane"
    )
    weather_observations: Mapped[list["WeatherObservation"]] = relationship(
        back_populates="race", order_by="WeatherObservation.observed_at"
    )
    result: Mapped["RaceResult | None"] = relationship(back_populates="race")


class Racer(Base):
    __tablename__ = "racers"
    __table_args__ = {"schema": "core"}

    registration_number: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class RaceEntry(Base):
    __tablename__ = "race_entries"
    __table_args__ = (
        UniqueConstraint("race_id", "lane"),
        CheckConstraint("lane BETWEEN 1 AND 6"),
        Index("ix_entries_racer", "racer_registration_number"),
        Index("ix_entries_motor", "motor_number"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    race_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.races.id", ondelete="CASCADE"))
    lane: Mapped[int] = mapped_column(SmallInteger)
    racer_registration_number: Mapped[str | None] = mapped_column(
        ForeignKey("core.racers.registration_number")
    )
    class_name: Mapped[str | None] = mapped_column(String(8))
    motor_number: Mapped[int | None] = mapped_column(SmallInteger)
    boat_number: Mapped[int | None] = mapped_column(SmallInteger)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    race: Mapped[Race] = relationship(back_populates="entries")
    racer: Mapped[Racer | None] = relationship()
    exhibitions: Mapped[list["ExhibitionObservation"]] = relationship(
        back_populates="entry", order_by="ExhibitionObservation.observed_at"
    )
    part_replacements: Mapped[list["PartReplacement"]] = relationship(
        back_populates="entry", order_by="PartReplacement.replaced_at"
    )
    win_odds_observations: Mapped[list["WinOddsObservation"]] = relationship(
        back_populates="entry", order_by="WinOddsObservation.observed_at"
    )


class ExhibitionObservation(Base):
    __tablename__ = "exhibition_observations"
    __table_args__ = (
        UniqueConstraint("race_entry_id", "observed_at"),
        CheckConstraint("exhibition_course BETWEEN 1 AND 6"),
        Index("ix_exhibitions_entry_latest", "race_entry_id", "observed_at"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    race_entry_id: Mapped[int] = mapped_column(
        ForeignKey("core.race_entries.id", ondelete="CASCADE")
    )
    exhibition_course: Mapped[int | None] = mapped_column(SmallInteger)
    exhibition_start_timing: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    exhibition_time_seconds: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    tilt: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    half_lap_time_seconds: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    lap_time_seconds: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    cornering_time_seconds: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    straight_time_seconds: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    lap_source_payload: Mapped[dict | None] = mapped_column(JSON)

    entry: Mapped[RaceEntry] = relationship(back_populates="exhibitions")

    @property
    def source(self) -> str | None:
        value = (self.source_payload or {}).get("source")
        return str(value) if value else None

    @property
    def lap_source(self) -> str | None:
        value = (self.lap_source_payload or {}).get("source")
        return str(value) if value else None


class WinOddsObservation(Base):
    __tablename__ = "win_odds_observations"
    __table_args__ = (
        UniqueConstraint("race_entry_id", "observed_at"),
        CheckConstraint("win_odds >= 0"),
        CheckConstraint("popularity_rank BETWEEN 1 AND 6"),
        Index("ix_win_odds_entry_latest", "race_entry_id", "observed_at"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    race_entry_id: Mapped[int] = mapped_column(
        ForeignKey("core.race_entries.id", ondelete="CASCADE")
    )
    win_odds: Mapped[Decimal] = mapped_column(Numeric(8, 1))
    popularity_rank: Mapped[int] = mapped_column(SmallInteger)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_payload: Mapped[dict] = mapped_column(JSON, default=dict)

    entry: Mapped[RaceEntry] = relationship(back_populates="win_odds_observations")

    @property
    def source(self) -> str | None:
        value = (self.source_payload or {}).get("source")
        return str(value) if value else None


class WeatherObservation(Base):
    __tablename__ = "weather_observations"
    __table_args__ = (
        UniqueConstraint("race_id", "observed_at"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    race_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.races.id", ondelete="CASCADE"))
    weather: Mapped[str | None] = mapped_column(String(32))
    air_temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    water_temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    wind_direction: Mapped[str | None] = mapped_column(String(20))
    wind_speed_mps: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    wave_height_cm: Mapped[int | None] = mapped_column(SmallInteger)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    race: Mapped[Race] = relationship(back_populates="weather_observations")


class PartReplacement(Base):
    __tablename__ = "part_replacements"
    __table_args__ = (
        UniqueConstraint("race_entry_id", "part_name", "replaced_at"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    race_entry_id: Mapped[int] = mapped_column(
        ForeignKey("core.race_entries.id", ondelete="CASCADE")
    )
    part_name: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[int] = mapped_column(SmallInteger, default=1)
    replaced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry: Mapped[RaceEntry] = relationship(back_populates="part_replacements")


class RaceResult(Base):
    __tablename__ = "race_results"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    race_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.races.id", ondelete="CASCADE"), unique=True
    )
    winning_technique: Mapped[str | None] = mapped_column(String(32))
    trifecta_combination: Mapped[str | None] = mapped_column(String(8))
    trifecta_payout_yen: Mapped[int | None] = mapped_column(Integer)
    trifecta_popularity_rank: Mapped[int | None] = mapped_column(SmallInteger)
    trifecta_refunded: Mapped[bool] = mapped_column(Boolean, default=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(40))
    race: Mapped[Race] = relationship(back_populates="result")
    entries: Mapped[list["ResultEntry"]] = relationship(
        back_populates="result", order_by="ResultEntry.finish_position"
    )


class ResultEntry(Base):
    __tablename__ = "result_entries"
    __table_args__ = (
        UniqueConstraint("race_result_id", "lane"),
        CheckConstraint("lane BETWEEN 1 AND 6"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    race_result_id: Mapped[int] = mapped_column(
        ForeignKey("core.race_results.id", ondelete="CASCADE")
    )
    lane: Mapped[int] = mapped_column(SmallInteger)
    finish_position: Mapped[int | None] = mapped_column(SmallInteger)
    actual_course: Mapped[int | None] = mapped_column(SmallInteger)
    actual_start_timing: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    status: Mapped[str | None] = mapped_column(String(20))
    result: Mapped[RaceResult] = relationship(back_populates="entries")


class ScoringProfile(Base):
    __tablename__ = "scoring_profiles"
    __table_args__ = {"schema": "analytics"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    weights: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PredictionRun(Base):
    __tablename__ = "prediction_runs"
    __table_args__ = (
        UniqueConstraint("race_id", "scoring_profile_id", "data_cutoff_at"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    race_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.races.id"))
    scoring_profile_id: Mapped[int] = mapped_column(ForeignKey("analytics.scoring_profiles.id"))
    data_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PredictionItem(Base):
    __tablename__ = "prediction_items"
    __table_args__ = (
        UniqueConstraint("prediction_run_id", "lane"),
        {"schema": "analytics"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    prediction_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analytics.prediction_runs.id", ondelete="CASCADE")
    )
    lane: Mapped[int] = mapped_column(SmallInteger)
    rank: Mapped[int] = mapped_column(SmallInteger)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    confidence: Mapped[str] = mapped_column(String(16))
    contributions: Mapped[dict] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="import_status", schema="ops")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    high_water_mark: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class ImportError(Base):
    __tablename__ = "import_errors"
    __table_args__ = {"schema": "ops"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ops.import_batches.id", ondelete="CASCADE")
    )
    entity: Mapped[str] = mapped_column(String(40))
    source_key: Mapped[str | None] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(Text)
    source_payload: Mapped[dict | None] = mapped_column(JSON)
