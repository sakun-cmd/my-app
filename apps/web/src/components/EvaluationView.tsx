"use client";

import { FormEvent, useEffect, useState } from "react";

import { getEvaluation, getTwoBoatEvaluation } from "@/lib/api";
import { formatPercent } from "@/lib/format";
import type { EvaluationSummary, TwoBoatEvaluation } from "@/lib/types";
import { ErrorState, LoadingState } from "./Status";

export function EvaluationView() {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const monthAgo = new Date(yesterday);
  monthAgo.setDate(monthAgo.getDate() - 29);
  const [filters, setFilters] = useState({
    dateFrom: formatJstDate(monthAgo),
    dateTo: formatJstDate(yesterday),
  });
  const [query, setQuery] = useState(filters);
  const [data, setData] = useState<EvaluationSummary | null>(null);
  const [flowData, setFlowData] = useState<TwoBoatEvaluation | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    Promise.all([
      getEvaluation(query, controller.signal),
      getTwoBoatEvaluation(query, controller.signal),
    ])
      .then(([evaluation, flowEvaluation]) => {
        setData(evaluation);
        setFlowData(flowEvaluation);
      })
      .catch((reason: unknown) => {
        if (reason instanceof Error && reason.name !== "AbortError") {
          setError(reason.message);
        }
      });
    return () => controller.abort();
  }, [query]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setData(null);
    setFlowData(null);
    setQuery(filters);
  }

  return (
    <section>
      <div className="section-heading">
        <div>
          <p className="eyebrow">WALK-FORWARD EVALUATION</p>
          <h1>過去データで評価</h1>
        </div>
        <p>発走前の展示データだけを使用し、確定着順と比較します。</p>
      </div>
      <form className="filters" onSubmit={submit}>
        <label>
          開始日
          <input
            type="date"
            value={filters.dateFrom}
            onChange={(event) =>
              setFilters((current) => ({ ...current, dateFrom: event.target.value }))
            }
          />
        </label>
        <label>
          終了日
          <input
            type="date"
            value={filters.dateTo}
            onChange={(event) =>
              setFilters((current) => ({ ...current, dateTo: event.target.value }))
            }
          />
        </label>
        <button type="submit">評価する</button>
      </form>

      {error ? (
        <ErrorState message={error} />
      ) : !data ? (
        <LoadingState label="時系列評価を集計しています" />
      ) : (
        <>
          <div className="metric-grid">
            <Metric label="評価レース数" value={data.metrics.race_count.toLocaleString("ja-JP")} />
            <Metric label="1位一致率" value={formatPercent(data.metrics.top_1_accuracy)} />
            <Metric label="上位2艇包含率" value={formatPercent(data.metrics.top_2_coverage)} />
            <Metric label="上位3艇包含率" value={formatPercent(data.metrics.top_3_coverage)} />
            <Metric
              label="1着艇の平均参考順位"
              value={data.metrics.average_winner_rank.toFixed(2)}
            />
            <Metric
              label="1号艇固定の一致率"
              value={formatPercent(data.metrics.lane_1_baseline_accuracy)}
            />
          </div>
          <div className="evaluation-comparison">
            <h2>基準との比較</h2>
            <div>
              <span>説明可能スコア</span>
              <div className="comparison-bar">
                <span style={{ width: formatPercent(data.metrics.top_1_accuracy) }} />
              </div>
              <strong>{formatPercent(data.metrics.top_1_accuracy)}</strong>
            </div>
            <div>
              <span>1号艇固定</span>
              <div className="comparison-bar baseline">
                <span
                  style={{ width: formatPercent(data.metrics.lane_1_baseline_accuracy) }}
                />
              </div>
              <strong>{formatPercent(data.metrics.lane_1_baseline_accuracy)}</strong>
            </div>
          </div>
          <div className="notes">
            {data.notes.map((note) => (
              <p key={note}>{note}</p>
            ))}
          </div>
          {flowData && (
            <>
              <div className="section-heading evaluation-subheading">
                <div>
                  <p className="eyebrow">TWO-BOAT FLOW VALIDATION</p>
                  <h2>2艇判定フローの検証</h2>
                </div>
                <p>AP＝展示または一周の1・2番時計</p>
              </div>
              <div className="metric-grid">
                <Metric
                  label={`判定対象率 (n=${flowData.triggered_races.toLocaleString("ja-JP")})`}
                  value={formatNullablePercent(flowData.trigger_rate)}
                />
                <Metric
                  label={`注目艇1着率 (n=${flowData.triggered_races.toLocaleString("ja-JP")})`}
                  value={formatNullablePercent(flowData.likely_boat_win_rate)}
                />
                <Metric
                  label={`注目艇3着内率 (n=${flowData.triggered_races.toLocaleString("ja-JP")})`}
                  value={formatNullablePercent(flowData.likely_boat_top3_rate)}
                />
                <Metric
                  label={`買い目一致率 (n=${flowData.ticket_generated_races.toLocaleString("ja-JP")})`}
                  value={formatNullablePercent(flowData.ticket_hit_rate)}
                />
                <Metric
                  label="平均買い目"
                  value={
                    flowData.average_ticket_count === null
                      ? "算出不可"
                      : `${flowData.average_ticket_count.toFixed(2)}点`
                  }
                />
                <Metric
                  label="均等買い回収率"
                  value={
                    flowData.flat_stake_return_rate === null
                      ? "算出不可"
                      : formatPercent(flowData.flat_stake_return_rate)
                  }
                />
                <Metric
                  label={`イン判定正解率 (n=${flowData.escape_assessed_races.toLocaleString("ja-JP")})`}
                  value={formatNullablePercent(flowData.escape_assessment_accuracy)}
                />
                <Metric
                  label="対象内の1号艇1着率"
                  value={formatNullablePercent(flowData.triggered_lane_1_win_rate)}
                />
                <Metric
                  label={`ST履歴充足 (n=${flowData.course_stats_covered_races.toLocaleString("ja-JP")})`}
                  value={formatNullablePercent(flowData.course_stats_coverage_rate)}
                />
              </div>
              <div className="notes">
                <p>
                  確定{flowData.total_finalized_races.toLocaleString("ja-JP")}レース中、
                  展示差条件は{flowData.gap_triggered_races.toLocaleString("ja-JP")}件、
                  ST履歴不足による判定除外は
                  {flowData.insufficient_data_races.toLocaleString("ja-JP")}件、
                  オッズ完全収録は{flowData.odds_covered_races.toLocaleString("ja-JP")}件です。
                </p>
                <p>
                  ST履歴のスナップショット日付とレース日との差は
                  {flowData.snapshot_lag_days_median === null
                    ? "算出不可"
                    : `中央値${flowData.snapshot_lag_days_median}日（最小${flowData.snapshot_lag_days_min}日・最大${flowData.snapshot_lag_days_max}日）`}
                  です。この日差は値の更新鮮度を示しません。
                </p>
                <p>
                  ST履歴の収録開始は{flowData.course_stats_history_available_from}です。
                  {flowData.course_stats_initial_snapshot_uncertain_through}
                  までの初期スナップショットは作成時点を確認できないため、
                  独立した検証期間として扱いません。
                </p>
                {flowData.notes.map((note) => (
                  <p key={note}>{note}</p>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function formatNullablePercent(value: number | null): string {
  return value === null ? "算出不可" : formatPercent(value);
}

function formatJstDate(value: Date): string {
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(value);
}
