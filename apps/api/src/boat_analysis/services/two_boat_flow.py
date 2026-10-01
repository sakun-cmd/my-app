from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from itertools import permutations
from statistics import mean, median
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..database import create_source_engine
from ..models import ExhibitionObservation, Race, RaceEntry, WinOddsObservation
from .official_results import OFFICIAL_RESULT_SOURCE
from .standard_correction import get_correction

EXHIBITION_GAP = Decimal("0.10")
MIN_COURSE_STARTS = 10
COURSE_STATS_HISTORY_AVAILABLE_FROM = date(2026, 7, 7)
COURSE_STATS_INITIAL_SNAPSHOT_UNCERTAIN_THROUGH = date(2026, 7, 8)
DISCLAIMER = (
    "この判定は指定ルールを過去・展示データへ機械的に適用した参考情報です。"
    "的中や利益を保証せず、自動投票も行いません。最終判断は利用者が行ってください。"
)


@dataclass(frozen=True)
class FlowBoat:
    lane: int
    exhibition_time: Decimal | None
    lap_time: Decimal | None
    course_avg_start_rank: Decimal | None
    course_avg_start_timing: Decimal | None
    nationwide_win_rate: Decimal | None
    course_top3_rate: Decimal | None
    course_starts: int | None = None
    course_stats_snapshot_date: date | None = None
    finish_position: int | None = None


def _scaled(value: Any, scale: int = 100) -> Decimal | None:
    raw = "" if value is None else str(value).strip()
    if not raw or not raw.lstrip("-").isdigit():
        return None
    parsed = Decimal(raw) / Decimal(scale)
    return None if parsed == 0 else parsed


def _decimal(value: Any, scale: int = 1) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)) / Decimal(scale)


def _apply_standard_correction(boats: list[FlowBoat], venue_code: str | None) -> list[FlowBoat]:
    """展示・一周タイムへスタンダード版補正値を加算した比較用の艇一覧を返す。

    生値の`boats`は変更せず、艇間比較にだけ補正後の値を使う。
    """
    return [
        replace(
            item,
            exhibition_time=(
                item.exhibition_time + get_correction(venue_code, item.lane, "exhibition")
                if item.exhibition_time is not None
                else None
            ),
            lap_time=(
                item.lap_time + get_correction(venue_code, item.lane, "lap")
                if item.lap_time is not None
                else None
            ),
        )
        for item in boats
    ]


def _ranks(values: dict[int, Decimal | None]) -> dict[int, int | None]:
    ordered = sorted({value for value in values.values() if value is not None})
    return {
        lane: ordered.index(value) + 1 if value is not None else None
        for lane, value in values.items()
    }


def _top_two_lanes(
    values: dict[int, Decimal | None], *, higher_is_better: bool = False
) -> set[int]:
    ranked_values = (
        {lane: -value if value is not None else None for lane, value in values.items()}
        if higher_is_better
        else values
    )
    ranks = _ranks(ranked_values)
    return {lane for lane, rank in ranks.items() if rank is not None and rank <= 2}


def _build_tickets(
    boats: list[FlowBoat],
    likely_lanes: list[int],
    outer_outer_lane: int | None,
    escape_assessment: str,
) -> list[tuple[int, int, int]]:
    by_time = sorted(
        boats,
        key=lambda item: (
            item.exhibition_time is None,
            item.exhibition_time or Decimal("999"),
            item.lane,
        ),
    )
    tickets: set[tuple[int, int, int]] = set()
    if escape_assessment == "likely":
        excluded = {1, *likely_lanes}
        companions = [item.lane for item in by_time if item.lane not in excluded][:2]
        pool = list(dict.fromkeys([*likely_lanes, *companions]))
        for second, third in permutations(pool, 2):
            if second in likely_lanes or third in likely_lanes:
                tickets.add((1, second, third))
    elif escape_assessment == "unlikely":
        partner = outer_outer_lane if outer_outer_lane not in likely_lanes else None
        excluded = {*likely_lanes, *([partner] if partner else [])}
        companions = [item.lane for item in by_time if item.lane not in excluded][:1]
        second_pool = list(
            dict.fromkeys(
                [
                    *likely_lanes,
                    *([partner] if partner and partner != 1 else []),
                    *companions,
                ]
            )
        )
        for head in likely_lanes:
            for second in second_pool:
                if second == head:
                    continue
                for third in range(1, 7):
                    if third not in {head, second}:
                        tickets.add((head, second, third))
    return sorted(tickets)


