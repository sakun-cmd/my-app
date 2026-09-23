from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ..schemas import AnalysisItem, Contribution
from .standard_correction import get_correction

DEFAULT_PROFILE_VERSION = "exhibition-v2"
DISCLAIMER = (
    "本表示は過去データと展示情報に基づく統計的な参考情報です。"
    "レース結果や利益を保証するものではありません。"
)

HALF_LAP_VENUES = frozenset({"01"})
NO_LAP_EXHIBITION_VENUES = frozenset({"03"})
NO_STRAIGHT_TIME_VENUES = frozenset({"12", "13", "18"})


def expected_lap_fields(venue_code: str | None) -> tuple[str, ...]:
    if not venue_code or venue_code in NO_LAP_EXHIBITION_VENUES:
        return ()
    segment = "half_lap_time_seconds" if venue_code in HALF_LAP_VENUES else "lap_time_seconds"
    fields = [segment, "cornering_time_seconds"]
    if venue_code not in NO_STRAIGHT_TIME_VENUES:
        fields.append("straight_time_seconds")
    return tuple(fields)


LAP_FIELD_METRIC = {
    "half_lap_time_seconds": "lap",
    "lap_time_seconds": "lap",
    "cornering_time_seconds": "cornering",
    "straight_time_seconds": "straight",
}


def _corrected(
    value: Decimal | None, venue_code: str | None, lane: int, metric: str
) -> Decimal | None:
    """スタンダード版補正値を加算した比較用タイムを返す(生値は変更しない)。"""
    if value is None:
        return None
    correction = get_correction(venue_code, lane, metric)
    return value + correction if correction else value


def _correction_note(venue_code: str | None, lane: int, metric: str) -> str:
    correction = get_correction(venue_code, lane, metric)
    if not correction:
        return ""
    return f" スタンダード版補正({correction:+.2f}秒)を適用した上で比較。"


@dataclass(frozen=True)
class ScoringInput:
    lane: int
    exhibition_time_seconds: Decimal | None
    exhibition_start_timing: Decimal | None
    exhibition_course: int | None
    half_lap_time_seconds: Decimal | None = None
    lap_time_seconds: Decimal | None = None
    cornering_time_seconds: Decimal | None = None
    straight_time_seconds: Decimal | None = None
    average_start_timing: Decimal | None = None


def _relative_points(
    value: Decimal | None,
    available: list[Decimal],
    maximum: Decimal,
    lower_is_better: bool = True,
) -> Decimal:
    if value is None or not available:
        return Decimal("0")
    if len(set(available)) == 1:
        return maximum
    low, high = min(available), max(available)
    ratio = (high - value) / (high - low) if lower_is_better else (value - low) / (high - low)
    return max(Decimal("0"), min(maximum, ratio * maximum))


START_DEVIATION_THRESHOLD = Decimal("0.10")
# 展示は進入争いがなく、選手は平均STより踏み込んで走る傾向がある。
# 実データ(2026/9/1-9/12, 10,248件)では平均-0.083秒・中央値-0.090秒
# タイトに出ており、補正しないと乖離判定が全艇でほぼ常に発動してしまう。
EXHIBITION_START_TIMING_BIAS = Decimal("-0.08")
# 閾値は元々±0.06だったが、直近30日・4,356レースでの検証
# (evaluate()によるtop1/top2/top3的中率比較)で、±0.06では展示ST保有艇の
# 57%が減点対象になっており、閾値を±0.10に緩めても的中率・平均着順は
# 誤差の範囲内で変化しないことを確認した上で±0.10に変更。


def _start_metric(item: ScoringInput) -> tuple[Decimal | None, bool]:
    """展示STの評価値(基準との乖離の絶対値)と減点対象かどうかを返す。

    選手の平均STが取得できる場合は、展示が平均STよりタイトに出る傾向
    (EXHIBITION_START_TIMING_BIAS)を補正した上で乖離を求め、補正後の乖離が
    +0.10以上または-0.10以下で減点する。平均STが取得できない場合は0.00を
    基準とし、負値のみ減点する(平均STが未取得の選手・レースへのフォールバック)。
    """
    if item.exhibition_start_timing is None:
        return None, False
    if item.average_start_timing is not None:
        deviation = (
            item.exhibition_start_timing - item.average_start_timing - EXHIBITION_START_TIMING_BIAS
        )
        penalized = (
            deviation >= START_DEVIATION_THRESHOLD or deviation <= -START_DEVIATION_THRESHOLD
        )
        return abs(deviation), penalized
    return abs(item.exhibition_start_timing), item.exhibition_start_timing < 0


def _inferred_lap_fields(entries: list[ScoringInput]) -> tuple[str, ...]:
    fields = []
    if any(item.half_lap_time_seconds is not None for item in entries):
        fields.append("half_lap_time_seconds")
    elif any(item.lap_time_seconds is not None for item in entries):
        fields.append("lap_time_seconds")
    for name in ("cornering_time_seconds", "straight_time_seconds"):
        if any(getattr(item, name) is not None for item in entries):
            fields.append(name)
    return tuple(fields)


