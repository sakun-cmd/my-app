"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { getRace, getRaceAnalysis, getTwoBoatFlow } from "@/lib/api";
import type { RaceAnalysis, RaceDetail, TwoBoatFlow } from "@/lib/types";
import { ErrorState, LoadingState } from "./Status";

const laneNames = ["白", "黒", "赤", "青", "黄", "緑"];

function format(value: string | null, suffix = "") {
  return value === null ? "—" : `${value}${suffix}`;
}

export function RaceAnalysisView({ raceId }: { raceId: string }) {
  const [race, setRace] = useState<RaceDetail | null>(null);
  const [analysis, setAnalysis] = useState<RaceAnalysis | null>(null);
  const [flow, setFlow] = useState<TwoBoatFlow | null>(null);
  const [flowError, setFlowError] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getRace(raceId, controller.signal),
      getRaceAnalysis(raceId, controller.signal),
    ])
      .then(([raceResponse, analysisResponse]) => {
        setRace(raceResponse);
        setAnalysis(analysisResponse);
      })
      .catch((reason: unknown) => {
        if (reason instanceof Error && reason.name !== "AbortError") {
          setError(reason.message);
        }
      });
    getTwoBoatFlow(raceId, controller.signal)
      .then(setFlow)
      .catch((reason: unknown) => {
        if (reason instanceof Error && reason.name !== "AbortError") {
          setFlowError(reason.message);
        }
      });
    return () => controller.abort();
  }, [raceId]);

  const analysisByLane = useMemo(
    () => new Map(analysis?.items.map((item) => [item.lane, item])),
    [analysis],
  );
  const resultByLane = useMemo(
    () => new Map(race?.result?.entries.map((item) => [item.lane, item])),
    [race],
  );
  const flowByLane = useMemo(
    () => new Map(flow?.metrics.map((item) => [item.lane, item])),
    [flow],
  );

  if (error) return <ErrorState message={error} />;
  if (!race || !analysis) return <LoadingState label="分析結果を計算しています" />;

  return (
    <>
      <Link href="/" className="back-link">
        ← レース一覧
      </Link>
      <section className="race-hero">
        <div>
          <p className="eyebrow">
            {race.race_date} · {race.grade ?? "一般"}
          </p>
          <h1>
            {race.venue.name} <span>{race.race_number}R</span>
          </h1>
          <p className="muted">
            {race.distance_m ? `${race.distance_m}m` : "距離未登録"} · スコア版{" "}
            {analysis.profile_version}
          </p>
          {race.weather && (
            <p className="weather-line">
              {race.weather.weather ?? "天候不明"} · 風{" "}
              {race.weather.wind_direction ?? "向き不明"}{" "}
              {format(race.weather.wind_speed_mps, "m/s")} · 波{" "}
              {race.weather.wave_height_cm === null
                ? "—"
                : `${race.weather.wave_height_cm}cm`}
              {" · "}気温 {format(race.weather.air_temperature_c, "℃")} / 水温{" "}
              {format(race.weather.water_temperature_c, "℃")}
            </p>
          )}
        </div>
        <div className="data-badge">
          <span>展示データ充足度</span>
          <strong>{race.data_completeness}%</strong>
        </div>
      </section>

      <div className="disclaimer">{analysis.disclaimer}</div>

      <section>
        <div className="section-heading">
          <div>
            <p className="eyebrow">TWO-BOAT FLOW</p>
            <h2>2艇判定フロー</h2>
          </div>
          <p>AP＝展示または一周の1・2番時計</p>
        </div>
        {flowError ? (
          <ErrorState message={flowError} />
        ) : !flow ? (
          <LoadingState label="2艇判定を計算しています" />
        ) : (
          <TwoBoatFlowPanel flow={flow} />
        )}
      </section>

      <section>
        <div className="section-heading">
          <div>
            <p className="eyebrow">EXPLAINABLE RANKING</p>
            <h2>参考順位</h2>
          </div>
          <p>同一レース内の相対評価です。スコアは勝率ではありません。</p>
        </div>
        <div className="ranking-grid">
          {analysis.items.map((item) => {
            const entry = race.entries.find((candidate) => candidate.lane === item.lane);
            const result = resultByLane.get(item.lane);
            return (
              <article className={`ranking-card lane-${item.lane}`} key={item.lane}>
                <div className="rank">参考 {item.rank}位</div>
                <div className="lane-chip">
                  <span>{item.lane}</span>
                  {laneNames[item.lane - 1]}
                </div>
                <h3>{entry?.racer_name ?? "選手名未登録"}</h3>
                <div className="score">
                  {item.score}
                  <small>/ 100</small>
                </div>
                <div className="score-bar">
                  <span style={{ width: `${item.score}%` }} />
                </div>
                <span className={`confidence confidence-${item.confidence}`}>
                  信頼度 {item.confidence}
                </span>
                {result && (
                  <span className="actual-finish">
                    実着 {result.finish_position ?? result.status ?? "—"}
                  </span>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section>
        <div className="section-heading">
          <div>
            <p className="eyebrow">EXHIBITION COMPARISON</p>
            <h2>6艇比較</h2>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>艇</th>
                <th>単勝人気</th>
                <th>選手</th>
                <th>展示進入</th>
                <th>展示ST</th>
                <th>展示タイム</th>
                <th>チルト</th>
                <th>周回</th>
                <th>回り足</th>
                <th>直線</th>
                <th>モーター</th>
                <th>部品交換</th>
                <th>参考順位</th>
                <th>実着順</th>
              </tr>
            </thead>
            <tbody>
              {race.entries.map((entry) => {
                const score = analysisByLane.get(entry.lane);
                const result = resultByLane.get(entry.lane);
                const flowMetric = flowByLane.get(entry.lane);
                return (
                  <tr key={entry.lane}>
                    <td>
                      <span className={`lane-number lane-${entry.lane}`}>
                        {entry.lane}
                      </span>
                    </td>
                    <td>
                      {flowMetric?.popularity_rank ? (
                        <>
                          <strong className="popularity-rank">
                            {flowMetric.popularity_rank}番人気
                          </strong>
                          <small>
                            単勝{" "}
                            {flowMetric.win_odds
                              ? `${Number(flowMetric.win_odds).toFixed(1)}倍`
                              : "—"}
                          </small>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <strong>{entry.racer_name ?? "—"}</strong>
                      <small>
                        {entry.racer_registration_number ?? "登録番号なし"} ·{" "}
                        {entry.class_name ?? "級別なし"}
                      </small>
                    </td>
                    <td>{entry.exhibition?.exhibition_course ?? "—"}</td>
                    <td>{format(entry.exhibition?.exhibition_start_timing ?? null)}</td>
                    <td>
                      {format(entry.exhibition?.exhibition_time_seconds ?? null, "秒")}
                      {entry.exhibition?.source === "boatrace.jp" && (
                        <small>公式</small>
                      )}
                    </td>
                    <td>{format(entry.exhibition?.tilt ?? null, "°")}</td>
                    <td>
                      {entry.exhibition?.half_lap_time_seconds !== null &&
                      entry.exhibition?.half_lap_time_seconds !== undefined
                        ? `半周 ${format(entry.exhibition.half_lap_time_seconds, "秒")}`
                        : entry.exhibition?.lap_time_seconds !== null &&
                            entry.exhibition?.lap_time_seconds !== undefined
                          ? `1周 ${format(entry.exhibition.lap_time_seconds, "秒")}`
                          : "—"}
                      {entry.exhibition?.lap_source === "race.boatcast.jp" && (
                        <small>Boatcast</small>
                      )}
                    </td>
                    <td>
                      {format(
                        entry.exhibition?.cornering_time_seconds ?? null,
                        "秒",
                      )}
                    </td>
                    <td>
                      {format(
                        entry.exhibition?.straight_time_seconds ?? null,
                        "秒",
                      )}
                    </td>
                    <td>{entry.motor_number ?? "—"}</td>
                    <td>
                      {entry.part_replacements.length
                        ? entry.part_replacements
                            .map((item) =>
                              item.quantity > 1
                                ? `${item.part_name}×${item.quantity}`
                                : item.part_name,
                            )
                            .join("、")
                        : "—"}
                    </td>
                    <td>
                      <strong>{score ? `${score.rank}位 / ${score.score}点` : "—"}</strong>
                      {score?.warnings.map((warning) => (
                        <small className="warning" key={warning}>
                          {warning}
                        </small>
                      ))}
                    </td>
                    <td>
                      <strong>
                        {result?.finish_position ?? result?.status ?? "未確定"}
                      </strong>
                      {result?.actual_start_timing !== null &&
                        result?.actual_start_timing !== undefined && (
                          <small>本番ST {result.actual_start_timing}</small>
                        )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <div className="section-heading">
          <div>
            <p className="eyebrow">PREDICTION VS RESULT</p>
            <h2>結果照合</h2>
          </div>
        </div>
        {race.result ? (
          <>
            <ResultComparison race={race} analysis={analysis} />
            <div className="disclaimer">
              結果出典:{" "}
              {race.result.source === "boatrace.jp"
                ? "BOAT RACE公式サイト（締切予定時刻の15分後から取得）"
                : "保存済み結果データ"}
            </div>
          </>
        ) : (
          <div className="status-card compact">
            <strong>結果は未確定です</strong>
            <p>締切予定時刻の15分後から公式結果を確認します。</p>
          </div>
        )}
      </section>

      <section>
        <div className="section-heading">
          <div>
            <p className="eyebrow">SCORE BREAKDOWN</p>
            <h2>評価根拠</h2>
          </div>
        </div>
        <div className="contribution-list">
          {analysis.items.map((item) => (
            <details key={item.lane}>
              <summary>
                <span className={`lane-number lane-${item.lane}`}>{item.lane}</span>
                <strong>{item.rank}位の寄与内訳</strong>
                <span>{item.score}点</span>
              </summary>
              <div className="contribution-grid">
                {item.contributions.map((part) => (
                  <div key={part.key}>
                    <div>
                      <strong>{part.label}</strong>
                      <span>+{part.points}</span>
                    </div>
                    <div className="mini-bar">
                      <span style={{ width: `${Math.min(Number(part.points) * 2, 100)}%` }} />
                    </div>
                    <small>{part.explanation}</small>
                  </div>
                ))}
              </div>
            </details>
          ))}
        </div>
      </section>
    </>
  );
}

function TwoBoatFlowPanel({ flow }: { flow: TwoBoatFlow }) {
  const escapeLabels = {
    likely: "イン逃げ寄り",
    unlikely: "イン不安",
    uncertain: "判定保留",
    not_assessed: "対象外",
  };
  const statusLabel = {
    pass: "次のレース",
    insufficient_data: "データ不足",
    review: "要比較",
  }[flow.status] ?? "要確認";
  const stepResultLabel = {
    yes: "YES",
    no: "NO",
    unknown: "不明",
  };
  return (
    <div className="flow-panel">
      <div className="flow-summary">
        <article>
          <span>判定</span>
          <strong>{statusLabel}</strong>
        </article>
        <article>
          <span>ヤリそうな艇</span>
          <strong>
            {flow.likely_lanes.length
              ? flow.likely_lanes.map((lane) => `${lane}号艇`).join("・")
              : "なし"}
          </strong>
        </article>
        <article>
          <span>イン評価</span>
          <strong>{escapeLabels[flow.escape_assessment]}</strong>
        </article>
        <article>
          <span>候補点数 / 合成オッズ（均等払戻換算）</span>
          <strong>
            {flow.tickets.length}点 /{" "}
            {flow.composite_odds ? `${Number(flow.composite_odds).toFixed(2)}倍` : "未取得"}
          </strong>
        </article>
      </div>
      <ol className="flow-steps">
        {flow.steps.map((step) => (
          <li key={step.number}>
            <span>{step.number}</span>
            <strong>{stepResultLabel[step.result as keyof typeof stepResultLabel] ?? step.result}</strong>
            <p>{step.detail}</p>
          </li>
        ))}
      </ol>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>艇</th>
              <th>単勝人気</th>
              <th>締切単勝</th>
              <th>展示順位（補正後）</th>
              <th>一周順位（補正後）</th>
              <th>平均ST順位</th>
              <th>平均ST</th>
              <th>全国勝率</th>
              <th>コース3連率</th>
              <th>進入数</th>
              <th>履歴基準日</th>
              <th>AP</th>
            </tr>
          </thead>
          <tbody>
            {flow.metrics.map((metric) => (
              <tr key={metric.lane}>
                <td>
                  <span className={`lane-number lane-${metric.lane}`}>
                    {metric.lane}
                  </span>
                </td>
                <td>
                  {metric.popularity_rank ? (
                    <strong className="popularity-rank">
                      {metric.popularity_rank}番人気
                    </strong>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  {metric.win_odds
                    ? `${Number(metric.win_odds).toFixed(1)}倍`
                    : "—"}
                </td>
                <td>{metric.exhibition_rank ? `${metric.exhibition_rank}位` : "—"}</td>
                <td>{metric.lap_rank ? `${metric.lap_rank}位` : "—"}</td>
                <td>{metric.course_avg_start_rank ?? "—"}</td>
                <td>{metric.course_avg_start_timing ?? "—"}</td>
                <td>
                  {metric.nationwide_win_rate
                    ? `${metric.nationwide_win_rate}`
                    : "—"}
                </td>
                <td>
                  {metric.course_top3_rate
                    ? `${Number(metric.course_top3_rate).toFixed(1)}%`
                    : "—"}
                </td>
                <td>{metric.course_starts ?? "—"}</td>
                <td>{metric.course_stats_snapshot_date ?? "—"}</td>
                <td>{metric.ap ? "あり" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="odds-source-note">
        単勝人気:{" "}
        {flow.win_odds_source === "boatrace.jp"
          ? `BOAT RACE公式（締切3分前から取得${
              flow.win_odds_observed_at
                ? `・${new Date(flow.win_odds_observed_at).toLocaleTimeString(
                    "ja-JP",
                    {
                      timeZone: "Asia/Tokyo",
                      hour: "2-digit",
                      minute: "2-digit",
                    },
                  )}`
                : ""
            }）`
          : flow.win_odds_source === "source_database"
            ? "元DBの締切単勝オッズ（過去レース）"
            : "公式取得時刻前または未取得"}
      </p>
      {flow.tickets.length > 0 && (
        <div className="ticket-ranking">
          <div className="ticket-ranking-heading">
            <strong>買い目候補の人気順位</strong>
            <span>全3連単の締切オッズが低い順</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>人気順位</th>
                  <th>買い目</th>
                  <th>締切オッズ</th>
                </tr>
              </thead>
              <tbody>
                {[...flow.tickets]
                  .sort(
                    (left, right) =>
                      (left.popularity_rank ?? Number.MAX_SAFE_INTEGER) -
                        (right.popularity_rank ?? Number.MAX_SAFE_INTEGER) ||
                      left.combination.join("").localeCompare(right.combination.join("")),
                  )
                  .map((ticket) => (
                    <tr key={ticket.combination.join("-")}>
                      <td>
                        {ticket.popularity_rank ? (
                          <strong className="popularity-rank">
                            {ticket.popularity_rank}番人気
                          </strong>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        <strong className="ticket-combination">
                          {ticket.combination.join("-")}
                        </strong>
                      </td>
                      <td>
                        {ticket.odds
                          ? `${Number(ticket.odds).toFixed(1)}倍`
                          : "未取得"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <div className="disclaimer">{flow.disclaimer}</div>
    </div>
  );
}

function ResultComparison({
  race,
  analysis,
}: {
  race: RaceDetail;
  analysis: RaceAnalysis;
}) {
  const winner = race.result?.entries.find((item) => item.finish_position === 1);
  const predictedWinner = analysis.items.find((item) => item.rank === 1);
  const winnerPrediction = analysis.items.find((item) => item.lane === winner?.lane);
  const exact = winner?.lane === predictedWinner?.lane;
  return (
    <div className="result-comparison">
      <article className={exact ? "comparison-hit" : ""}>
        <span>参考1位</span>
        <strong>{predictedWinner ? `${predictedWinner.lane}号艇` : "—"}</strong>
      </article>
      <article>
        <span>実際の1着</span>
        <strong>{winner ? `${winner.lane}号艇` : "—"}</strong>
      </article>
      <article>
        <span>1着艇の参考順位</span>
        <strong>{winnerPrediction ? `${winnerPrediction.rank}位` : "—"}</strong>
      </article>
      <article className={exact ? "comparison-hit" : "comparison-miss"}>
        <span>照合</span>
        <strong>{exact ? "1位一致" : "不一致"}</strong>
      </article>
    </div>
  );
}
