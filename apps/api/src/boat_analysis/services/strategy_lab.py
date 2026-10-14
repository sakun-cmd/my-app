import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import permutations
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..database import engine
from ..models import (
    LabPrediction,
    LabSettlement,
    LabStrategy,
    LabTicket,
    Race,
    RaceEntry,
    RaceResult,
)
from .official_results import NO_RESULT_MARKERS
from .two_boat_flow import (
    _live_saved_coverage,
    analyze_races_two_boat_flow,
    result_winning_combination,
)

logger = logging.getLogger(__name__)

UNIT_STAKE_YEN = 100
STRONG_THREAT_SCORE = 6
_refresh_lock = Lock()


@dataclass(frozen=True)
class LabRefreshResult:
    eligible_races: int
    complete_races: int
    predictions_created: int
    settlements_created: int
    already_running: bool = False


def _higher_ranks(metrics: dict[int, dict[str, Any]], key: str) -> dict[int, int | None]:
    ordered = sorted(
        {
            Decimal(str(item[key]))
            for item in metrics.values()
            if item.get(key) is not None
        },
        reverse=True,
    )
    return {
        lane: (
            ordered.index(Decimal(str(item[key]))) + 1
            if item.get(key) is not None
            else None
        )
        for lane, item in metrics.items()
    }


def calculate_threats(flow: dict[str, Any]) -> dict[str, Any]:
    metrics = {int(item["lane"]): item for item in flow.get("metrics", [])}
    if set(metrics) != set(range(1, 7)):
        return {"scores": {}, "reasons": {}, "strong_lanes": [], "ordered_lanes": []}
    win_rate_ranks = _higher_ranks(metrics, "nationwide_win_rate")
    course_top3_ranks = _higher_ranks(metrics, "course_top3_rate")
    lane_one = metrics[1]
    scores: dict[int, int] = {}
    reasons: dict[int, dict[str, bool]] = {}
    for lane in range(2, 7):
        item = metrics[lane]
        lane_one_exhibition = lane_one.get("exhibition_time_corrected")
        lane_exhibition = item.get("exhibition_time_corrected")
        exhibition_advantage = (
            Decimal(str(lane_one_exhibition)) - Decimal(str(lane_exhibition))
            if lane_one_exhibition is not None and lane_exhibition is not None
            else None
        )
        signals = {
            "展示2位以内": item.get("exhibition_rank") is not None
            and item["exhibition_rank"] <= 2,
            "周回2位以内": item.get("lap_rank") is not None
            and item["lap_rank"] <= 2,
            "平均ST順位が1号艇より優位": (
                item.get("course_avg_start_rank") is not None
                and lane_one.get("course_avg_start_rank") is not None
                and item["course_avg_start_rank"] < lane_one["course_avg_start_rank"]
            ),
            "全国勝率2位以内": (
                win_rate_ranks.get(lane) is not None
                and win_rate_ranks[lane] <= 2
            ),
            "コース3連率2位以内": (
                course_top3_ranks.get(lane) is not None
                and course_top3_ranks[lane] <= 2
            ),
            "人気3位以内": item.get("popularity_rank") is not None
            and item["popularity_rank"] <= 3,
            "1号艇より展示0.05秒以上優位": (
                exhibition_advantage is not None
                and exhibition_advantage >= Decimal("0.05")
            ),
        }
        reasons[lane] = signals
        scores[lane] = sum(signals.values())
    ordered_lanes = sorted(
        range(2, 7),
        key=lambda lane: (
            -scores[lane],
            metrics[lane].get("popularity_rank") or 99,
            metrics[lane].get("exhibition_rank") or 99,
            lane,
        ),
    )
    return {
        "scores": scores,
        "reasons": reasons,
        "strong_lanes": [
            lane for lane in ordered_lanes if scores[lane] >= STRONG_THREAT_SCORE
        ],
        "ordered_lanes": ordered_lanes,
    }


def _box_tickets(lanes: set[int]) -> list[tuple[int, int, int]]:
    if len(lanes) != 3:
        return []
    return sorted(permutations(sorted(lanes), 3))