def _popularity_ranks(
    odds: dict[tuple[int, int, int], Decimal] | None,
) -> dict[tuple[int, int, int], int]:
    if not odds:
        return {}
    return {
        combination: rank
        for rank, (combination, _) in enumerate(
            sorted(
                ((combination, value) for combination, value in odds.items() if value > 0),
                key=lambda item: (item[1], item[0]),
            ),
            start=1,
        )
    }


def result_winning_combination(
    entries: list[tuple[int, int | None]],
) -> tuple[int, int, int] | None:
    """(艇番, 着順)の一覧から確定済み3連単の着順組み合わせを返す。"""
    ordered = sorted(
        (item for item in entries if item[1] is not None),
        key=lambda item: item[1],
    )
    if len(ordered) < 3 or ordered[0][1] != 1:
        return None
    return (ordered[0][0], ordered[1][0], ordered[2][0])


def evaluate_two_boat_flow(
    boats: list[FlowBoat],
    odds: dict[tuple[int, int, int], Decimal] | None = None,
    win_odds: dict[int, Decimal] | None = None,
    venue_code: str | None = None,
) -> dict[str, Any]:
    boats = sorted(boats, key=lambda item: item.lane)
    raw_by_lane = {item.lane: item for item in boats}
    # 艇間の展示・一周タイム比較はすべてスタンダード版補正後の値で行う。
    compared = _apply_standard_correction(boats, venue_code)
    by_lane = {item.lane: item for item in compared}
    correction_applied = any(
        by_lane[lane].exhibition_time != raw.exhibition_time
        or by_lane[lane].lap_time != raw.lap_time
        for lane, raw in raw_by_lane.items()
    )
    basis_note = "（スタンダード版補正後の展示タイムで比較）" if correction_applied else ""
    win_popularity = {
        lane: rank
        for rank, (lane, _) in enumerate(
            sorted(
                ((lane, value) for lane, value in (win_odds or {}).items() if value > 0),
                key=lambda item: (item[1], item[0]),
            ),
            start=1,
        )
    }
    win_popularity.update(
        {lane: 6 for lane, value in (win_odds or {}).items() if value == 0}
    )
    exhibition_ranks = _ranks({item.lane: item.exhibition_time for item in compared})
    lap_ranks = _ranks({item.lane: item.lap_time for item in compared})
    ap_lanes = _top_two_lanes(
        {item.lane: item.exhibition_time for item in compared}
    ) | _top_two_lanes({item.lane: item.lap_time for item in compared})
    win_rate_top_two = _top_two_lanes(
        {item.lane: item.nationwide_win_rate for item in boats},
        higher_is_better=True,
    )
    course_top3_top_two = _top_two_lanes(
        {item.lane: item.course_top3_rate for item in boats},
        higher_is_better=True,
    )
    triggers = []
    for inner_lane in range(1, 6):
        inner = by_lane.get(inner_lane)
        outer = by_lane.get(inner_lane + 1)
        if (
            inner
            and outer
            and inner.exhibition_time is not None
            and outer.exhibition_time is not None
            and inner.exhibition_time - outer.exhibition_time >= EXHIBITION_GAP
        ):
            triggers.append(
                {
                    "inner_lane": inner_lane,
                    "outer_lane": inner_lane + 1,
                    "gap": inner.exhibition_time - outer.exhibition_time,
                }
            )

    metrics = [
        {
            "lane": item.lane,
            "exhibition_time": item.exhibition_time,
            "lap_time": item.lap_time,
            "exhibition_time_corrected": by_lane[item.lane].exhibition_time,
            "lap_time_corrected": by_lane[item.lane].lap_time,
            "exhibition_rank": exhibition_ranks[item.lane],
            "lap_rank": lap_ranks[item.lane],
            "course_avg_start_rank": item.course_avg_start_rank,
            "course_avg_start_timing": item.course_avg_start_timing,
            "nationwide_win_rate": item.nationwide_win_rate,
            "course_top3_rate": item.course_top3_rate,
            "course_starts": item.course_starts,
            "course_stats_snapshot_date": item.course_stats_snapshot_date,
            "win_odds": (win_odds or {}).get(item.lane),
            "popularity_rank": win_popularity.get(item.lane),
            "ap": item.lane in ap_lanes,
        }
        for item in boats
    ]
    steps = [
        {
            "number": 1,
            "result": "yes" if triggers else "no",
            "detail": (
                f"{len(triggers)}組が0.10秒以上の条件を満たしました{basis_note}"
                if triggers
                else f"隣接する外側艇に0.10秒以上の展示優位はありません{basis_note}"
            ),
        }
    ]
    if not triggers:
        return {
            "status": "pass",
            "outer_lane": None,
            "outer_outer_lane": None,
            "likely_lanes": [],
            "escape_assessment": "not_assessed",
            "metrics": metrics,
            "steps": steps,
            "tickets": [],
            "composite_odds": None,
            "decision": "pass",
            "disclaimer": DISCLAIMER,
        }

    trigger = max(triggers, key=lambda item: (item["gap"], -item["inner_lane"]))
    steps[0]["detail"] += (
        f"。最大差の{trigger['inner_lane']}号艇→{trigger['outer_lane']}号艇"
        f"（{trigger['gap']:.2f}秒）を判定します"
    )
    raw_inner_time = raw_by_lane[trigger["inner_lane"]].exhibition_time
    raw_outer_time = raw_by_lane[trigger["outer_lane"]].exhibition_time
    if correction_applied and raw_inner_time is not None and raw_outer_time is not None:
        raw_gap = raw_inner_time - raw_outer_time
        if raw_gap != trigger["gap"]:
            steps[0]["detail"] += f"（生タイム差{raw_gap:.2f}秒）"
    inner = by_lane[trigger["inner_lane"]]
    outer = by_lane[trigger["outer_lane"]]
    if inner.course_avg_start_rank is None or outer.course_avg_start_rank is None:
        steps.append(
            {
                "number": 2,
                "result": "unknown",
                "detail": "比較対象のコース平均ST順位が不足しているため判定できません",
            }
        )
        return {
            "status": "insufficient_data",
            "outer_lane": outer.lane,
            "outer_outer_lane": outer.lane + 1 if outer.lane < 6 else None,
            "likely_lanes": [],
            "escape_assessment": "not_assessed",
            "metrics": metrics,
            "steps": steps,
            "tickets": [],
            "composite_odds": None,
            "decision": "pass",
            "disclaimer": DISCLAIMER,
        }
    start_rank_better = outer.course_avg_start_rank < inner.course_avg_start_rank
    steps.append(
        {
            "number": 2,
            "result": "yes" if start_rank_better else "no",
            "detail": (
                f"{outer.lane}号艇のコース平均ST順位が内側艇より速い"
                if start_rank_better
                else f"{outer.lane}号艇のコース平均ST順位は内側艇より優位ではない"
            ),
        }
    )
    if not start_rank_better:
        outer_ap = outer.lane in ap_lanes
        steps.append(
            {
                "number": 3,
                "result": "yes" if outer_ap else "no",
                "detail": (
                    f"{outer.lane}号艇は展示または一周の2番時計以内"
                    if outer_ap
                    else f"{outer.lane}号艇にAPポイントはありません"
                ),
            }
        )
        if not outer_ap:
            return {
                "status": "pass",
                "outer_lane": outer.lane,
                "outer_outer_lane": outer.lane + 1 if outer.lane < 6 else None,
                "likely_lanes": [],
                "escape_assessment": "not_assessed",
                "metrics": metrics,
                "steps": steps,
                "tickets": [],
                "composite_odds": None,
                "decision": "pass",
                "disclaimer": DISCLAIMER,
            }

    outer_outer = by_lane.get(outer.lane + 1)
    clearly_better = bool(
        outer_outer
        and outer.exhibition_time is not None
        and outer_outer.exhibition_time is not None
        and outer_outer.exhibition_time <= outer.exhibition_time
        and outer.course_avg_start_rank is not None
        and outer_outer.course_avg_start_rank is not None
        and outer_outer.course_avg_start_rank <= outer.course_avg_start_rank
    )
    steps.append(
        {
            "number": 4,
            "result": "yes" if clearly_better else "no",
            "detail": (
                f"{outer_outer.lane}号艇が展示・コース平均ST順位とも同等以上"
                if clearly_better and outer_outer
                else "外の外艇は2項目とも同等以上とは判定できません"
            ),
        }
    )
    if clearly_better and outer_outer:
        likely_lanes = [outer_outer.lane]
    elif outer_outer:
        appeal_reasons = []
        if outer_outer.lane in ap_lanes:
            appeal_reasons.append("AP")
        if outer_outer.lane in win_rate_top_two:
            appeal_reasons.append("全国勝率上位2艇")
        if outer_outer.lane in course_top3_top_two:
            appeal_reasons.append("コース3連率上位2艇")
        steps.append(
            {
                "number": 5,
                "result": "yes" if appeal_reasons else "no",
                "detail": (
                    f"{outer_outer.lane}号艇の追加根拠: {'、'.join(appeal_reasons)}"
                    if appeal_reasons
                    else f"{outer_outer.lane}号艇に追加のアピール根拠はありません"
                ),
            }
        )
        likely_lanes = [outer.lane, outer_outer.lane] if appeal_reasons else [outer.lane]
    else:
        likely_lanes = [outer.lane]

    lane_one = by_lane.get(1)
    if (
        lane_one is None
        or lane_one.exhibition_time is None
        or lane_one.course_avg_start_rank is None
        or any(
            by_lane[lane].exhibition_time is None or by_lane[lane].course_avg_start_rank is None
            for lane in likely_lanes
        )
    ):
        escape_assessment = "uncertain"
    else:
        threatened = any(
            lane_one.exhibition_time - by_lane[lane].exhibition_time >= EXHIBITION_GAP
            and by_lane[lane].course_avg_start_rank < lane_one.course_avg_start_rank
            for lane in likely_lanes
        )
        escape_assessment = "unlikely" if threatened else "likely"

    ticket_keys = _build_tickets(
        compared,
        likely_lanes,
        outer_outer.lane if outer_outer else None,
        escape_assessment,
    )
    ticket_popularity = _popularity_ranks(odds)
    ticket_rows = [
        {
            "combination": ticket,
            "odds": odds.get(ticket) if odds else None,
            "popularity_rank": ticket_popularity.get(ticket),
        }
        for ticket in ticket_keys
    ]
    available_odds = [row["odds"] for row in ticket_rows if row["odds"]]
    composite_odds = (
        Decimal("1") / sum((Decimal("1") / value for value in available_odds), Decimal("0"))
        if ticket_rows and len(available_odds) == len(ticket_rows)
        else None
    )
    return {
        "status": "review",
        "outer_lane": outer.lane,
        "outer_outer_lane": outer_outer.lane if outer_outer else None,
        "likely_lanes": likely_lanes,
        "escape_assessment": escape_assessment,
        "metrics": metrics,
        "steps": steps,
        "tickets": ticket_rows,
        "composite_odds": composite_odds,
        "decision": "review",
        "disclaimer": DISCLAIMER,
    }


