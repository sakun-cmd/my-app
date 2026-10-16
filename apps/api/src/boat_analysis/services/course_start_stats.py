from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from threading import Lock

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..database import create_source_engine, engine
from ..models import RacerCourseStartStat

COURSE_STATS_LOOKBACK_DAYS = 365
COURSE_STATS_SOURCE = "source_raw_results_365d"
_REFRESH_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class DerivedCourseStartStat:
    racer_registration_number: str
    course_no: int
    starts: int
    average_start_timing: Decimal | None
    average_start_rank: Decimal | None
    top3_finishes: int
    top3_rate: Decimal | None
    history_from: date
    history_through: date | None


_SOURCE_STATS_QUERY = text(
    """
    WITH target_pairs AS MATERIALIZED (
        SELECT DISTINCT
               btrim(toroku_bango) AS racer_registration_number,
               CASE
                   WHEN btrim(teiban) ~ '^[1-6]$' THEN teiban::integer
               END AS course_no
        FROM public.brd_b3
        WHERE (kaisai_nen || lpad(kaisai_tsukihi, 4, '0')) = :snapshot_key
          AND btrim(toroku_bango) ~ '^[0-9]+$'
          AND btrim(teiban) ~ '^[1-6]$'
    ),
    starts AS MATERIALIZED (
        SELECT h.kaisai_nen, h.kaisai_tsukihi, h.kyoteijo_code,
               h.race_no, h.teiban,
               btrim(h.toroku_bango) AS racer_registration_number,
               CASE
                   WHEN btrim(h.shinnyu_course) ~ '^[1-6]$'
                   THEN h.shinnyu_course::integer
               END AS course_no,
               CASE
                   WHEN btrim(h.st) ~ '^[0-9]{3}$'
                   THEN h.st::numeric / 100
               END AS start_timing,
               CASE
                   WHEN btrim(h.chakujun) ~ '^[0-9]+$'
                   THEN h.chakujun::integer
               END AS finish_position,
               1 + count(c.teiban) FILTER (
                   WHERE
                       CASE
                           WHEN btrim(c.st) ~ '^[0-9]{3}$' THEN c.st::integer
                       END
                       <
                       CASE
                           WHEN btrim(h.st) ~ '^[0-9]{3}$' THEN h.st::integer
                       END
               ) AS start_rank,
               to_date(
                   h.kaisai_nen || lpad(h.kaisai_tsukihi, 4, '0'),
                   'YYYYMMDD'
               ) AS result_date
        FROM public.brd_k3 h
        JOIN target_pairs target
          ON target.racer_registration_number = btrim(h.toroku_bango)
         AND target.course_no = CASE
             WHEN btrim(h.shinnyu_course) ~ '^[1-6]$'
             THEN h.shinnyu_course::integer
         END
        LEFT JOIN public.brd_k3 c
          ON c.kaisai_nen = h.kaisai_nen
         AND c.kaisai_tsukihi = h.kaisai_tsukihi
         AND c.kyoteijo_code = h.kyoteijo_code
         AND c.race_no = h.race_no
         AND btrim(c.st) ~ '^[0-9]{3}$'
        WHERE (h.kaisai_nen || lpad(h.kaisai_tsukihi, 4, '0'))
              BETWEEN :history_from_key AND :history_through_key
          AND btrim(h.shinnyu_course) ~ '^[1-6]$'
          AND btrim(h.st) ~ '^[0-9]{3}$'
        GROUP BY h.kaisai_nen, h.kaisai_tsukihi, h.kyoteijo_code,
                 h.race_no, h.teiban, h.toroku_bango,
                 h.shinnyu_course, h.st, h.chakujun
    )
    SELECT target.racer_registration_number,
           target.course_no,
           count(starts.teiban) AS starts,
           avg(starts.start_timing) AS average_start_timing,
           avg(starts.start_rank) AS average_start_rank,
           count(starts.teiban) FILTER (
               WHERE starts.finish_position BETWEEN 1 AND 3
           ) AS top3_finishes,
           max(starts.result_date) AS history_through
    FROM target_pairs target
    LEFT JOIN starts
      ON starts.racer_registration_number = target.racer_registration_number
     AND starts.course_no = target.course_no
    GROUP BY target.racer_registration_number, target.course_no
    ORDER BY target.racer_registration_number, target.course_no
    """
)