def score_entries(entries: list[ScoringInput], venue_code: str | None = None) -> list[AnalysisItem]:
    lap_fields = (
        expected_lap_fields(venue_code) if venue_code is not None else _inferred_lap_fields(entries)
    )
    field_details = {
        "half_lap_time_seconds": ("half_lap", "半周タイム", Decimal("15")),
        "lap_time_seconds": ("lap", "一周タイム", Decimal("15")),
        "cornering_time_seconds": ("cornering", "回り足タイム", Decimal("15")),
        "straight_time_seconds": ("straight", "直線タイム", Decimal("10")),
    }
    times = [
        value
        for value in (
            _corrected(item.exhibition_time_seconds, venue_code, item.lane, "exhibition")
            for item in entries
        )
        if value
    ]
    start_metrics = [_start_metric(item) for item in entries]
    starts = [value for value, _ in start_metrics if value is not None]
    lap_values = {
        name: [
            value
            for value in (
                _corrected(getattr(item, name), venue_code, item.lane, LAP_FIELD_METRIC[name])
                for item in entries
            )
            if value is not None
        ]
        for name in lap_fields
    }
    active_lap_fields = {name for name, values in lap_values.items() if len(set(values)) >= 2}
    available_maximum = Decimal("60") + sum(
        (field_details[name][2] for name in lap_fields if name in active_lap_fields),
        Decimal("0"),
    )
    normalization = Decimal("100") / available_maximum
    neutral_lap_points = {
        name: (
            sum(
                (
                    _relative_points(value, lap_values[name], field_details[name][2])
                    for value in lap_values[name]
                ),
                Decimal("0"),
            )
            / Decimal(len(lap_values[name]))
        )
        for name in active_lap_fields
    }
    scored: list[tuple[ScoringInput, Decimal, list[Contribution], list[str], str]] = []

    for item, (start_value, start_penalized) in zip(entries, start_metrics, strict=True):
        warnings: list[str] = []
        contributions: list[Contribution] = []
        exhibition_corrected = _corrected(
            item.exhibition_time_seconds, venue_code, item.lane, "exhibition"
        )
        time_points = _relative_points(exhibition_corrected, times, Decimal("30"))
        contributions.append(
            Contribution(
                key="exhibition_time",
                label="展示タイム",
                raw_value=item.exhibition_time_seconds,
                points=time_points,
                explanation="同一レース内で速いほど高評価"
                + _correction_note(venue_code, item.lane, "exhibition"),
            )
        )
        start_points = _relative_points(start_value, starts, Decimal("20"))
        if start_penalized:
            start_points *= Decimal("0.5")
            warnings.append(
                "展示STが選手平均STから0.10秒以上乖離しているため、スタート評価を減点しています"
                if item.average_start_timing is not None
                else "展示STが負値のため、スタート評価を減点しています"
            )
        contributions.append(
            Contribution(
                key="exhibition_start",
                label="展示ST",
                raw_value=item.exhibition_start_timing,
                points=start_points,
                explanation="選手の平均ST(傾向差補正後)に近い展示STを評価し、"
                "＋0.10以上及び-0.10以下は減点",
            )
        )
        course_points = (
            Decimal("10")
            if item.exhibition_course == item.lane
            else Decimal("5")
            if item.exhibition_course is not None
            else Decimal("0")
        )
        contributions.append(
            Contribution(
                key="course_stability",
                label="進入安定性",
                raw_value=(
                    Decimal(item.exhibition_course) if item.exhibition_course is not None else None
                ),
                points=course_points,
                explanation="展示進入が枠番どおりなら高評価",
            )
        )
        for name in lap_fields:
            key, label, maximum = field_details[name]
            value = getattr(item, name)
            metric = LAP_FIELD_METRIC[name]
            if name not in active_lap_fields:
                points = Decimal("0")
                explanation = "比較可能な値が不足または同値のため配点対象外"
            elif value is None:
                points = neutral_lap_points[name]
                explanation = "欠損のため観測済み艇の平均点を使用"
            else:
                corrected_value = _corrected(value, venue_code, item.lane, metric)
                points = _relative_points(corrected_value, lap_values[name], maximum)
                explanation = "同一レース内で短いほど高評価" + _correction_note(
                    venue_code, item.lane, metric
                )
            contributions.append(
                Contribution(
                    key=key,
                    label=label,
                    raw_value=value,
                    points=points,
                    explanation=explanation,
                )
            )

        expected_values = [
            ("展示タイム", item.exhibition_time_seconds),
            ("展示ST", item.exhibition_start_timing),
            ("展示進入", item.exhibition_course),
            *[(field_details[name][1], getattr(item, name)) for name in lap_fields],
        ]
        missing = [label for label, value in expected_values if value is None]
        if missing:
            warnings.append(f"展示データ不足: {'、'.join(missing)}")
        if lap_fields and all(getattr(item, name) is None for name in lap_fields):
            warnings.append("周回展示データが未到着です")
        coverage = Decimal(len(expected_values) - len(missing)) / Decimal(len(expected_values))
        confidence = "高" if coverage == 1 else "中" if coverage >= Decimal("0.67") else "低"

        normalized = [
            contribution.model_copy(update={"points": contribution.points * normalization})
            for contribution in contributions
        ]
        total = sum((part.points for part in normalized), Decimal("0"))
        scored.append((item, total, normalized, warnings, confidence))

    scored.sort(key=lambda row: (-row[1], row[0].lane))
    return [
        AnalysisItem(
            lane=item.lane,
            rank=index,
            score=total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            confidence=confidence,
            contributions=[
                contribution.model_copy(
                    update={
                        "points": contribution.points.quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                    }
                )
                for contribution in contributions
            ],
            warnings=warnings,
        )
        for index, (item, total, contributions, warnings, confidence) in enumerate(scored, start=1)
    ]
