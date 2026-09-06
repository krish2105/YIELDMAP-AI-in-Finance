/** Typed client for the YIELDMAP API. */

import type { Kpi } from "./kpi";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export type Role = "viewer" | "analyst" | "admin";
export type Provenance = "REAL" | "SYNTHETIC";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  { role = "viewer", ...init }: RequestInit & { role?: Role } = {},
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Yieldmap-Role": role,
      ...(init.headers ?? {}),
    },
  });

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json())?.detail;
    } catch {
      detail = await response.text().catch(() => undefined);
    }
    // A 503 here is nearly always "the database has not been built", which is worth saying
    // plainly rather than surfacing as a generic failure.
    throw new ApiError(
      typeof detail === "string" ? detail : `Request to ${path} failed`,
      response.status,
      detail,
    );
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, role?: Role) => request<T>(path, { role }),
  post: <T>(path: string, body: unknown, role: Role = "analyst") =>
    request<T>(path, { method: "POST", body: JSON.stringify(body), role }),
};

// --- response shapes -------------------------------------------------------

export interface KpiEnvelope {
  kpis: Kpi[];
  provenance: Provenance;
  notice: string;
}

export interface AreaRow {
  area_key: string;
  name: string;
  dld_name: string;
  lat: number | null;
  lon: number | null;
  coord_confidence: string | null;
  has_location: boolean;
  n_transactions: number;
}

export interface SeriesPoint {
  month: string;
  median_ppsqm: number;
  n: number;
}

export interface AreaDetail {
  area_key: string;
  kpis: Kpi[];
  series: { sql: string; points: SeriesPoint[] };
  risk: RiskRow | null;
  forecast: ForecastRow | null;
  provenance: Provenance;
  notice: string;
}

export interface RiskRow {
  area_key: string;
  n: number;
  score: number | null;
  components: Record<string, number | null>;
  raw: Record<string, number | null>;
  reason: string | null;
}

export interface ForecastRow {
  area_key: string;
  n_months: number;
  trend_per_month: number;
  forecast: number[];
  lower: number[];
  upper: number[];
  backtest_mape: number | null;
  naive_mape: number | null;
  beats_naive: boolean | null;
}

export interface ScreenerRow {
  area_key: string;
  area_name: string | null;
  property_type: string | null;
  rooms: number | null;
  n: number;
  median_price: number;
  median_ppsqm: number;
  ppsqm_sd: number | null;
  offplan_share: number | null;
  cv: number | null;
}

export interface Citation {
  n: number;
  title: string;
  section?: string | null;
  source: string;
  source_url?: string | null;
  kind: string;
  status?: string;
  provenance?: Provenance;
}

export interface AskAnswer {
  question: string;
  language: string;
  answer: string;
  citations: Citation[];
  used_sources: number[];
  found_material: boolean;
  citation_coverage: number;
  degraded: boolean;
  backend: string | null;
  notes: string[];
  dropped_sentences: string[];
  provenance: Provenance;
  notice: string;
}

export interface MemoSummary {
  id: string;
  run_id: string;
  area_key: string;
  status: string;
  provenance: Provenance;
  created_at: string;
  citations: number;
  citation_coverage: number;
  disagreements: number;
  audit_severity: string;
  blocked: boolean;
}
