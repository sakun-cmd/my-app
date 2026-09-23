import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import MetaData, Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import create_source_engine, engine
from ..models import (
    ExhibitionObservation,
    ImportBatch,
    ImportStatus,
    PartReplacement,
    Race,
    RaceEntry,
    Racer,
    RaceResult,
    ResultEntry,
    Venue,
    WeatherObservation,
)


def _load_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(
            f"Source mapping not found: {path}. Copy source-mapping.example.json "
            "and update it after inspecting the source schema."
        )
    mapping = json.loads(path.read_text(encoding="utf-8"))
    if mapping.get("adapter"):
        return mapping
    required = {"races", "entries", "exhibitions", "results"}
    missing = required - mapping.keys()
    if missing:
        raise ValueError(f"Source mapping is missing sections: {sorted(missing)}")
    return mapping


def _rows(source_connection, source_table: Table, columns: dict[str, str]):
    selected = []
    for target_name, source_name in columns.items():
        if source_name not in source_table.c:
            raise ValueError(f"Missing source column {source_table.fullname}.{source_name}")
        selected.append(source_table.c[source_name].label(target_name))
    yield from source_connection.execute(select(*selected)).mappings()


def _as_datetime(value: Any) -> datetime:
    source_timezone = ZoneInfo(get_settings().app_timezone)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=source_timezone)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=source_timezone)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=source_timezone)
    raise ValueError("A timestamp is required")


def _as_optional_datetime(value: Any) -> datetime | None:
    return _as_datetime(value) if value is not None else None


def _json_safe(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat()
        if isinstance(value, (date, datetime))
        else str(value)
        if isinstance(value, Decimal)
        else value
        if value is None or isinstance(value, (str, int, float, bool, list, dict))
        else str(value)
        for key, value in values.items()
    }


def _upsert(session: Session, model, values: dict, index_elements: list[str]) -> None:
    statement = insert(model).values(**values)
    updates = {key: value for key, value in values.items() if key not in index_elements}
    session.execute(statement.on_conflict_do_update(index_elements=index_elements, set_=updates))


