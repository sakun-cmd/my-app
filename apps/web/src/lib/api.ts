import type {
  RaceAnalysis,
  RaceDetail,
  RaceListResponse,
  EvaluationSummary,
  ImportBatch,
  LabDashboard,
  LabRefresh,
  SourceInspection,
  TwoBoatEvaluation,
  TwoBoatFlow,
  TwoBoatFlowSummary,
} from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function dailyExcelUrl(raceDate: string): string {
  const params = new URLSearchParams({ race_date: raceDate });
  return `${API_BASE_URL}/api/reports/daily.xlsx?${params}`;
}

async function request<T>(
  path: string,
  signal?: AbortSignal,
  method: "GET" | "POST" = "GET",
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    signal,
    method,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `API request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function getRaces(
  filters: { date?: string; venue?: string; pageSize?: number },
  signal?: AbortSignal,
): Promise<RaceListResponse> {
  const params = new URLSearchParams();
  if (filters.date) params.set("race_date", filters.date);
  if (filters.venue) params.set("venue_code", filters.venue);
  if (filters.pageSize) params.set("page_size", String(filters.pageSize));
  const query = params.size ? `?${params}` : "";
  return request(`/api/races${query}`, signal);
}

export function getRace(id: string, signal?: AbortSignal): Promise<RaceDetail> {
  return request(`/api/races/${id}`, signal);
}

export function getRaceAnalysis(
  id: string,
  signal?: AbortSignal,
): Promise<RaceAnalysis> {
  return request(`/api/analysis/races/${id}`, signal);
}

export function getTwoBoatFlow(
  id: string,
  signal?: AbortSignal,
): Promise<TwoBoatFlow> {
  return request(`/api/analysis/races/${id}/two-boat-flow`, signal);
}

export function getTwoBoatFlowSummary(
  raceDate: string,
  signal?: AbortSignal,
): Promise<TwoBoatFlowSummary[]> {
  const params = new URLSearchParams({ race_date: raceDate });
  return request(`/api/analysis/two-boat-flow/summary?${params}`, signal);
}

export function inspectSource(signal?: AbortSignal): Promise<SourceInspection> {
  return request("/api/imports/source-schema", signal);
}

export function refreshLiveData(signal?: AbortSignal): Promise<ImportBatch> {
  return request("/api/imports/live-refresh", signal, "POST");
}

export function getEvaluation(
  filters: { dateFrom?: string; dateTo?: string },
  signal?: AbortSignal,
): Promise<EvaluationSummary> {
  const params = new URLSearchParams();
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  const query = params.size ? `?${params}` : "";
  return request(`/api/evaluations/summary${query}`, signal);
}

export function getTwoBoatEvaluation(
  filters: {
    dateFrom: string;
    dateTo: string;
    dataSource: "live_saved" | "source_database";
  },
  signal?: AbortSignal,
): Promise<TwoBoatEvaluation> {
  const params = new URLSearchParams({
    date_from: filters.dateFrom,
    date_to: filters.dateTo,
    data_source: filters.dataSource,
  });
  return request(`/api/evaluations/two-boat-flow?${params}`, signal);
}

export function getLabDashboard(
  filters: { dateFrom: string; dateTo: string; recentLimit?: number },
  signal?: AbortSignal,
): Promise<LabDashboard> {
  const params = new URLSearchParams({
    date_from: filters.dateFrom,
    date_to: filters.dateTo,
    recent_limit: String(filters.recentLimit ?? 100),
  });
  return request(`/api/lab/dashboard?${params}`, signal);
}

export function refreshLab(signal?: AbortSignal): Promise<LabRefresh> {
  return request("/api/lab/refresh", signal, "POST");
}