def _popularity_formation_tickets(
    flow: dict[str, Any],
    require_lane_one_favorite: bool = False,
    max_lane_one_implied_odds: Decimal | None = None,
) -> tuple[list[tuple[int, int, int]], str | None]:
    """1号艇1着固定で、2・3番人気と4・5番人気を2着・3着に入れ替えたフォーメーション。

    ① 1 - 4・5番人気 - 2・3番人気 / ② 1 - 2・3番人気 - 4・5番人気 の計8点。
    人気順は1号艇を除く5艇の人気順で数える(1号艇が1番人気なら2〜5番人気と一致)。
    6号艇が注目艇に入り、4番人気以内でなければ5番人気を6号艇に差し替える。
    require_lane_one_favorite のときは1号艇が1番人気でないレースを見送る
    (2026-07〜10の検証で、1番人気でないレースの回収率が56〜67%と低かったため)。
    max_lane_one_implied_odds のときは、公式3連単由来の1号艇の1着支持換算値が
    その値未満のレースだけを対象にする(3連単1着支持順位での2026-07-09〜10-10の
    再検証で、1番人気条件72.0%に対し1.5倍未満は77.0%、前後半とも77%前後だったため)。
    """
    popularity = {
        int(item["lane"]): item.get("popularity_rank") for item in flow.get("metrics", [])
    }
    if require_lane_one_favorite and popularity.get(1) is not None and popularity[1] != 1:
        return [], "1号艇が1番人気でないため見送り"
    if max_lane_one_implied_odds is not None:
        lane_one_odds = next(
            (
                item.get("win_odds")
                for item in flow.get("metrics", [])
                if int(item["lane"]) == 1
            ),
            None,
        )
        if flow.get("popularity_source") != "official_trifecta" or lane_one_odds is None:
            return [], "1号艇の1着支持換算値が未取得のため見送り"
        if Decimal(str(lane_one_odds)) >= max_lane_one_implied_odds:
            return [], (
                f"1号艇の1着支持換算値が{max_lane_one_implied_odds}倍以上のため見送り"
            )
    ranked = sorted(
        (lane for lane in range(2, 7) if popularity.get(lane) is not None),
        key=lambda lane: (popularity[lane], lane),
    )
    if len(ranked) < 4:
        return [], "単勝人気が未取得のため見送り"
    upper = ranked[:2]
    lower = ranked[2:4]
    likely = {int(lane) for lane in flow.get("likely_lanes", [])}
    if 6 in likely and 6 not in ranked[:3]:
        lower = [lower[0], 6]
    tickets = {(1, second, third) for second in lower for third in upper}
    tickets |= {(1, second, third) for second in upper for third in lower}
    return sorted(tickets), None