def _source_rows(date_from: date, date_to: date) -> list[dict[str, Any]]:
    query = text(
        """
        SELECT b3.kaisai_nen, b3.kaisai_tsukihi, b3.kyoteijo_code,
               b3.race_no, b3.teiban, b3.toroku_bango,
               b3.zenkoku_ritsu_1, c3.tenji_time, c4.isshu,
               h.avg_st, h.avg_start_juni, h.shinnyu_kaisu,
               h.chakukaisu_1, h.chakukaisu_2, h.chakukaisu_3,
               h.snapshot_date AS course_stats_snapshot_date,
               k3.chakujun
        FROM public.brd_b3 b3
        LEFT JOIN public.brd_c3 c3 USING
            (kaisai_nen, kaisai_tsukihi, kyoteijo_code, race_no, teiban)
        LEFT JOIN public.brd_c4 c4 USING
            (kaisai_nen, kaisai_tsukihi, kyoteijo_code, race_no, teiban)
        LEFT JOIN public.brd_k3 k3 USING
            (kaisai_nen, kaisai_tsukihi, kyoteijo_code, race_no, teiban)
        LEFT JOIN LATERAL (
            SELECT avg_st, avg_start_juni, shinnyu_kaisu,
                   chakukaisu_1, chakukaisu_2, chakukaisu_3,
                   snapshot_date
            FROM public.racer_course_stats_history history
            WHERE history.toroku_bango =
                    NULLIF(btrim(b3.toroku_bango), '')::integer
              AND history.course_no = b3.teiban::integer
              AND history.snapshot_date <= make_date(
                    b3.kaisai_nen::integer,
                    substring(lpad(b3.kaisai_tsukihi, 4, '0'), 1, 2)::integer,
                    substring(lpad(b3.kaisai_tsukihi, 4, '0'), 3, 2)::integer
                  )
              AND history.avg_start_juni IS NOT NULL
            ORDER BY history.snapshot_date DESC
            LIMIT 1
        ) h ON true
        WHERE (b3.kaisai_nen || lpad(b3.kaisai_tsukihi, 4, '0'))
              BETWEEN :date_from AND :date_to
        ORDER BY b3.kaisai_nen, b3.kaisai_tsukihi, b3.kyoteijo_code,
                 b3.race_no, b3.teiban
        """
    )
    engine = create_source_engine()
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            rows = [
                dict(row)
                for row in connection.execute(
                    query,
                    {
                        "date_from": date_from.strftime("%Y%m%d"),
                        "date_to": date_to.strftime("%Y%m%d"),
                    },
                ).mappings()
            ]
            connection.rollback()
            return rows
    finally:
        engine.dispose()


