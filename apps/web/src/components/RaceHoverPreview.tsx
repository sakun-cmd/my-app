"use client";

import Link from "next/link";
import { ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { getRace, getTwoBoatFlow } from "@/lib/api";
import type { RaceDetail, RaceSummary, TwoBoatFlow } from "@/lib/types";

type PreviewData = {
  race: RaceDetail;
  flow: TwoBoatFlow | null;
};

type PreviewCacheEntry = {
  expiresAt: number;
  request: Promise<PreviewData>;
};

const PREVIEW_CACHE_MILLISECONDS = 10_000;
const PREVIEW_REFRESH_MILLISECONDS = 15_000;
const previewCache = new Map<string, PreviewCacheEntry>();

const assessmentLabels: Record<TwoBoatFlow["escape_assessment"], string> = {
  likely: "イン有力",
  unlikely: "イン逃げ注意",
  low_confidence: "イン信頼不足",
  uncertain: "判定保留",
  not_assessed: "対象外",
};

function loadPreview(raceId: string, force = false): Promise<PreviewData> {
  const cached = previewCache.get(raceId);
  if (!force && cached && cached.expiresAt > Date.now()) return cached.request;
  const request = Promise.all([
    getRace(raceId),
    getTwoBoatFlow(raceId).catch(() => null),
  ]).then(([race, flow]) => ({ race, flow }));
  previewCache.set(raceId, {
    expiresAt: Date.now() + PREVIEW_CACHE_MILLISECONDS,
    request,
  });
  request.catch(() => {
    if (previewCache.get(raceId)?.request === request) {
      previewCache.delete(raceId);
    }
  });
  return request;
}

function displayTime(value: string | null) {
  if (!value) return "時刻未登録";
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function startTiming(value: string | null) {
  if (value === null) return "—";
  const parsed = Number(value);
  return parsed < 0 ? `F${Math.abs(parsed).toFixed(2)}` : parsed.toFixed(2);
}

export function RaceHoverPreview({
  race,
  className,
  children,
}: {
  race: RaceSummary;
  className: string;
  children: ReactNode;
}) {
  const linkRef = useRef<HTMLAnchorElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<PreviewData | null>(null);
  const [error, setError] = useState("");
  const [position, setPosition] = useState({ left: 16, top: 16 });

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  useEffect(() => {
    if (!open) return;
    let active = true;
    setData(null);
    setError("");

    function refresh(force = false) {
      void loadPreview(race.id, force)
        .then((result) => {
          if (active) {
            setData(result);
            setError("");
          }
        })
        .catch((reason: unknown) => {
          if (active) {
            setError(
              reason instanceof Error ? reason.message : "プレビューを取得できません",
            );
          }
        });
    }

    refresh();
    const refreshTimer = window.setInterval(
      () => refresh(true),
      PREVIEW_REFRESH_MILLISECONDS,
    );
    return () => {
      active = false;
      window.clearInterval(refreshTimer);
    };
  }, [open, race.id, race.data_completeness, race.status]);

  function showPreview() {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      const rect = linkRef.current?.getBoundingClientRect();
      if (rect) {
        const width = Math.min(440, window.innerWidth - 24);
        const left = Math.max(
          12,
          Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 12),
        );
        const preferredTop = rect.bottom + 10;
        const top =
          preferredTop + 430 <= window.innerHeight
            ? preferredTop
            : Math.max(12, rect.top - 440);
        setPosition({ left, top });
      }
      setOpen(true);
    }, 250);
  }

  function hidePreview() {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    setOpen(false);
  }

  const metrics = new Map(data?.flow?.metrics.map((item) => [item.lane, item]));

  return (
    <>
      <Link
        ref={linkRef}
        className={className}
        href={`/races/${race.id}`}
        onMouseEnter={showPreview}
        onMouseLeave={hidePreview}
        onFocus={showPreview}
        onBlur={hidePreview}
        aria-describedby={open ? `race-preview-${race.id}` : undefined}
      >
        {children}
      </Link>
      {open &&
        typeof document !== "undefined" &&
        createPortal(
          <aside
            id={`race-preview-${race.id}`}
            className="race-hover-preview"
            style={position}
            role="tooltip"
          >
            <div className="race-hover-preview-heading">
              <div>
                <span>{race.race_date} · {displayTime(race.scheduled_at)}</span>
                <strong>
                  {race.venue.name} {race.race_number}R
                </strong>
              </div>
              <span className="race-hover-preview-hint">クリックで全詳細 →</span>
            </div>

            {!data && !error ? (
              <p className="race-hover-preview-loading">レース情報を読み込み中…</p>
            ) : error ? (
              <p className="race-hover-preview-error">{error}</p>
            ) : data ? (
              <>
                <div className="race-hover-preview-summary">
                  <span>
                    イン評価
                    <strong>
                      {data.flow
                        ? assessmentLabels[data.flow.escape_assessment]
                        : "未取得"}
                    </strong>
                  </span>
                  <span>
                    注目艇
                    <strong>
                      {data.flow?.likely_lanes.length
                        ? data.flow.likely_lanes.map((lane) => `${lane}号艇`).join("・")
                        : "なし"}
                    </strong>
                  </span>
                  <span>
                    買い目
                    <strong>
                      {data.flow?.tickets.length
                        ? `${data.flow.tickets.length}点`
                        : "なし"}
                    </strong>
                  </span>
                </div>

                <div className="race-hover-preview-table">
                  <div className="race-hover-preview-table-head">
                    <span>艇</span>
                    <span>選手</span>
                    <span>人気</span>
                    <span>展示</span>
                    <span>ST</span>
                    <span>一周</span>
                  </div>
                  {data.race.entries.map((entry) => {
                    const metric = metrics.get(entry.lane);
                    return (
                      <div className="race-hover-preview-table-row" key={entry.lane}>
                        <span className={`lane-number lane-${entry.lane}`}>
                          {entry.lane}
                        </span>
                        <strong>{entry.racer_name ?? "未登録"}</strong>
                        <span>
                          {metric?.popularity_rank
                            ? `${metric.popularity_rank}位`
                            : "—"}
                        </span>
                        <span>
                          {entry.exhibition?.exhibition_time_seconds ?? "—"}
                        </span>
                        <span>
                          {startTiming(
                            entry.exhibition?.exhibition_start_timing ?? null,
                          )}
                        </span>
                        <span>{entry.exhibition?.lap_time_seconds ?? "—"}</span>
                      </div>
                    );
                  })}
                </div>

                {data.race.result?.trifecta_combination && (
                  <p className="race-hover-preview-result">
                    確定3連単 <strong>{data.race.result.trifecta_combination}</strong>
                    {data.race.result.trifecta_payout_yen
                      ? ` · ${data.race.result.trifecta_payout_yen.toLocaleString("ja-JP")}円`
                      : ""}
                  </p>
                )}
              </>
            ) : null}
          </aside>,
          document.body,
        )}
    </>
  );
}