def build_strategy_tickets(
    strategy_code: str,
    flow: dict[str, Any],
    threats: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> tuple[list[tuple[int, int, int]], str | None]:
    config = config or {}
    current = sorted(
        {tuple(int(lane) for lane in item["combination"]) for item in flow.get("tickets", [])}
    )
    likely = {int(lane) for lane in flow.get("likely_lanes", [])}
    strong = set(threats["strong_lanes"])
    ordered = [int(lane) for lane in threats["ordered_lanes"]]
    if strategy_code == "current":
        return current, None if current else "現行買い目なし"
    if strategy_code == "skip_single_likely":
        if len(likely) == 1:
            return [], "注目艇が1艇のため見送り"
        return current, None if current else "現行買い目なし"
    if strategy_code == "recommended_threat_box":
        if not likely.intersection(strong):
            return [], "おすすめ艇と強い脅威艇が一致しないため見送り"
        lanes = {1, *likely}
        for lane in ordered:
            if len(lanes) >= 3:
                break
            lanes.add(lane)
        return _box_tickets(lanes), None
    if strategy_code == "strong_threat_top2_box":
        if not strong:
            return [], "6点以上の強い脅威艇がないため見送り"
        return _box_tickets({1, *ordered[:2]}), None
    if strategy_code in {"popularity_formation", "popularity_formation_single_wide"}:
        if not current:
            return [], "現行買い目なし"
        max_implied = config.get("max_lane_one_implied_odds")
        tickets, skip_reason = _popularity_formation_tickets(
            flow,
            bool(config.get("require_lane_one_favorite")),
            Decimal(str(max_implied)) if max_implied is not None else None,
        )
        if strategy_code == "popularity_formation" or skip_reason or len(likely) != 1:
            return tickets, skip_reason
        # 注目艇1艇のときは 1-注目艇-残り4艇 / 1-残り4艇-注目艇 の全流し8点
        # (2026-07-09〜10-10の検証で、4点買い66.9%に対し8点は75.9%、前後半とも改善したため)
        (lane,) = likely
        others = [other for other in range(2, 7) if other != lane]
        return sorted(
            {(1, lane, other) for other in others} | {(1, other, lane) for other in others}
        ), None
    raise ValueError(f"Unsupported lab strategy: {strategy_code}")


def _load_races(db: Session, target_date: date) -> list[Race]:
    return list(
        db.scalars(
            select(Race)
            .where(Race.race_date == target_date)
            .options(
                selectinload(Race.entries).selectinload(RaceEntry.exhibitions),
                selectinload(Race.entries).selectinload(
                    RaceEntry.win_odds_observations
                ),
                selectinload(Race.result).selectinload(RaceResult.entries),
            )
            .order_by(Race.venue_code, Race.race_number)
        ).all()
    )


def _create_predictions(
    db: Session,
    races: list[Race],
    now: datetime,
) -> tuple[int, int, int]:
    eligible = [
        race
        for race in races
        if race.scheduled_at is not None and now <= race.scheduled_at
    ]
    complete = [race for race in eligible if _live_saved_coverage(race)["complete"]]
    if not complete:
        return len(eligible), 0, 0
    flows = analyze_races_two_boat_flow(complete, db)
    strategies = list(
        db.scalars(
            select(LabStrategy)
            .where(LabStrategy.active.is_(True))
            .order_by(LabStrategy.id)
        ).all()
    )
    existing = set(
        db.execute(
            select(LabPrediction.race_id, LabPrediction.strategy_id).where(
                LabPrediction.race_id.in_([race.id for race in complete])
            )
        ).all()
    )
    created = 0
    for race in complete:
        flow = flows.get(race.id)
        if flow is None:
            continue
        threats = calculate_threats(flow)
        snapshot = jsonable_encoder(
            {
                "flow": flow,
                "threats": threats,
                "captured_at": now,
                "latest_allowed_observation_at": race.scheduled_at,
            }
        )
        for strategy in strategies:
            if (race.id, strategy.id) in existing:
                continue
            tickets, skip_reason = build_strategy_tickets(
                strategy.code,
                flow,
                threats,
                strategy.config,
            )
            prediction = LabPrediction(
                race_id=race.id,
                strategy_id=strategy.id,
                data_cutoff_at=race.scheduled_at,
                status="ready" if tickets else "skipped",
                skip_reason=skip_reason,
                input_snapshot=snapshot,
            )
            prediction.tickets = [
                LabTicket(
                    first_lane=ticket[0],
                    second_lane=ticket[1],
                    third_lane=ticket[2],
                    stake_yen=UNIT_STAKE_YEN,
                )
                for ticket in tickets
            ]
            db.add(prediction)
            created += 1
    return len(eligible), len(complete), created


def _settle_predictions(db: Session) -> int:
    predictions = list(
        db.scalars(
            select(LabPrediction)
            .where(~LabPrediction.settlement.has())
            .options(
                selectinload(LabPrediction.tickets),
                selectinload(LabPrediction.settlement),
                selectinload(LabPrediction.race)
                .selectinload(Race.result)
                .selectinload(RaceResult.entries),
            )
        ).all()
    )
    created = 0
    for prediction in predictions:
        result = prediction.race.result
        if (
            prediction.settlement is not None
            or result is None
            or result.finalized_at is None
        ):
            continue
        refunded = (
            result.trifecta_refunded or result.winning_technique in NO_RESULT_MARKERS
        )
        winning = result_winning_combination(
            [(entry.lane, entry.finish_position) for entry in result.entries]
        )
        tickets = {
            (ticket.first_lane, ticket.second_lane, ticket.third_lane)
            for ticket in prediction.tickets
        }
        stake = sum(ticket.stake_yen for ticket in prediction.tickets)
        hit = None if refunded or not tickets or winning is None else winning in tickets
        returned = (
            stake
            if refunded
            else (result.trifecta_payout_yen or 0) if hit else 0
        )
        prediction.settlement = LabSettlement(
            result_finalized_at=result.finalized_at,
            winning_combination="-".join(map(str, winning)) if winning else None,
            trifecta_payout_yen=result.trifecta_payout_yen,
            refunded=refunded,
            hit=hit,
            stake_yen=stake,
            returned_yen=returned,
            profit_yen=returned - stake,
        )
        created += 1
    return created


def refresh_strategy_lab(target_date: date | None = None) -> LabRefreshResult:
    if not _refresh_lock.acquire(blocking=False):
        return LabRefreshResult(0, 0, 0, 0, already_running=True)
    try:
        settings = get_settings()
        now = datetime.now(ZoneInfo(settings.app_timezone))
        target = target_date or now.date()
        with Session(engine) as db:
            races = _load_races(db, target)
            eligible, complete, predictions = _create_predictions(db, races, now)
            db.flush()
            settlements = _settle_predictions(db)
            db.commit()
        return LabRefreshResult(
            eligible_races=eligible,
            complete_races=complete,
            predictions_created=predictions,
            settlements_created=settlements,
        )
    finally:
        _refresh_lock.release()


def lab_dashboard(
    db: Session,
    date_from: date,
    date_to: date,
    recent_limit: int = 100,
) -> dict[str, Any]:
    predictions = list(
        db.scalars(
            select(LabPrediction)
            .join(LabPrediction.race)
            .where(Race.race_date >= date_from, Race.race_date <= date_to)
            .options(
                selectinload(LabPrediction.tickets),
                selectinload(LabPrediction.settlement),
                selectinload(LabPrediction.strategy),
                selectinload(LabPrediction.race).selectinload(Race.venue),
            )
            .order_by(
                Race.race_date.desc(),
                Race.scheduled_at.desc(),
                LabPrediction.strategy_id,
            )
        ).all()
    )
    strategies = list(
        db.scalars(
            select(LabStrategy)
            .where(LabStrategy.active.is_(True))
            .order_by(LabStrategy.id)
        ).all()
    )
    grouped: dict[int, list[LabPrediction]] = defaultdict(list)
    for prediction in predictions:
        grouped[prediction.strategy_id].append(prediction)
    summaries = []
    for strategy in strategies:
        rows = grouped[strategy.id]
        applicable = [row for row in rows if row.status == "ready"]
        settled = [
            row
            for row in applicable
            if row.settlement is not None and not row.settlement.refunded
        ]
        stake = sum(row.settlement.stake_yen for row in settled)
        returned = sum(row.settlement.returned_yen for row in settled)
        hits = sum(row.settlement.hit is True for row in settled)
        winning_rows = [
            row for row in settled if row.settlement.returned_yen > 0
        ]
        max_row = max(
            winning_rows,
            key=lambda row: row.settlement.returned_yen,
            default=None,
        )
        stake_without_max = (
            stake - max_row.settlement.stake_yen if max_row else stake
        )
        return_without_max = (
            returned - max_row.settlement.returned_yen if max_row else returned
        )
        summaries.append(
            {
                "strategy_code": strategy.code,
                "strategy_version": strategy.version,
                "strategy_name": strategy.name,
                "description": strategy.description,
                "prediction_count": len(rows),
                "applicable_count": len(applicable),
                "settled_count": len(settled),
                "hit_count": hits,
                "hit_rate": hits / len(settled) if settled else None,
                "total_stake_yen": stake,
                "total_returned_yen": returned,
                "profit_yen": returned - stake,
                "return_rate": returned / stake if stake else None,
                "max_payout_excluded_return_rate": (
                    return_without_max / stake_without_max
                    if stake_without_max
                    else None
                ),
            }
        )
    recent = []
    for prediction in predictions[:recent_limit]:
        threats = prediction.input_snapshot.get("threats", {})
        settlement = prediction.settlement
        recent.append(
            {
                "prediction_id": prediction.id,
                "race_id": prediction.race_id,
                "race_date": prediction.race.race_date,
                "venue_code": prediction.race.venue_code,
                "venue_name": prediction.race.venue.name,
                "race_number": prediction.race.race_number,
                "scheduled_at": prediction.race.scheduled_at,
                "strategy_code": prediction.strategy.code,
                "strategy_version": prediction.strategy.version,
                "strategy_name": prediction.strategy.name,
                "status": prediction.status,
                "skip_reason": prediction.skip_reason,
                "likely_lanes": prediction.input_snapshot.get("flow", {}).get(
                    "likely_lanes", []
                ),
                "strong_threat_lanes": threats.get("strong_lanes", []),
                "threat_scores": threats.get("scores", {}),
                "tickets": [
                    {
                        "combination": (
                            ticket.first_lane,
                            ticket.second_lane,
                            ticket.third_lane,
                        ),
                        "stake_yen": ticket.stake_yen,
                    }
                    for ticket in prediction.tickets
                ],
                "created_at": prediction.created_at,
                "settlement": (
                    {
                        "winning_combination": settlement.winning_combination,
                        "refunded": settlement.refunded,
                        "hit": settlement.hit,
                        "stake_yen": settlement.stake_yen,
                        "returned_yen": settlement.returned_yen,
                        "profit_yen": settlement.profit_yen,
                        "settled_at": settlement.settled_at,
                    }
                    if settlement
                    else None
                ),
            }
        )
    return {
        "date_from": date_from,
        "date_to": date_to,
        "calculated_at": datetime.now(UTC),
        "summaries": summaries,
        "recent_predictions": recent,
        "notes": [
            "発走予定時刻以前に公式LIVE入力が6艇分揃った時点の判定を固定保存します。",
            "結果確定後に各買い目100円として自動採点します。実際の投票は行いません。",
            "回収率は小標本や高配当1件に左右されるため、最大払戻除外後も併記します。",
            "的中や利益を保証するものではなく、本番採用前の統計的な比較用途です。",
        ],
    }
