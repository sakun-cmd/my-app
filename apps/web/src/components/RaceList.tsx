"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { getRaces } from "@/lib/api";
import type { RaceListResponse } from "@/lib/types";
import { EmptyState, ErrorState, LoadingState } from "./Status";

function displayTime(value: string | null) {
  if (!value) return "時刻未登録";
  return new Intl.DateTimeFormat("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

const statusLabels = {
  upcoming: "発売前",
  live: "確定待ち",
  pending_result: "結果待ち",
  final: "確定",
  cancelled: "中止",
  void: "不成立",
  unknown: "状態不明",
};

export function RaceList() {
  const [filters, setFilters] = useState({ date: "", venue: "" });
  const [query, setQuery] = useState(filters);
  const [data, setData] = useState<RaceListResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    getRaces(query, controller.signal)
      .then(setData)
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
    setQuery(filters);
  }

  return (
    <>
      <form className="filters" onSubmit={submit}>
        <label>
          開催日
          <input
            type="date"
            value={filters.date}
            onChange={(event) =>
              setFilters((current) => ({ ...current, date: event.target.value }))
            }
          />
        </label>
        <label>
          場コード
          <input
            inputMode="numeric"
            maxLength={2}
            placeholder="例: 01"
            value={filters.venue}
            onChange={(event) =>
              setFilters((current) => ({ ...current, venue: event.target.value }))
            }
          />
        </label>
        <button type="submit">絞り込む</button>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            const empty = { date: "", venue: "" };
            setFilters(empty);
            setData(null);
            setQuery(empty);
          }}
        >
          クリア
        </button>
      </form>

      {error ? (
        <ErrorState message={error} />
      ) : !data ? (
        <LoadingState label="レースデータを読み込んでいます" />
      ) : data.items.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="race-grid">
          {data.items.map((race) => (
            <Link className="race-card" href={`/races/${race.id}`} key={race.id}>
              <div className="race-card-heading">
                <span className="race-number">{race.race_number}R</span>
                <span className={`tag status-${race.status}`}>
                  {statusLabels[race.status]}
                </span>
              </div>
              <h2>{race.venue.name}</h2>
              <p className="muted">
                {race.race_date} · {displayTime(race.scheduled_at)}
              </p>
              <div className="completeness">
                <span>展示データ充足度</span>
                <strong>{race.data_completeness}%</strong>
                <div className="meter" aria-hidden="true">
                  <span style={{ width: `${race.data_completeness}%` }} />
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
