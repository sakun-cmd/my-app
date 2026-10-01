"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  dailyExcelUrl,
  getRaces,
  getTwoBoatFlowSummary,
  refreshLiveData,
} from "@/lib/api";
import { orderLiveRaces } from "@/lib/live-race-order";
import type { ImportBatch, RaceListResponse, TwoBoatFlowSummary } from "@/lib/types";
import { ErrorState, LoadingState } from "./Status";

const statusLabels = {
  upcoming: "発売前",
  live: "確定待ち",
  pending_result: "結果待ち",
  final: "確定",
  cancelled: "中止",
  void: "不成立",
  unknown: "状態不明",
};

function dateInJapan(value = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function displayTime(value: string | null) {
  if (!value) return "時刻未登録";
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function LiveRaceView() {
  const raceDate = useMemo(dateInJapan, []);
  const previousRaceDate = useMemo(
    () =>
      dateInJapan(
        new Date(
          new Date(`${raceDate}T00:00:00+09:00`).getTime() - 24 * 60 * 60 * 1000,
        ),
      ),
    [raceDate],
  );
  const [data, setData] = useState<RaceListResponse | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [officialResults, setOfficialResults] =
    useState<ImportBatch["official_results"] | null>(null);
  const [officialExhibitions, setOfficialExhibitions] =
    useState<ImportBatch["official_exhibitions"] | null>(null);
  const [officialWinOdds, setOfficialWinOdds] =
    useState<ImportBatch["official_win_odds"] | null>(null);
  const [boatcastLaps, setBoatcastLaps] =
    useState<ImportBatch["boatcast_laps"] | null>(null);
  const [flowSummaries, setFlowSummaries] = useState<Map<string, TwoBoatFlowSummary>>(
    new Map(),
  );
  const orderedRaces = useMemo(
    () => (data ? orderLiveRaces(data.items) : []),
    [data],
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError("");
    try {
      const refreshResult = await refreshLiveData();
      setOfficialResults(refreshResult.official_results);
      setOfficialExhibitions(refreshResult.official_exhibitions);
      setOfficialWinOdds(refreshResult.official_win_odds);
      setBoatcastLaps(refreshResult.boatcast_laps);
      const [races, flows] = await Promise.all([
        getRaces({ date: raceDate, pageSize: 500 }),
        getTwoBoatFlowSummary(raceDate).catch(() => [] as TwoBoatFlowSummary[]),
      ]);
      setData(races);
      setFlowSummaries(new Map(flows.map((item) => [item.race_id, item])));
      setLastUpdated(new Date());
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "LIVE更新に失敗しました");
    } finally {
      setRefreshing(false);
    }
  }, [raceDate]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return (
    <section>
      <div className="section-heading live-heading">
        <div>
          <p className="eyebrow">LIVE EXHIBITION MONITOR</p>
          <h1>本日のレース</h1>
        </div>
        <div className="live-controls">
          <span className="live-indicator">
            <i aria-hidden="true" />
            60秒ごとに自動更新
          </span>
          <button type="button" onClick={() => void refresh()} disabled={refreshing}>
            {refreshing ? "更新中…" : "今すぐ更新"}
          </button>
          <a className="button-link secondary" href={dailyExcelUrl(previousRaceDate)}>
            前日Excel
          </a>
        </div>
      </div>

      <div className="live-meta">
        <strong>{raceDate}</strong>
        <span>
          最終更新:{" "}
          {lastUpdated
            ? lastUpdated.toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo" })
            : "更新待ち"}
        </span>
        <span>結果は締切15分後から公式取得</span>
        <span>展示は締切5分前から公式取得</span>
        <span>単勝オッズは締切3分前から公式取得</span>
        <span>周回展示は展示と同じ締切5分前からBoatcast取得</span>
        {officialExhibitions && (
          <span>
            公式展示: 確認 {officialExhibitions.checked_races} / 取得{" "}
            {officialExhibitions.imported_races}
            {officialExhibitions.errors_count > 0 &&
              ` / エラー ${officialExhibitions.errors_count}`}
          </span>
        )}
        {officialResults && (
          <span>
            公式結果: 確認 {officialResults.checked_races} / 確定{" "}
            {officialResults.finalized_races}
            {officialResults.errors_count > 0 &&
              ` / エラー ${officialResults.errors_count}`}
          </span>
        )}
        {officialWinOdds && (
          <span>
            公式単勝: 確認 {officialWinOdds.checked_races} / 取得{" "}
            {officialWinOdds.imported_races}
            {officialWinOdds.errors_count > 0 &&
              ` / エラー ${officialWinOdds.errors_count}`}
          </span>
        )}
        {boatcastLaps && (
          <span>
            Boatcast周回: 確認 {boatcastLaps.checked_races} / 取得{" "}
            {boatcastLaps.imported_races}
            {boatcastLaps.errors_count > 0 &&
              ` / エラー ${boatcastLaps.errors_count}`}
          </span>
        )}
      </div>

      {error ? (
        <ErrorState message={error} />
      ) : !data ? (
        <LoadingState label="当日の展示・結果データを更新しています" />
      ) : data.items.length === 0 ? (
        <div className="status-card">
          <strong>本日のレースはありません</strong>
          <p>開催日または元データの更新状況を確認してください。</p>
        </div>
      ) : (
        <div className="live-race-list">
          {orderedRaces.map((race) => {
            const flow = flowSummaries.get(race.id);
            return (
              <Link href={`/races/${race.id}`} className="live-race-row" key={race.id}>
                <time>{displayTime(race.scheduled_at)}</time>
                <strong>{race.venue.name}</strong>
                <span className="live-race-number">{race.race_number}R</span>
                <span className={`tag status-${race.status}`}>
                  {statusLabels[race.status]}
                </span>
                <span className="live-completeness">
                  展示 {race.data_completeness}%
                </span>
                <span className="live-ticket-flag">
                  {flow?.has_tickets && (
                    <span className="tag" title={`買い目候補 ${flow.ticket_count}点`}>
                      買い目あり
                    </span>
                  )}
                </span>
                <span className="live-hit-flag">
                  {flow?.hit === true && <span className="tag hit">的中</span>}
                  {flow?.hit === false && <span className="tag miss">不的中</span>}
                </span>
                <span aria-hidden="true">→</span>
              </Link>
            );
          })}
        </div>
      )}

      <div className="disclaimer">
        展示タイム・展示進入・展示ST・単勝オッズと確定結果はBOAT RACE公式サイト、
        周回展示はBoatcastから取得します。公式掲載の遅延や変更が
        あり得るため、本表示だけで購入判断を行わないでください。
      </div>
    </section>
  );
}
