import uuid
from collections.abc import Iterable, Iterator, Mapping
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import MetaData, Table, and_, or_, select, tuple_
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import create_source_engine, engine
from ..models import (
    ExhibitionObservation,
    ImportBatch,
    ImportError,
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

BATCH_SIZE = 1_000
IMPORT_LOCK_KEY = 2_026_090_901
RACE_NAMESPACE = uuid.UUID("52e6bd4b-6258-49ea-8669-136ef94aa589")

VENUE_NAMES = {
    "01": "桐生",
    "02": "戸田",
    "03": "江戸川",
    "04": "平和島",
    "05": "多摩川",
    "06": "浜名湖",
    "07": "蒲郡",
    "08": "常滑",
    "09": "津",
    "10": "三国",
    "11": "びわこ",
    "12": "住之江",
    "13": "尼崎",
    "14": "鳴門",
    "15": "丸亀",
    "16": "児島",
    "17": "宮島",
    "18": "徳山",
    "19": "下関",
    "20": "若松",
    "21": "芦屋",
    "22": "福岡",
    "23": "唐津",
    "24": "大村",
}

PART_COLUMNS = {
    "propeller": "プロペラ",
    "piston": "ピストン",
    "piston_ring": "ピストンリング",
    "denki_isshiki": "電気一式",
    "carburetor": "キャブレタ",
    "cylinder": "シリンダ",
    "crankshaft": "クランクシャフト",
    "gearcase": "ギヤケース",
    "careerbody": "キャリアボデー",
}

SOURCE_COLUMNS = {
    "races": [
        "record_id",
        "kaisai_nen",
        "kaisai_tsukihi",
        "kyoteijo_code",
        "race_no",
        "race_mei",
        "kyori",
        "shimekiri_yotei_jikoku",
    ],
    "entries": [
        "kaisai_nen",
        "kaisai_tsukihi",
        "kyoteijo_code",
        "race_no",
        "teiban",
        "toroku_bango",
        "shimei",
        "kyubetsu",
        "taiju",
        "motor_no",
        "boat_no",
    ],
    "weather": [
        "kaisai_nen",
        "kaisai_tsukihi",
        "kyoteijo_code",
        "race_no",
        "tenki_code",
        "kion",
        "suion",
        "fuko_code",
        "fusoku",
        "hako",
    ],
    "exhibitions": [
        "record_id",
        "kaisai_nen",
        "kaisai_tsukihi",
        "kyoteijo_code",
        "race_no",
        "teiban",
        "tilt",
        "tenji_time",
        "tenji_shinnyu_course",
        "tenji_st",
        "tenji_kigo",
        *PART_COLUMNS,
    ],
    "lap_exhibitions": [
        "record_id",
        "kaisai_nen",
        "kaisai_tsukihi",
        "kyoteijo_code",
        "race_no",
        "teiban",
        "hanshu",
        "isshu",
        "mawariashi",
        "chokusen",
    ],
    "results": [
        "kaisai_nen",
        "kaisai_tsukihi",
        "kyoteijo_code",
        "race_no",
        "teiban",
        "chakujun",
        "shinnyu_course",
        "st",
    ],
}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _optional_int(value: Any) -> int | None:
    raw = _text(value)
    return int(raw) if raw and raw.lstrip("-").isdigit() else None


def _scaled_decimal(value: Any, scale: int, *, zero_is_missing: bool = False) -> Decimal | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = Decimal(raw) / Decimal(scale)
    except InvalidOperation as exc:
        raise ValueError(f"invalid fixed-point number: {raw!r}") from exc
    if zero_is_missing and parsed == 0:
        return None
    return parsed


def _start_timing(value: Any, marker: Any = None) -> Decimal | None:
    raw = _text(value)
    if not raw:
        return None
    sign = (
        Decimal("-1")
        if _text(marker).upper() == "F" or raw.upper().startswith("F")
        else Decimal("1")
    )
    digits = raw.lstrip("FfLl+-")
    if not digits.isdigit():
        raise ValueError(f"invalid start timing: {raw!r}")
    return sign * Decimal(digits) / Decimal(100)


def _race_date(row: Mapping[str, Any]) -> date:
    year = _text(row["kaisai_nen"])
    month_day = _text(row["kaisai_tsukihi"]).zfill(4)
    if len(year) != 4 or len(month_day) != 4 or not (year + month_day).isdigit():
        raise ValueError("invalid race date components")
    return date(int(year), int(month_day[:2]), int(month_day[2:]))


def source_race_id(row: Mapping[str, Any]) -> str:
    race_date = _race_date(row)
    venue = _text(row["kyoteijo_code"]).zfill(2)
    race_number = _optional_int(row["race_no"])
    if race_number is None or not 1 <= race_number <= 12:
        raise ValueError("invalid race number")
    if venue not in VENUE_NAMES:
        raise ValueError("invalid venue code")
    return f"{race_date:%Y%m%d}{venue}{race_number:02d}"


def target_race_id(row: Mapping[str, Any]) -> uuid.UUID:
    return uuid.uuid5(RACE_NAMESPACE, source_race_id(row))


def _scheduled_at(row: Mapping[str, Any]) -> datetime:
    raw = _text(row["shimekiri_yotei_jikoku"]).zfill(4)
    if len(raw) != 4 or not raw.isdigit():
        raise ValueError("invalid scheduled time")
    hour, minute = int(raw[:2]), int(raw[2:])
    if hour > 23 or minute > 59:
        raise ValueError("invalid scheduled time")
    timezone = ZoneInfo(get_settings().app_timezone)
    return datetime.combine(_race_date(row), time(hour, minute), tzinfo=timezone)


def transform_race(row: Mapping[str, Any]) -> dict[str, Any]:
    venue_code = _text(row["kyoteijo_code"]).zfill(2)
    return {
        "id": target_race_id(row),
        "source_id": source_race_id(row),
        "race_date": _race_date(row),
        "venue_code": venue_code,
        "race_number": int(_text(row["race_no"])),
        "scheduled_at": _scheduled_at(row),
        "grade": _text(row.get("race_mei")) or None,
        "distance_m": _optional_int(row.get("kyori")),
        "source_updated_at": None,
    }


def transform_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    lane = _optional_int(row["teiban"])
    if lane is None or not 1 <= lane <= 6:
        raise ValueError("invalid lane")
    racer_number = _text(row.get("toroku_bango")) or None
    return {
        "race_id": target_race_id(row),
        "lane": lane,
        "racer_registration_number": racer_number,
        "class_name": _text(row.get("kyubetsu")) or None,
        "motor_number": _optional_int(row.get("motor_no")),
        "boat_number": _optional_int(row.get("boat_no")),
        "weight_kg": _scaled_decimal(row.get("taiju"), 10, zero_is_missing=True),
        "racer_name": _text(row.get("shimei")) or racer_number,
    }


def transform_exhibition(
    row: Mapping[str, Any], race_entry_id: int, observed_at: datetime
) -> dict[str, Any]:
    return {
        "race_entry_id": race_entry_id,
        "exhibition_course": _optional_int(row.get("tenji_shinnyu_course")),
        "exhibition_start_timing": _start_timing(row.get("tenji_st"), row.get("tenji_kigo")),
        "exhibition_time_seconds": _scaled_decimal(
            row.get("tenji_time"), 100, zero_is_missing=True
        ),
        "tilt": _scaled_decimal(row.get("tilt"), 10),
        "observed_at": observed_at,
        "source_payload": {
            "record_id": _text(row.get("record_id")) or None,
            "tenji_kigo": _text(row.get("tenji_kigo")) or None,
            "observed_at_strategy": "scheduled_at",
        },
    }


def transform_lap_exhibition(
    row: Mapping[str, Any], race_entry_id: int, observed_at: datetime
) -> dict[str, Any]:
    return {
        "race_entry_id": race_entry_id,
        "half_lap_time_seconds": _scaled_decimal(row.get("hanshu"), 100, zero_is_missing=True),
        "lap_time_seconds": _scaled_decimal(row.get("isshu"), 100, zero_is_missing=True),
        "cornering_time_seconds": _scaled_decimal(row.get("mawariashi"), 100, zero_is_missing=True),
        "straight_time_seconds": _scaled_decimal(row.get("chokusen"), 100, zero_is_missing=True),
        "observed_at": observed_at,
        "lap_source_payload": {
            "record_id": _text(row.get("record_id")) or None,
            "observed_at_strategy": "scheduled_at",
        },
    }


def transform_result(row: Mapping[str, Any], race_result_id: int) -> dict[str, Any]:
    lane = _optional_int(row["teiban"])
    if lane is None or not 1 <= lane <= 6:
        raise ValueError("invalid result lane")
    finish_raw = _text(row.get("chakujun"))
    finish = int(finish_raw) if finish_raw.isdigit() else None
    if finish not in range(1, 7):
        finish = None
    return {
        "race_result_id": race_result_id,
        "lane": lane,
        "finish_position": finish,
        "actual_course": _optional_int(row.get("shinnyu_course")),
        "actual_start_timing": _start_timing(row.get("st")),
        "status": "finished" if finish is not None else finish_raw or "unknown",
    }


def _chunks(rows: Iterable[Mapping[str, Any]], size: int = BATCH_SIZE) -> Iterator[list]:
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _bulk_upsert(
    session: Session,
    model,
    values: list[dict[str, Any]],
    index_elements: list[str],
) -> None:
    if not values:
        return
    statement = insert(model).values(values)
    mutable = set(values[0]) - set(index_elements) - {"id"}
    updates = {name: getattr(statement.excluded, name) for name in mutable}
    session.execute(statement.on_conflict_do_update(index_elements=index_elements, set_=updates))


def _source_rows(
    connection,
    table: Table,
    names: list[str],
    date_from: date | None = None,
):
    missing = [name for name in names if name not in table.c]
    if missing:
        raise ValueError(f"{table.fullname} is missing required columns: {missing}")
    statement = select(*(table.c[name] for name in names))
    if date_from is not None:
        year = str(date_from.year)
        month_day = f"{date_from.month:02d}{date_from.day:02d}"
        statement = statement.where(
            or_(
                table.c.kaisai_nen > year,
                and_(
                    table.c.kaisai_nen == year,
                    table.c.kaisai_tsukihi >= month_day,
                ),
            )
        )
    statement = statement.execution_options(stream_results=True, yield_per=BATCH_SIZE)
    return connection.execute(statement).mappings()


def _record_errors(
    session: Session,
    batch_id: uuid.UUID,
    entity: str,
    errors: list[tuple[str | None, str]],
) -> None:
    session.add_all(
        ImportError(
            import_batch_id=batch_id,
            entity=entity,
            source_key=source_key,
            reason=reason,
        )
        for source_key, reason in errors
    )


def _safe_transform(rows, transform):
    values = []
    errors = []
    for row in rows:
        try:
            values.append(transform(row))
        except (KeyError, TypeError, ValueError) as exc:
            try:
                key = source_race_id(row)
            except (KeyError, TypeError, ValueError):
                key = None
            errors.append((key, str(exc)))
    return values, errors


def _reflect_tables(source_engine, mapping: dict[str, Any]) -> dict[str, Table]:
    schema = mapping.get("schema") or get_settings().source_schema
    metadata = MetaData()
    return {
        entity: Table(name, metadata, schema=schema, autoload_with=source_engine)
        for entity, name in mapping["tables"].items()
    }


class ImportAlreadyRunning(RuntimeError):
    pass


def run_brd_import(mapping: dict[str, Any], date_from: date | None = None) -> ImportBatch:
    with engine.connect() as lock_connection:
        acquired = lock_connection.execute(
            sql_text("SELECT pg_try_advisory_lock(:key)"),
            {"key": IMPORT_LOCK_KEY},
        ).scalar_one()
        if not acquired:
            raise ImportAlreadyRunning("An import is already running")
        try:
            return _run_brd_import(mapping, date_from)
        finally:
            lock_connection.execute(
                sql_text("SELECT pg_advisory_unlock(:key)"),
                {"key": IMPORT_LOCK_KEY},
            )


def _run_brd_import(mapping: dict[str, Any], date_from: date | None = None) -> ImportBatch:
    source_engine = create_source_engine()
    current_date = datetime.now(ZoneInfo(get_settings().app_timezone)).date()
    with Session(engine) as session:
        batch = ImportBatch(
            status=ImportStatus.RUNNING,
            high_water_mark=date_from.isoformat() if date_from else None,
        )
        session.add(batch)
        session.commit()
        session.refresh(batch)
        batch_id = batch.id

    rows_read = 0
    rows_written = 0
    errors_count = 0
    try:
        tables = _reflect_tables(source_engine, mapping)
        with source_engine.connect() as source_connection:
            source_connection.exec_driver_sql("SET TRANSACTION READ ONLY")

            race_rows = _source_rows(
                source_connection,
                tables["races"],
                SOURCE_COLUMNS["races"],
                date_from,
            )
            for raw_batch in _chunks(race_rows):
                values, errors = _safe_transform(raw_batch, transform_race)
                rows_read += len(raw_batch)
                errors_count += len(errors)
                with Session(engine) as session:
                    venues = {
                        value["venue_code"]: VENUE_NAMES[value["venue_code"]] for value in values
                    }
                    _bulk_upsert(
                        session,
                        Venue,
                        [{"code": code, "name": name} for code, name in venues.items()],
                        ["code"],
                    )
                    _bulk_upsert(session, Race, values, ["source_id"])
                    _record_errors(session, batch_id, "race", errors)
                    session.commit()
                rows_written += len(values)
            source_connection.commit()

            entry_rows = _source_rows(
                source_connection,
                tables["entries"],
                SOURCE_COLUMNS["entries"],
                date_from,
            )
            for raw_batch in _chunks(entry_rows):
                values, errors = _safe_transform(raw_batch, transform_entry)
                rows_read += len(raw_batch)
                with Session(engine) as session:
                    race_ids = {value["race_id"] for value in values}
                    existing_race_ids = set(
                        session.scalars(select(Race.id).where(Race.id.in_(race_ids)))
                    )
                    accepted = []
                    racers = {}
                    for value in values:
                        if value["race_id"] not in existing_race_ids:
                            errors.append((None, "entry references a race excluded during import"))
                            continue
                        name = value.pop("racer_name")
                        number = value["racer_registration_number"]
                        if number:
                            racers[number] = name or number
                        accepted.append(value)
                    _bulk_upsert(
                        session,
                        Racer,
                        [
                            {"registration_number": number, "name": name}
                            for number, name in racers.items()
                        ],
                        ["registration_number"],
                    )
                    _bulk_upsert(session, RaceEntry, accepted, ["race_id", "lane"])
                    _record_errors(session, batch_id, "entry", errors)
                    session.commit()
                errors_count += len(errors)
                rows_written += len(accepted)
            source_connection.commit()

            exhibition_rows = _source_rows(
                source_connection,
                tables["exhibitions"],
                SOURCE_COLUMNS["exhibitions"],
                date_from,
            )
            for raw_batch in _chunks(exhibition_rows):
                rows_read += len(raw_batch)
                errors = []
                race_keys = []
                for row in raw_batch:
                    try:
                        race_keys.append((target_race_id(row), int(_text(row["teiban"]))))
                    except (KeyError, TypeError, ValueError) as exc:
                        errors.append((None, str(exc)))
                with Session(engine) as session:
                    entry_map = {
                        (race_id, lane): entry_id
                        for race_id, lane, entry_id in session.execute(
                            select(RaceEntry.race_id, RaceEntry.lane, RaceEntry.id).where(
                                tuple_(RaceEntry.race_id, RaceEntry.lane).in_(race_keys)
                            )
                        )
                    }
                    official_entry_ids = {
                        entry_id
                        for entry_id, payload in session.execute(
                            select(
                                ExhibitionObservation.race_entry_id,
                                ExhibitionObservation.source_payload,
                            ).where(
                                ExhibitionObservation.race_entry_id.in_(set(entry_map.values()))
                            )
                        )
                        if (payload or {}).get("source") == "boatrace.jp"
                    }
                    race_ids = {race_id for race_id, _ in race_keys}
                    schedule_map = dict(
                        session.execute(
                            select(Race.id, Race.scheduled_at).where(Race.id.in_(race_ids))
                        ).all()
                    )
                    values = []
                    part_values = []
                    for row in raw_batch:
                        try:
                            key = (target_race_id(row), int(_text(row["teiban"])))
                            entry_id = entry_map[key]
                            observed_at = schedule_map[key[0]]
                            if observed_at is None:
                                raise ValueError("race is missing scheduled_at")
                            if entry_id not in official_entry_ids:
                                values.append(transform_exhibition(row, entry_id, observed_at))
                            for column, part_name in PART_COLUMNS.items():
                                quantity = _optional_int(row.get(column)) or 0
                                if quantity > 0:
                                    part_values.append(
                                        {
                                            "race_entry_id": entry_id,
                                            "part_name": part_name,
                                            "quantity": quantity,
                                            "replaced_at": observed_at,
                                        }
                                    )
                        except (KeyError, TypeError, ValueError) as exc:
                            errors.append((None, str(exc)))
                    _bulk_upsert(
                        session,
                        ExhibitionObservation,
                        values,
                        ["race_entry_id", "observed_at"],
                    )
                    _bulk_upsert(
                        session,
                        PartReplacement,
                        part_values,
                        ["race_entry_id", "part_name", "replaced_at"],
                    )
                    _record_errors(session, batch_id, "exhibition", errors)
                    session.commit()
                errors_count += len(errors)
                rows_written += len(values) + len(part_values)
            source_connection.commit()

            lap_exhibition_rows = _source_rows(
                source_connection,
                tables["lap_exhibitions"],
                SOURCE_COLUMNS["lap_exhibitions"],
                date_from,
            )
            for raw_batch in _chunks(lap_exhibition_rows):
                rows_read += len(raw_batch)
                errors = []
                race_keys = []
                for row in raw_batch:
                    try:
                        race_keys.append((target_race_id(row), int(_text(row["teiban"]))))
                    except (KeyError, TypeError, ValueError) as exc:
                        errors.append((None, str(exc)))
                with Session(engine) as session:
                    entry_map = {
                        (race_id, lane): entry_id
                        for race_id, lane, entry_id in session.execute(
                            select(RaceEntry.race_id, RaceEntry.lane, RaceEntry.id).where(
                                tuple_(RaceEntry.race_id, RaceEntry.lane).in_(race_keys)
                            )
                        )
                    }
                    race_ids = {race_id for race_id, _ in race_keys}
                    boatcast_entry_ids = {
                        entry_id
                        for entry_id, payload in session.execute(
                            select(
                                ExhibitionObservation.race_entry_id,
                                ExhibitionObservation.lap_source_payload,
                            ).where(
                                ExhibitionObservation.race_entry_id.in_(set(entry_map.values()))
                            )
                        )
                        if (payload or {}).get("source") == "race.boatcast.jp"
                    }
                    schedule_map = dict(
                        session.execute(
                            select(Race.id, Race.scheduled_at).where(Race.id.in_(race_ids))
                        ).all()
                    )
                    values = []
                    for row in raw_batch:
                        try:
                            if _race_date(row) >= current_date:
                                continue
                            key = (target_race_id(row), int(_text(row["teiban"])))
                            entry_id = entry_map[key]
                            if entry_id in boatcast_entry_ids:
                                continue
                            observed_at = schedule_map[key[0]]
                            if observed_at is None:
                                raise ValueError("race is missing scheduled_at")
                            values.append(transform_lap_exhibition(row, entry_id, observed_at))
                        except (KeyError, TypeError, ValueError) as exc:
                            errors.append((None, str(exc)))
                    _bulk_upsert(
                        session,
                        ExhibitionObservation,
                        values,
                        ["race_entry_id", "observed_at"],
                    )
                    _record_errors(session, batch_id, "lap_exhibition", errors)
                    session.commit()
                errors_count += len(errors)
                rows_written += len(values)
            source_connection.commit()

            weather_rows = _source_rows(
                source_connection,
                tables["weather"],
                SOURCE_COLUMNS["weather"],
                date_from,
            )
            for raw_batch in _chunks(weather_rows):
                rows_read += len(raw_batch)
                values = []
                errors = []
                race_ids = []
                for row in raw_batch:
                    try:
                        race_ids.append(target_race_id(row))
                    except (KeyError, TypeError, ValueError) as exc:
                        errors.append((None, str(exc)))
                with Session(engine) as session:
                    schedule_map = dict(
                        session.execute(
                            select(Race.id, Race.scheduled_at).where(Race.id.in_(race_ids))
                        ).all()
                    )
                    for row in raw_batch:
                        try:
                            race_id = target_race_id(row)
                            observed_at = schedule_map[race_id]
                            if observed_at is None:
                                raise ValueError("race is missing scheduled_at")
                            values.append(
                                {
                                    "race_id": race_id,
                                    "weather": _text(row.get("tenki_code")) or None,
                                    "air_temperature_c": _scaled_decimal(row.get("kion"), 10),
                                    "water_temperature_c": _scaled_decimal(row.get("suion"), 10),
                                    "wind_direction": _text(row.get("fuko_code")) or None,
                                    "wind_speed_mps": _scaled_decimal(row.get("fusoku"), 1),
                                    "wave_height_cm": _optional_int(row.get("hako")),
                                    "observed_at": observed_at,
                                }
                            )
                        except (KeyError, TypeError, ValueError) as exc:
                            errors.append((None, str(exc)))
                    _bulk_upsert(
                        session,
                        WeatherObservation,
                        values,
                        ["race_id", "observed_at"],
                    )
                    _record_errors(session, batch_id, "weather", errors)
                    session.commit()
                errors_count += len(errors)
                rows_written += len(values)
            source_connection.commit()

            result_rows = (
                _source_rows(
                    source_connection,
                    tables["results"],
                    SOURCE_COLUMNS["results"],
                    date_from,
                )
                if date_from is None
                else []
            )
            for raw_batch in _chunks(result_rows):
                rows_read += len(raw_batch)
                errors = []
                race_ids = []
                for row in raw_batch:
                    try:
                        race_ids.append(target_race_id(row))
                    except (KeyError, TypeError, ValueError) as exc:
                        errors.append((None, str(exc)))
                with Session(engine) as session:
                    existing_race_ids = set(
                        session.scalars(select(Race.id).where(Race.id.in_(race_ids)))
                    )
                    for _race_id in set(race_ids) - existing_race_ids:
                        errors.append((None, "result references a race excluded during import"))
                    if existing_race_ids:
                        statement = insert(RaceResult).values(
                            [{"race_id": race_id} for race_id in existing_race_ids]
                        )
                        session.execute(
                            statement.on_conflict_do_nothing(index_elements=["race_id"])
                        )
                    session.flush()
                    result_map = dict(
                        session.execute(
                            select(RaceResult.race_id, RaceResult.id).where(
                                RaceResult.race_id.in_(existing_race_ids)
                            )
                        ).all()
                    )
                    official_race_ids = set(
                        session.scalars(
                            select(RaceResult.race_id).where(
                                RaceResult.race_id.in_(existing_race_ids),
                                RaceResult.source == "boatrace.jp",
                            )
                        )
                    )
                    values = []
                    for row in raw_batch:
                        try:
                            race_id = target_race_id(row)
                            if race_id in official_race_ids:
                                continue
                            values.append(transform_result(row, result_map[race_id]))
                        except (KeyError, TypeError, ValueError) as exc:
                            errors.append((None, str(exc)))
                    _bulk_upsert(
                        session,
                        ResultEntry,
                        values,
                        ["race_result_id", "lane"],
                    )
                    _record_errors(session, batch_id, "result", errors)
                    session.commit()
                errors_count += len(errors)
                rows_written += len(values)
            source_connection.commit()

        with Session(engine) as session:
            batch = session.get(ImportBatch, batch_id)
            batch.status = ImportStatus.SUCCEEDED
            batch.completed_at = datetime.now(ZoneInfo("UTC"))
            batch.rows_read = rows_read
            batch.rows_written = rows_written
            batch.errors_count = errors_count
            session.commit()
            session.refresh(batch)
            return batch
    except Exception as exc:
        with Session(engine) as session:
            batch = session.get(ImportBatch, batch_id)
            batch.status = ImportStatus.FAILED
            batch.completed_at = datetime.now(ZoneInfo("UTC"))
            batch.rows_read = rows_read
            batch.rows_written = rows_written
            batch.errors_count = errors_count
            batch.error_message = type(exc).__name__
            session.commit()
        raise
    finally:
        source_engine.dispose()
