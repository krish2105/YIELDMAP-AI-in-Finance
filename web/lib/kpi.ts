/**
 * The KPI contract.
 *
 * Every number YIELDMAP shows crosses the API as one of these objects, never as a bare float.
 * The point is Rule 3: a reader can always get from a rendered figure back to the exact SQL that
 * produced it, the sample it came from, and the method that defines it.
 */
import thresholds from "../../config/kpi_thresholds.json";

export type Confidence = "high" | "medium" | "low" | "insufficient";

export type KpiSource =
  | { kind: "sql"; ref: string }
  | { kind: "doc"; ref: string; sha256?: string };

export interface KpiDelta {
  value: number;
  /** e.g. "12m", "yoy", "30d" */
  window: string;
  direction: "up" | "down" | "flat";
}

export interface Kpi {
  id: string;
  label: string;
  /** null means the value could not be computed — render the insufficient-data state. */
  value: number | null;
  unit: string;
  format: "currency_aed" | "percent" | "count" | "ratio" | "index" | "score" | "years";
  delta?: KpiDelta;
  /** Sample size behind the value. Always present, always shown. */
  n: number;
  asof: string;
  confidence: Confidence;
  /** Deep-links to /methodology#<method_id>. */
  method_id: string;
  sql: string;
  sql_hash: string;
  sources: KpiSource[];
  /** Set when provenance is SYNTHETIC, so the UI can banner it. */
  synthetic?: boolean;
}

/**
 * Confidence from sample size and dispersion.
 *
 * `cv` is the coefficient of variation of the underlying sample (std / |mean|). A small sample or
 * a wildly dispersed one is not reported as a confident number — this is what stops the 3D city
 * from extruding a whole community on the strength of three transactions.
 */
export function confidenceFor(n: number, cv: number | null): Confidence {
  if (!Number.isFinite(n) || n < thresholds.min_n) return "insufficient";
  // Dispersion unknown (e.g. a count, which has none) — judge on sample size alone.
  const dispersion = cv === null || !Number.isFinite(cv) ? 0 : Math.abs(cv);
  if (n >= thresholds.high.min_n && dispersion <= thresholds.high.max_cv) return "high";
  if (n >= thresholds.medium.min_n && dispersion <= thresholds.medium.max_cv) return "medium";
  return "low";
}

/** True when the tile must render "insufficient data" instead of a number. */
export function isSuppressed(kpi: Pick<Kpi, "value" | "confidence">): boolean {
  return kpi.value === null || kpi.confidence === "insufficient";
}

const AED = new Intl.NumberFormat("en-AE", {
  style: "currency",
  currency: "AED",
  maximumFractionDigits: 0,
});

/** Display string for a KPI. Never invents a value: suppressed KPIs render a dash. */
export function formatKpi(kpi: Pick<Kpi, "value" | "format" | "unit" | "confidence">): string {
  if (isSuppressed(kpi)) return "—";
  const v = kpi.value as number;
  switch (kpi.format) {
    case "currency_aed":
      return AED.format(v);
    case "percent":
      return `${v.toFixed(2)}%`;
    case "count":
      return new Intl.NumberFormat("en-AE").format(Math.round(v));
    case "ratio":
      return v.toFixed(2);
    case "index":
      return v.toFixed(1);
    case "score":
      return Math.round(v).toString();
    case "years":
      return `${v.toFixed(1)} yr`;
  }
}
