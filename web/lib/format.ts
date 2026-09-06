/** Number and date formatting, in one place so a figure reads the same wherever it appears. */

const AED0 = new Intl.NumberFormat("en-AE", {
  style: "currency",
  currency: "AED",
  maximumFractionDigits: 0,
});
const COUNT = new Intl.NumberFormat("en-AE");

/** Compact currency for axis ticks, where "AED 1,250,000" will not fit. */
export function compactAed(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}b`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}m`;
  if (abs >= 1e3) return `${Math.round(value / 1e3)}k`;
  return Math.round(value).toString();
}

export function aed(value: number): string {
  return AED0.format(value);
}

export function count(value: number): string {
  return COUNT.format(Math.round(value));
}

export function percent(value: number, digits = 2): string {
  return `${value.toFixed(digits)}%`;
}

export function signedPercent(value: number, digits = 1): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function monthLabel(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
}

export function dateLabel(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