def _to_boat(row: dict[str, Any]) -> FlowBoat:
    starts = int(row["shinnyu_kaisu"]) if row.get("shinnyu_kaisu") is not None else None
    finish_counts = [row.get(f"chakukaisu_{position}") for position in range(1, 4)]
    top3 = sum((value or 0) for value in finish_counts)
    finish_raw = str(row.get("chakujun") or "").strip()
    return FlowBoat(
        lane=int(str(row["teiban"]).strip()),
        exhibition_time=_scaled(row.get("tenji_time")),
        lap_time=_scaled(row.get("isshu")),
        course_avg_start_rank=_decimal(row.get("avg_start_juni"), 100),
        course_avg_start_timing=_decimal(row.get("avg_st"), 100),
        nationwide_win_rate=_scaled(row.get("zenkoku_ritsu_1")),
        course_top3_rate=(
            Decimal(top3) / Decimal(starts) * Decimal("100")
            if starts is not None
            and starts >= MIN_COURSE_STARTS
            and any(value is not None for value in finish_counts)
            else None
        ),
        course_starts=starts,
        course_stats_snapshot_date=row.get("course_stats_snapshot_date"),
        finish_position=(
            int(finish_raw) if finish_raw.isdigit() and 1 <= int(finish_raw) <= 6 else None
        ),
    )