def run_import(date_from: date | None = None) -> ImportBatch:
    settings = get_settings()
    mapping = _load_mapping(settings.source_mapping_path)
    if mapping.get("adapter") == "boatrace_brd_v1":
        from .brd_importer import run_brd_import

        return run_brd_import(mapping, date_from)
    if date_from is not None:
        raise RuntimeError("Date-filtered import requires the boatrace_brd_v1 adapter")
    source_engine = create_source_engine()

    with Session(engine) as session:
        batch = ImportBatch(status=ImportStatus.RUNNING)
        session.add(batch)
        session.commit()
        session.refresh(batch)
        batch_id = batch.id

    rows_read = 0
    rows_written = 0
    try:
        metadata = MetaData()
        tables = {
            name: Table(
                section["table"],
                metadata,
                schema=settings.source_schema,
                autoload_with=source_engine,
            )
            for name, section in mapping.items()
            if name
            in {
                "races",
                "entries",
                "exhibitions",
                "weather",
                "part_replacements",
                "results",
            }
        }
        with source_engine.connect() as source_connection, Session(engine) as session:
            source_connection.exec_driver_sql("SET TRANSACTION READ ONLY")

            for row in _rows(source_connection, tables["races"], mapping["races"]["columns"]):
                rows_read += 1
                source_id = str(row["source_id"])
                race_date = row["race_date"]
                _upsert(
                    session,
                    Venue,
                    {
                        "code": str(row["venue_code"]),
                        "name": row.get("venue_name") or str(row["venue_code"]),
                    },
                    ["code"],
                )
                _upsert(
                    session,
                    Race,
                    {
                        "source_id": source_id,
                        "race_date": race_date,
                        "venue_code": str(row["venue_code"]),
                        "race_number": int(row["race_number"]),
                        "scheduled_at": _as_optional_datetime(row.get("scheduled_at")),
                        "grade": row.get("grade"),
                        "distance_m": row.get("distance_m"),
                        "source_updated_at": _as_optional_datetime(row.get("updated_at")),
                    },
                    ["source_id"],
                )
                rows_written += 1
            session.flush()
            race_ids = dict(session.execute(select(Race.source_id, Race.id)).all())

            for row in _rows(source_connection, tables["entries"], mapping["entries"]["columns"]):
                rows_read += 1
                source_id = str(row["race_source_id"])
                race_id = race_ids.get(source_id)
                if race_id is None:
                    raise ValueError(f"Entry references unknown race {source_id}")
                racer_number = row.get("racer_registration_number")
                if racer_number:
                    _upsert(
                        session,
                        Racer,
                        {
                            "registration_number": str(racer_number),
                            "name": row.get("racer_name") or str(racer_number),
                        },
                        ["registration_number"],
                    )
                _upsert(
                    session,
                    RaceEntry,
                    {
                        "race_id": race_id,
                        "lane": int(row["lane"]),
                        "racer_registration_number": str(racer_number) if racer_number else None,
                        "class_name": row.get("class_name"),
                        "motor_number": row.get("motor_number"),
                        "boat_number": row.get("boat_number"),
                        "weight_kg": Decimal(str(row["weight_kg"]))
                        if row.get("weight_kg") is not None
                        else None,
                    },
                    ["race_id", "lane"],
                )
                rows_written += 1
            session.flush()
            entry_ids = {
                (source_id, lane): entry_id
                for source_id, lane, entry_id in session.execute(
                    select(Race.source_id, RaceEntry.lane, RaceEntry.id).join(RaceEntry)
                )
            }

            for row in _rows(
                source_connection,
                tables["exhibitions"],
                mapping["exhibitions"]["columns"],
            ):
                rows_read += 1
                source_id = str(row["race_source_id"])
                lane = int(row["lane"])
                entry_id = entry_ids.get((source_id, lane))
                if entry_id is None:
                    raise ValueError(f"Exhibition references unknown entry {source_id}/{lane}")
                observed_at = _as_datetime(row.get("observed_at"))
                values = {
                    "race_entry_id": entry_id,
                    "exhibition_course": row.get("exhibition_course"),
                    "exhibition_start_timing": row.get("exhibition_start_timing"),
                    "exhibition_time_seconds": row.get("exhibition_time_seconds"),
                    "tilt": row.get("tilt"),
                    "half_lap_time_seconds": row.get("half_lap_time_seconds"),
                    "lap_time_seconds": row.get("lap_time_seconds"),
                    "cornering_time_seconds": row.get("cornering_time_seconds"),
                    "straight_time_seconds": row.get("straight_time_seconds"),
                    "observed_at": observed_at,
                    "source_payload": _json_safe(dict(row)),
                }
                _upsert(
                    session,
                    ExhibitionObservation,
                    values,
                    ["race_entry_id", "observed_at"],
                )
                rows_written += 1

            if "weather" in tables:
                for row in _rows(
                    source_connection, tables["weather"], mapping["weather"]["columns"]
                ):
                    rows_read += 1
                    source_id = str(row["race_source_id"])
                    race_id = race_ids.get(source_id)
                    if race_id is None:
                        raise ValueError(f"Weather references unknown race {source_id}")
                    observed_at = _as_datetime(row.get("observed_at"))
                    _upsert(
                        session,
                        WeatherObservation,
                        {
                            "race_id": race_id,
                            "weather": row.get("weather"),
                            "air_temperature_c": row.get("air_temperature_c"),
                            "water_temperature_c": row.get("water_temperature_c"),
                            "wind_direction": row.get("wind_direction"),
                            "wind_speed_mps": row.get("wind_speed_mps"),
                            "wave_height_cm": row.get("wave_height_cm"),
                            "observed_at": observed_at,
                        },
                        ["race_id", "observed_at"],
                    )
                    rows_written += 1

            if "part_replacements" in tables:
                for row in _rows(
                    source_connection,
                    tables["part_replacements"],
                    mapping["part_replacements"]["columns"],
                ):
                    rows_read += 1
                    source_id = str(row["race_source_id"])
                    lane = int(row["lane"])
                    entry_id = entry_ids.get((source_id, lane))
                    if entry_id is None:
                        raise ValueError(
                            f"Part replacement references unknown entry {source_id}/{lane}"
                        )
                    replaced_at = _as_datetime(row.get("replaced_at"))
                    _upsert(
                        session,
                        PartReplacement,
                        {
                            "race_entry_id": entry_id,
                            "part_name": str(row["part_name"]),
                            "quantity": int(row.get("quantity") or 1),
                            "replaced_at": replaced_at,
                        },
                        ["race_entry_id", "part_name", "replaced_at"],
                    )
                    rows_written += 1

            for row in _rows(source_connection, tables["results"], mapping["results"]["columns"]):
                rows_read += 1
                source_id = str(row["race_source_id"])
                race_id = race_ids.get(source_id)
                if race_id is None:
                    raise ValueError(f"Result references unknown race {source_id}")
                result = session.scalar(select(RaceResult).where(RaceResult.race_id == race_id))
                if result is None:
                    result = RaceResult(race_id=race_id)
                    session.add(result)
                    session.flush()
                _upsert(
                    session,
                    ResultEntry,
                    {
                        "race_result_id": result.id,
                        "lane": int(row["lane"]),
                        "finish_position": row.get("finish_position"),
                        "actual_course": row.get("actual_course"),
                        "actual_start_timing": row.get("actual_start_timing"),
                        "status": row.get("status"),
                    },
                    ["race_result_id", "lane"],
                )
                rows_written += 1

            batch = session.get(ImportBatch, batch_id)
            batch.status = ImportStatus.SUCCEEDED
            batch.completed_at = datetime.now(UTC)
            batch.rows_read = rows_read
            batch.rows_written = rows_written
            session.commit()
            session.refresh(batch)
            return batch
    except Exception as exc:
        with Session(engine) as session:
            batch = session.get(ImportBatch, batch_id)
            batch.status = ImportStatus.FAILED
            batch.completed_at = datetime.now(UTC)
            batch.rows_read = rows_read
            batch.rows_written = rows_written
            batch.error_message = str(exc)
            session.commit()
        raise
    finally:
        source_engine.dispose()
