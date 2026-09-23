from datetime import date
from decimal import Decimal

from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.dialects import postgresql

from boat_analysis.services.brd_importer import (
    _scheduled_at,
    _source_rows,
    _start_timing,
    source_race_id,
    transform_entry,
    transform_exhibition,
    transform_lap_exhibition,
    transform_result,
)


def race_key() -> dict[str, str]:
    return {
        "kaisai_nen": "2026",
        "kaisai_tsukihi": "0909",
        "kyoteijo_code": "01",
        "race_no": "1",
    }


def test_race_identity_and_jst_schedule() -> None:
    row = {**race_key(), "shimekiri_yotei_jikoku": "1030"}
    assert source_race_id(row) == "202609090101"
    scheduled = _scheduled_at(row)
    assert scheduled.date() == date(2026, 9, 9)
    assert scheduled.utcoffset().total_seconds() == 9 * 60 * 60


def test_fixed_point_and_flying_start_conversion() -> None:
    assert _start_timing("001") == Decimal("0.01")
    assert _start_timing("001", "F") == Decimal("-0.01")


def test_entry_fixed_point_weight() -> None:
    entry = transform_entry(
        {
            **race_key(),
            "teiban": "1",
            "toroku_bango": "1234",
            "shimei": "選手",
            "kyubetsu": "A1",
            "taiju": "520",
            "motor_no": "12",
            "boat_no": "34",
        }
    )
    assert entry["weight_kg"] == Decimal("52")


def test_exhibition_conversion() -> None:
    observed_at = _scheduled_at({**race_key(), "shimekiri_yotei_jikoku": "1030"})
    exhibition = transform_exhibition(
        {
            "record_id": "x",
            "tenji_shinnyu_course": "2",
            "tenji_st": "005",
            "tenji_kigo": "",
            "tenji_time": "0680",
            "tilt": "-05",
        },
        10,
        observed_at,
    )
    assert exhibition["exhibition_time_seconds"] == Decimal("6.8")
    assert exhibition["exhibition_start_timing"] == Decimal("0.05")
    assert exhibition["tilt"] == Decimal("-0.5")


def test_lap_exhibition_conversion_and_missing_values() -> None:
    observed_at = _scheduled_at({**race_key(), "shimekiri_yotei_jikoku": "1030"})
    exhibition = transform_lap_exhibition(
        {
            "record_id": "x",
            "hanshu": "1863",
            "isshu": "0000",
            "mawariashi": "0460",
            "chokusen": "0770",
        },
        10,
        observed_at,
    )
    assert exhibition["half_lap_time_seconds"] == Decimal("18.63")
    assert exhibition["lap_time_seconds"] is None
    assert exhibition["cornering_time_seconds"] == Decimal("4.6")
    assert exhibition["straight_time_seconds"] == Decimal("7.7")


def test_non_numeric_finish_is_status() -> None:
    result = transform_result(
        {
            **race_key(),
            "teiban": "3",
            "chakujun": "F",
            "shinnyu_course": "3",
            "st": "F01",
        },
        99,
    )
    assert result["finish_position"] is None
    assert result["status"] == "F"
    assert result["actual_start_timing"] == Decimal("-0.01")


def test_live_source_query_is_date_filtered() -> None:
    table = Table(
        "brd_b2",
        MetaData(),
        Column("kaisai_nen", String),
        Column("kaisai_tsukihi", String),
        Column("race_no", String),
    )

    class Connection:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return self

        def mappings(self):
            return []

    connection = Connection()
    list(
        _source_rows(
            connection,
            table,
            ["kaisai_nen", "kaisai_tsukihi", "race_no"],
            date(2026, 9, 9),
        )
    )
    sql = str(
        connection.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "kaisai_nen > '2026'" in sql
    assert "kaisai_tsukihi >= '0909'" in sql