def _odds_for_keys(
    date_from: date, date_to: date
) -> dict[str, dict[tuple[int, int, int], Decimal]]:
    engine = create_source_engine()
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            rows = connection.execute(
                text(
                    """
                    SELECT DISTINCT ON
                           (kaisai_nen, kaisai_tsukihi, kyoteijo_code, race_no)
                           kaisai_nen, kaisai_tsukihi, kyoteijo_code, race_no,
                           odds_sanrentan
                    FROM public.odds_view
                    WHERE (kaisai_nen || lpad(kaisai_tsukihi, 4, '0'))
                          BETWEEN :date_from AND :date_to
                    ORDER BY kaisai_nen, kaisai_tsukihi, kyoteijo_code, race_no,
                             CASE
                               WHEN NULLIF(btrim(odds_koshinjikan), '') IS NULL
                               THEN 1 ELSE 0
                             END DESC,
                             NULLIF(btrim(odds_koshinjikan), '') DESC NULLS LAST
                    """
                ),
                {
                    "date_from": date_from.strftime("%Y%m%d"),
                    "date_to": date_to.strftime("%Y%m%d"),
                },
            ).mappings()
            result = {}
            for row in rows:
                key = (
                    f"{row['kaisai_nen']}{str(row['kaisai_tsukihi']).zfill(4)}"
                    f"{str(row['kyoteijo_code']).zfill(2)}"
                    f"{int(str(row['race_no']).strip()):02d}"
                )
                packed = str(row["odds_sanrentan"] or "")
                parsed: dict[tuple[int, int, int], Decimal] = {}
                for index in range(0, len(packed), 9):
                    chunk = packed[index : index + 9]
                    if len(chunk) != 9 or not chunk.isdigit():
                        continue
                    combination = tuple(int(value) for value in chunk[:3])
                    raw_odds = int(chunk[3:])
                    if len(set(combination)) == 3 and raw_odds > 0:
                        parsed[combination] = Decimal(raw_odds) / Decimal("10")
                result[key] = parsed
            connection.rollback()
            return result
    finally:
        engine.dispose()


def _ticket_odds(
    odds_row: dict[tuple[int, int, int], Decimal] | None,
    tickets: list[tuple[int, int, int]],
) -> dict[tuple[int, int, int], Decimal]:
    if not odds_row:
        return {}
    result = {}
    for ticket in tickets:
        value = odds_row.get(ticket)
        if value:
            result[ticket] = value
    return result


