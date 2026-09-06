/** Typed client for the YIELDMAP API. */

import type { Kpi } from "./kpi";

/**
 * Same origin, always. Next rewrites /api to the FastAPI service at runtime, so this build runs
 * unchanged against a local API, a preview deployment and production — and the browser never makes
 * a cross-origin request.
 */
export const API_BASE = "/api";

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

/**
 * The bearer token, held in memory for the tab's lifetime.
 *
 * Not localStorage: anything written there is readable by any script that reaches this origin, so
 * a single injected script turns into a stolen session that outlives the tab. A variable is lost
 * on reload, which is a real cost — the user signs in again — and the right trade for a token that
 * can start work costing money. A refresh-cookie flow is the fix when this has real accounts.
 */
let accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };
  // The role is never sent. It is a claim inside the token, which only the API can make, and the
  // interface asking for one used to be the entire access-control system.
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });

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
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
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
