from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from ..database import create_source_engine


def _scaled_start_timing(value: Any) -> Decimal | None:
    raw = "" if value is None else str(value).strip()
    if not raw or not raw.lstrip("-").isdigit():
        return None
    return Decimal(raw) / Decimal(100)


def fetch_average_start_timings(date_from: date, date_to: date) -> dict[str, dict[int, Decimal]]:
    """選手の平均ST（brd_l3.avg_st）をレースキー・艇番ごとに取得する。"""
    engine = create_source_engine()
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            rows = connection.execute(
                text(
                    """
                    SELECT kaisai_nen, kaisai_tsukihi, kyoteijo_code, race_no,
                           teiban, avg_st
                    FROM public.brd_l3
                    WHERE (kaisai_nen || lpad(kaisai_tsukihi, 4, '0'))
                          BETWEEN :date_from AND :date_to
                    """
                ),
                {
                    "date_from": date_from.strftime("%Y%m%d"),
                    "date_to": date_to.strftime("%Y%m%d"),
                },
            ).mappings()
            result: dict[str, dict[int, Decimal]] = {}
            for row in rows:
                value = _scaled_start_timing(row["avg_st"])
                if value is None:
                    continue
                key = (
                    f"{row['kaisai_nen']}{str(row['kaisai_tsukihi']).zfill(4)}"
                    f"{str(row['kyoteijo_code']).zfill(2)}"
                    f"{int(str(row['race_no']).strip()):02d}"
                )
                result.setdefault(key, {})[int(str(row["teiban"]).strip())] = value
            connection.rollback()
            return result
    finally:
        engine.dispose()