def fetch_derived_course_start_stats(snapshot_date: date) -> list[DerivedCourseStartStat]:
    history_from = snapshot_date - timedelta(days=COURSE_STATS_LOOKBACK_DAYS)
    history_through = snapshot_date - timedelta(days=1)
    engine = create_source_engine()
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            rows = connection.execute(
                _SOURCE_STATS_QUERY,
                {
                    "snapshot_key": snapshot_date.strftime("%Y%m%d"),
                    "history_from_key": history_from.strftime("%Y%m%d"),
                    "history_through_key": history_through.strftime("%Y%m%d"),
                },
            ).mappings()
            result = []
            for row in rows:
                starts = int(row["starts"])
                top3_finishes = int(row["top3_finishes"])
                result.append(
                    DerivedCourseStartStat(
                        racer_registration_number=row["racer_registration_number"],
                        course_no=int(row["course_no"]),
                        starts=starts,
                        average_start_timing=(
                            Decimal(row["average_start_timing"])
                            if row["average_start_timing"] is not None
                            else None
                        ),
                        average_start_rank=(
                            Decimal(row["average_start_rank"])
                            if row["average_start_rank"] is not None
                            else None
                        ),
                        top3_finishes=top3_finishes,
                        top3_rate=(
                            Decimal(top3_finishes) / Decimal(starts) * Decimal("100")
                            if starts
                            else None
                        ),
                        history_from=history_from,
                        history_through=row["history_through"],
                    )
                )
            connection.rollback()
            return result
    finally:
        engine.dispose()


def refresh_course_start_stats(
    snapshot_date: date,
    db: Session,
    required_pairs: set[tuple[str, int]] | None = None,
) -> dict[tuple[str, int], RacerCourseStartStat]:
    with _REFRESH_LOCK:
        existing = load_course_start_stats(snapshot_date, db)
        if existing and (
            required_pairs is None or required_pairs.issubset(existing)
        ):
            return existing
        derived = fetch_derived_course_start_stats(snapshot_date)
        if not derived:
            return {}
        values = [
            {
                "racer_registration_number": item.racer_registration_number,
                "course_no": item.course_no,
                "snapshot_date": snapshot_date,
                "starts": item.starts,
                "average_start_timing": item.average_start_timing,
                "average_start_rank": item.average_start_rank,
                "top3_finishes": item.top3_finishes,
                "top3_rate": item.top3_rate,
                "history_from": item.history_from,
                "history_through": item.history_through,
                "source": COURSE_STATS_SOURCE,
            }
            for item in derived
        ]
        statement = insert(RacerCourseStartStat).values(values)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    "racer_registration_number",
                    "course_no",
                    "snapshot_date",
                ],
                set_={
                    "starts": statement.excluded.starts,
                    "average_start_timing": statement.excluded.average_start_timing,
                    "average_start_rank": statement.excluded.average_start_rank,
                    "top3_finishes": statement.excluded.top3_finishes,
                    "top3_rate": statement.excluded.top3_rate,
                    "history_from": statement.excluded.history_from,
                    "history_through": statement.excluded.history_through,
                    "source": statement.excluded.source,
                    "generated_at": func.now(),
                },
            )
        )
        db.commit()
        return load_course_start_stats(snapshot_date, db)


def load_course_start_stats(
    snapshot_date: date,
    db: Session,
) -> dict[tuple[str, int], RacerCourseStartStat]:
    rows = db.scalars(
        select(RacerCourseStartStat).where(
            RacerCourseStartStat.snapshot_date == snapshot_date
        )
    ).all()
    return {
        (row.racer_registration_number, row.course_no): row
        for row in rows
    }


def get_course_start_stats(
    snapshot_date: date,
    required_pairs: set[tuple[str, int]],
    db: Session,
) -> dict[tuple[str, int], RacerCourseStartStat]:
    existing = load_course_start_stats(snapshot_date, db)
    if required_pairs.issubset(existing):
        return existing
    return refresh_course_start_stats(snapshot_date, db, required_pairs)


def ensure_course_start_stats(snapshot_date: date) -> int:
    with Session(engine) as db:
        existing_count = db.scalar(
            select(func.count())
            .select_from(RacerCourseStartStat)
            .where(RacerCourseStartStat.snapshot_date == snapshot_date)
        )
        if existing_count:
            return int(existing_count)
        return len(refresh_course_start_stats(snapshot_date, db))