def _parse_win_odds(packed: Any) -> dict[int, Decimal]:
    raw = str(packed or "").strip()
    if len(raw) != 42 or not raw.isdigit():
        return {}
    parsed: dict[int, Decimal] = {}
    for lane in range(1, 7):
        chunk = raw[(lane - 1) * 7 : lane * 7]
        if int(chunk[0]) != lane:
            return {}
        odds = Decimal(int(chunk[1:])) / Decimal("10")
        if odds <= 0:
            return {}
        parsed[lane] = odds
    return parsed


def _win_odds_for_keys(date_from: date, date_to: date) -> dict[str, dict[int, Decimal]]:
    engine = create_source_engine()
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            rows = connection.execute(
                text(
                    """
                    SELECT DISTINCT ON
                           (kaisai_nen, kaisai_tsukihi, kyoteijo_code, race_no)
                           kaisai_nen, kaisai_tsukihi, kyoteijo_code, race_no,
                           odds_tansho
                    FROM public.brd_o1
                    WHERE (kaisai_nen || lpad(kaisai_tsukihi, 4, '0'))
                          BETWEEN :date_from AND :date_to
                    ORDER BY kaisai_nen, kaisai_tsukihi, kyoteijo_code, race_no,
                             CASE
                               WHEN NULLIF(btrim(odds_koshinjikan), '') IS NULL
                               THEN 1 ELSE 0
                             END DESC,
                             NULLIF(btrim(odds_koshinjikan), '') DESC NULLS LAST
                    """
                ),
                {
                    "date_from": date_from.strftime("%Y%m%d"),
                    "date_to": date_to.strftime("%Y%m%d"),
                },
            ).mappings()
            result = {}
            for row in rows:
                key = (
                    f"{row['kaisai_nen']}{str(row['kaisai_tsukihi']).zfill(4)}"
                    f"{str(row['kyoteijo_code']).zfill(2)}"
                    f"{int(str(row['race_no']).strip()):02d}"
                )
                parsed = _parse_win_odds(row["odds_tansho"])
                if parsed:
                    result[key] = parsed
            connection.rollback()
            return result
    finally:
        engine.dispose()


def analyze_races_two_boat_flow(
    races: list[Race],
    db: Session,
    *,
    include_source_baseline: bool = False,
) -> dict[UUID, dict[str, Any]]:
    """当日取得した公式値を優先して2艇判定する。

    `include_source_baseline`が真の場合、バックテストと同じ元DBの値だけで判定した
    結果を`source_baseline`として併記する。
    """
    if not races:
        return {}
    race_dates = {race.race_date for race in races}
    if len(race_dates) != 1:
        raise ValueError("batch flow analysis requires one race date")
    target_date = next(iter(race_dates))
    source_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _source_rows(target_date, target_date):
        key = (
            f"{row['kaisai_nen']}{str(row['kaisai_tsukihi']).zfill(4)}"
            f"{str(row['kyoteijo_code']).zfill(2)}"
            f"{int(str(row['race_no']).strip()):02d}"
        )
        source_rows[key].append(row)
    trifecta_odds = _odds_for_keys(target_date, target_date)
    source_win_odds = _win_odds_for_keys(target_date, target_date)

    race_ids = [race.id for race in races]
    official_win_rows = db.execute(
        select(
            RaceEntry.race_id,
            RaceEntry.lane,
            WinOddsObservation.win_odds,
            WinOddsObservation.observed_at,
        )
        .join(
            WinOddsObservation,
            WinOddsObservation.race_entry_id == RaceEntry.id,
        )
        .where(RaceEntry.race_id.in_(race_ids))
        .order_by(
            RaceEntry.race_id,
            RaceEntry.lane,
            WinOddsObservation.observed_at.desc(),
        )
    ).all()
    official_win: dict[UUID, dict[int, Decimal]] = defaultdict(dict)
    official_win_observed_at: dict[UUID, datetime] = {}
    for race_id, lane, odds, observed_at in official_win_rows:
        official_win[race_id].setdefault(lane, odds)
        previous = official_win_observed_at.get(race_id)
        if previous is None or observed_at > previous:
            official_win_observed_at[race_id] = observed_at

    lap_rows = db.execute(
        select(RaceEntry.race_id, RaceEntry.lane, ExhibitionObservation)
        .join(
            ExhibitionObservation,
            ExhibitionObservation.race_entry_id == RaceEntry.id,
        )
        .where(RaceEntry.race_id.in_(race_ids))
        .order_by(
            RaceEntry.race_id,
            RaceEntry.lane,
            ExhibitionObservation.observed_at.desc(),
        )
    ).all()
    official_exhibition_times: dict[UUID, dict[int, Decimal]] = defaultdict(dict)
    boatcast_laps: dict[UUID, dict[int, Decimal]] = defaultdict(dict)
    for race_id, lane, observation in lap_rows:
        if (
            lane not in official_exhibition_times[race_id]
            and observation.source == OFFICIAL_RESULT_SOURCE
            and observation.exhibition_time_seconds is not None
        ):
            official_exhibition_times[race_id][lane] = observation.exhibition_time_seconds
        if lane in boatcast_laps[race_id] or observation.lap_source != "race.boatcast.jp":
            continue
        segment = (
            observation.half_lap_time_seconds
            if observation.half_lap_time_seconds is not None
            else observation.lap_time_seconds
        )
        if segment is not None:
            boatcast_laps[race_id][lane] = segment

    results: dict[UUID, dict[str, Any]] = {}
    for race in races:
        rows = source_rows.get(race.source_id)
        if not rows:
            continue
        boats = source_boats = [_to_boat(row) for row in rows]
        if official_exhibition_times.get(race.id) or boatcast_laps.get(race.id):
            boats = [
                replace(
                    item,
                    exhibition_time=official_exhibition_times[race.id].get(
                        item.lane,
                        item.exhibition_time,
                    ),
                    lap_time=boatcast_laps[race.id].get(item.lane, item.lap_time),
                )
                for item in boats
            ]
        win_odds = official_win.get(race.id, {})
        win_odds_source = OFFICIAL_RESULT_SOURCE if len(win_odds) == 6 else None
        win_odds_observed_at = official_win_observed_at.get(race.id)
        if len(win_odds) != 6:
            win_odds = source_win_odds.get(race.source_id, {})
            win_odds_source = "source_database" if win_odds else None
            win_odds_observed_at = None
        result = evaluate_two_boat_flow(
            boats,
            trifecta_odds.get(race.source_id),
            win_odds,
            venue_code=race.venue_code,
        )
        result["race_id"] = race.id
        result["win_odds_source"] = win_odds_source
        result["win_odds_observed_at"] = win_odds_observed_at
        if include_source_baseline:
            full_odds = trifecta_odds.get(race.source_id)
            result["source_baseline"] = {
                "flow": evaluate_two_boat_flow(source_boats, full_odds, venue_code=race.venue_code),
                "boats": source_boats,
                "trifecta_odds": full_odds or {},
                "winning_combination": result_winning_combination(
                    [(item.lane, item.finish_position) for item in source_boats]
                ),
            }
        results[race.id] = result
    return results


