"use client";

import { useEffect, useState } from "react";

import { inspectSource } from "@/lib/api";
import type { SourceInspection } from "@/lib/types";
import { ErrorState, LoadingState } from "./Status";

export function DataQualityView() {
  const [inspection, setInspection] = useState<SourceInspection | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    inspectSource(controller.signal)
      .then(setInspection)
      .catch((reason: unknown) => {
        if (reason instanceof Error && reason.name !== "AbortError") {
          setError(reason.message);
        }
      });
    return () => controller.abort();
  }, []);

  if (error) return <ErrorState message={error} />;
  if (!inspection) return <LoadingState label="既存DBのスキーマを調査しています" />;

  return (
    <section>
      <div className="section-heading">
        <div>
          <p className="eyebrow">SOURCE DATABASE</p>
          <h1>データ品質</h1>
        </div>
        <p>
          {inspection.database_name} · {inspection.tables.length}テーブル
        </p>
      </div>
      <div className="quality-grid">
        {inspection.tables.map((table) => (
          <article className="quality-card" key={`${table.schema_name}.${table.table_name}`}>
            <div>
              <span>{table.schema_name}</span>
              <h2>{table.table_name}</h2>
            </div>
            <strong>
              {table.estimated_rows === null
                ? "件数不明"
                : `約 ${table.estimated_rows.toLocaleString("ja-JP")} 行`}
            </strong>
            <p>{table.columns.length} 列</p>
            <p className="muted">
              主キー: {table.primary_key.length ? table.primary_key.join(", ") : "未定義"}
            </p>
            <details>
              <summary>列定義を表示</summary>
              <ul className="column-list">
                {table.columns.map((column) => (
                  <li key={column.name}>
                    <code>{column.name}</code>
                    <span>
                      {column.data_type}
                      {column.nullable ? " · NULL可" : " · 必須"}
                      {column.null_fraction === null
                        ? ""
                        : ` · NULL ${Math.round(column.null_fraction * 100)}%`}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          </article>
        ))}
      </div>
    </section>
  );
}
