"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { getLabDashboard, refreshLab } from "@/lib/api";
import type { LabDashboard, LabPrediction, LabRefresh } from "@/lib/types";
import { ErrorState, LoadingState } from "./Status";

export function StrategyLabView() {
  const today = new Date();
  const monthAgo = new Date(today);
  monthAgo.setDate(monthAgo.getDate() - 29);
  const initial = {
    dateFrom: formatJstDate(monthAgo),
    dateTo: formatJstDate(today),
  };
  const [filters, setFilters] = useState(initial);
  const [query, setQuery] = useState(initial);
  const [data, setData] = useState<LabDashboard | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshResult, setRefreshResult] = useState<LabRefresh | null>(null);

  const load = useCallback(
    (signal?: AbortSignal) => {
      setError("");
      return getLabDashboard(query, signal)
        .then(setData)
        .catch((reason: unknown) => {
          if (reason instanceof Error && reason.name !== "AbortError") {
            setError(reason.message);
          }
        });
    },
    [query],
  );

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setQuery(filters);
  }

  async function refresh() {
    setRefreshing(true);
    setRefreshResult(null);
    setError("");
    try {
      const result = await refreshLab();
      setRefreshResult(result);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新に失敗しました");
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <section>
      <div className="section-heading">
        <div>
          <p className="eyebrow">LIVE SHADOW STRATEGY LAB</p>
          <h1>買い方LAB</h1>
        </div>
        <p>締切前に固定した仮想買い目を、公式結果で自動採点します。</p>
      </div>

      <div className="lab-callout">
        <strong>本番の買い目・Telegram通知から分離</strong>
        <span>
          実投票は行わず、各方式を1点100円として同じLIVEレースで比較します。
        </span>
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
        <button type="submit">集計する</button>
        <button
          className="secondary"
          type="button"
          disabled={refreshing}
          onClick={() => void refresh()}
        >
          {refreshing ? "LIVE更新中" : "今すぐLIVE更新"}
        </button>
      </form>

      {refreshResult && (
        <p className="lab-refresh-result">
          締切前対象 {refreshResult.eligible_races}件 / LIVE完全{" "}
          {refreshResult.complete_races}件 / 新規予想{" "}
          {refreshResult.predictions_created}件 / 新規採点{" "}
          {refreshResult.settlements_created}件
          {refreshResult.already_running ? "（別の更新処理が実行中です）" : ""}
        </p>
      )}

      {error ? (
        <ErrorState message={error} />
      ) : !data ? (
        <LoadingState label="買い方のLIVE検証結果を集計しています" />
      ) : (
        <>
          {data.summaries.length ? (
            <div className="lab-strategy-grid">
              {data.summaries.map((summary) => (
                <article className="lab-strategy-card" key={summary.strategy_code}>
                  <div>
                    <span className="tag">v{summary.strategy_version}</span>
                    <h2>{summary.strategy_name}</h2>
                    <p>{summary.description}</p>
                  </div>
                  <dl>
                    <Metric
                      label="対象 / 採点済み"
                      value={`${summary.applicable_count} / ${summary.settled_count}`}
                    />
                    <Metric
                      label="的中率"
                      value={formatNullablePercent(summary.hit_rate)}
                    />
                    <Metric
                      label="回収率"
                      value={formatNullablePercent(summary.return_rate)}
                      emphasis={summary.return_rate !== null && summary.return_rate >= 1}
                    />
                    <Metric
                      label="最大払戻除外"
                      value={formatNullablePercent(
                        summary.max_payout_excluded_return_rate,
                      )}
                    />
                    <Metric
                      label="収支"
                      value={formatYen(summary.profit_yen, true)}
                      emphasis={summary.profit_yen > 0}
                    />
                  </dl>
                </article>
              ))}
            </div>
          ) : (
            <div className="status-card">
              <strong>まだLIVE検証データがありません</strong>
              <p>
                締切前に公式展示・周回・人気が揃った次のレースから自動記録します。
              </p>
            </div>
          )}

          <div className="section-heading evaluation-subheading">
            <div>
              <p className="eyebrow">FROZEN PREDICTIONS</p>
              <h2>固定済み予想と採点</h2>
            </div>
            <p>最大100件を新しい順に表示</p>
          </div>
          {data.recent_predictions.length ? (
            <div className="table-wrap">
              <table className="lab-table">
                <thead>
                  <tr>
                    <th>レース</th>
                    <th>方式</th>
                    <th>注目 / 強い脅威</th>
                    <th>仮想買い目</th>
                    <th>結果</th>
                    <th>収支</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_predictions.map((prediction) => (
                    <PredictionRow
                      key={prediction.prediction_id}
                      prediction={prediction}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">固定済み予想はありません。</p>
          )}
          <div className="notes">
            {data.notes.map((note) => (
              <p key={note}>{note}</p>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function PredictionRow({ prediction }: { prediction: LabPrediction }) {
  const tickets = prediction.tickets
    .map((ticket) => ticket.combination.join("-"))
    .join(" / ");
  const result = prediction.settlement;
  return (
    <tr>
      <td>
        <strong>
          {prediction.race_date} {prediction.venue_name} {prediction.race_number}R
        </strong>
        <small>{formatJstTime(prediction.created_at)} 固定</small>
      </td>
      <td>
        {prediction.strategy_name}
        <small>v{prediction.strategy_version}</small>
      </td>
      <td>
        注目: {formatLanes(prediction.likely_lanes)}
        <small>強い脅威: {formatLanes(prediction.strong_threat_lanes)}</small>
      </td>
      <td>
        {prediction.status === "ready" ? (
          <>
            {tickets}
            <small>{prediction.tickets.length}点</small>
          </>
        ) : (
          <>
            見送り
            <small>{prediction.skip_reason}</small>
          </>
        )}
      </td>
      <td>
        {!result ? (
          "未確定"
        ) : result.refunded ? (
          "返還"
        ) : (
          <>
            {result.winning_combination ?? "不成立"}
            <small>{result.hit === null ? "対象外" : result.hit ? "的中" : "不的中"}</small>
          </>
        )}
      </td>
      <td
        className={
          result && result.profit_yen > 0
            ? "lab-profit"
            : result && result.profit_yen < 0
              ? "lab-loss"
              : undefined
        }
      >
        {result ? formatYen(result.profit_yen, true) : "—"}
      </td>
    </tr>
  );
}

function Metric({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className={emphasis ? "positive" : undefined}>{value}</dd>
    </div>
  );
}

function formatNullablePercent(value: number | null): string {
  return value === null
    ? "算出不可"
    : new Intl.NumberFormat("ja-JP", {
        style: "percent",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(value);
}

function formatYen(value: number, sign = false): string {
  const absolute = `${Math.abs(value).toLocaleString("ja-JP")}円`;
  if (!sign || value === 0) return absolute;
  return `${value > 0 ? "+" : "-"}${absolute}`;
}

function formatLanes(lanes: number[]): string {
  return lanes.length ? lanes.map((lane) => `${lane}号艇`).join("・") : "なし";
}

function formatJstDate(value: Date): string {
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(value);
}

function formatJstTime(value: string): string {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