def analyze_race_two_boat_flow(race_id: UUID, db: Session) -> dict[str, Any]:
    race = db.get(Race, race_id)
    if race is None:
        raise LookupError("Race not found")
    result = analyze_races_two_boat_flow([race], db).get(race.id)
    if result is None:
        raise LookupError("Source race data not found")
    return result


def evaluate_two_boat_strategy(date_from: date, date_to: date) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _source_rows(date_from, date_to):
        key = (
            f"{row['kaisai_nen']}{str(row['kaisai_tsukihi']).zfill(4)}"
            f"{str(row['kyoteijo_code']).zfill(2)}"
            f"{int(str(row['race_no']).strip()):02d}"
        )
        grouped[key].append(row)
    odds_rows = _odds_for_keys(date_from, date_to)
    finalized = gap_triggered = insufficient = triggered = likely_wins = likely_top3 = 0
    ticket_hits = ticket_generated = triggered_lane_one_wins = 0
    course_stats_covered = 0
    ticket_counts: list[int] = []
    snapshot_lags: list[int] = []
    odds_covered = 0
    total_stake = Decimal("0")
    total_return = Decimal("0")
    escape_checks = escape_correct = 0
    for key, rows in grouped.items():
        boats = [_to_boat(row) for row in rows]
        ordered = sorted(
            (item for item in boats if item.finish_position is not None),
            key=lambda item: item.finish_position or 99,
        )
        if len(ordered) < 3 or ordered[0].finish_position != 1:
            continue
        finalized += 1
        full_course_stats = len(boats) == 6 and all(
            item.course_avg_start_rank is not None for item in boats
        )
        course_stats_covered += int(full_course_stats)
        race_date = date.fromisoformat(f"{key[:4]}-{key[4:6]}-{key[6:8]}")
        snapshot_lags.extend(
            (race_date - item.course_stats_snapshot_date).days
            for item in boats
            if item.course_stats_snapshot_date is not None
        )
        preliminary = evaluate_two_boat_flow(boats, venue_code=key[8:10])
        gap_triggered += int(preliminary["steps"][0]["result"] == "yes")
        insufficient += int(preliminary["status"] == "insufficient_data")
        if preliminary["status"] != "review":
            continue
        triggered += 1
        winning_combo = tuple(item.lane for item in ordered[:3])
        triggered_lane_one_wins += int(winning_combo[0] == 1)
        likely = set(preliminary["likely_lanes"])
        likely_wins += int(winning_combo[0] in likely)
        likely_top3 += int(bool(likely.intersection(winning_combo)))
        ticket_keys = [tuple(row["combination"]) for row in preliminary["tickets"]]
        if ticket_keys:
            ticket_generated += 1
            ticket_counts.append(len(ticket_keys))
            ticket_hits += int(winning_combo in ticket_keys)
        assessment = preliminary["escape_assessment"]
        if assessment in {"likely", "unlikely"}:
            escape_checks += 1
            escape_correct += int(
                (assessment == "likely" and winning_combo[0] == 1)
                or (assessment == "unlikely" and winning_combo[0] != 1)
            )
        full_odds = odds_rows.get(key)
        odds = _ticket_odds(full_odds, ticket_keys)
        if ticket_keys and len(odds) == len(ticket_keys):
            odds_covered += 1
            total_stake += Decimal("100") * len(ticket_keys)
            if winning_combo in odds:
                total_return += Decimal("100") * odds[winning_combo]
    triggered_divisor = triggered or None
    return {
        "date_from": date_from,
        "date_to": date_to,
        "total_finalized_races": finalized,
        "gap_triggered_races": gap_triggered,
        "insufficient_data_races": insufficient,
        "triggered_races": triggered,
        "trigger_rate": triggered / finalized if finalized else None,
        "likely_boat_win_rate": (likely_wins / triggered_divisor if triggered_divisor else None),
        "likely_boat_top3_rate": (likely_top3 / triggered_divisor if triggered_divisor else None),
        "triggered_lane_1_win_rate": (
            triggered_lane_one_wins / triggered_divisor if triggered_divisor else None
        ),
        "ticket_generated_races": ticket_generated,
        "ticket_hit_rate": ticket_hits / ticket_generated if ticket_generated else None,
        "average_ticket_count": mean(ticket_counts) if ticket_counts else None,
        "escape_assessment_accuracy": (escape_correct / escape_checks if escape_checks else None),
        "escape_assessed_races": escape_checks,
        "course_stats_covered_races": course_stats_covered,
        "course_stats_coverage_rate": (course_stats_covered / finalized if finalized else None),
        "course_stats_history_available_from": COURSE_STATS_HISTORY_AVAILABLE_FROM,
        "course_stats_initial_snapshot_uncertain_through": (
            COURSE_STATS_INITIAL_SNAPSHOT_UNCERTAIN_THROUGH
        ),
        "snapshot_lag_days_min": min(snapshot_lags) if snapshot_lags else None,
        "snapshot_lag_days_median": median(snapshot_lags) if snapshot_lags else None,
        "snapshot_lag_days_max": max(snapshot_lags) if snapshot_lags else None,
        "odds_covered_races": odds_covered,
        "flat_stake_return_rate": (float(total_return / total_stake) if total_stake else None),
        "notes": [
            "展示タイム・一周タイムの艇間比較（0.10秒差、AP、イン評価）は場ごとのスタンダード版補正値を加算した補正後タイムで行います。",
            "APは展示タイムまたは一周タイムの1・2番時計です。",
            "コース平均ST順位はレース日以前で値が収録された最新スナップショットだけを使用し、欠損時は判定対象外とします。",
            "コース別ST履歴は2026-07-07以降だけ収録されているため、それより前は検証できません。",
            "履歴値は大半が期間中固定で、スナップショット日付は値の実質的な更新日を示しません。日差0日でも最新データとは解釈しません。",
            "未来日付の履歴は使用していません。ただし2026-07-07〜07-08は初期スナップショットの作成時点を確認できないため、独立した検証期間として扱いません。",
            f"コース3連率は進入数{MIN_COURSE_STARTS}以上の場合だけ追加根拠に使います。",
            "買い目一致率は候補買い目を生成できたレースだけを分母にしています。",
            "オッズはodds_viewの3連単パックを使い、収録時点の値で均等100円買いを試算します。",
            "Go/Passの最終判断は自動化せず、候補と合成オッズを提示します。",
        ],
    }
