import { describe, expect, it } from "vitest";
import { confidenceFor, formatKpi, isSuppressed, type Kpi } from "./kpi";

describe("confidenceFor", () => {
  it("suppresses samples below the minimum", () => {
    expect(confidenceFor(4, 0.1)).toBe("insufficient");
    expect(confidenceFor(0, 0)).toBe("insufficient");
  });

  it("rates a large, tight sample high", () => {
    expect(confidenceFor(120, 0.2)).toBe("high");
  });

  it("demotes a large but wildly dispersed sample", () => {
    expect(confidenceFor(120, 0.9)).toBe("low");
  });

  it("rates a mid-sized, moderately dispersed sample medium", () => {
    expect(confidenceFor(15, 0.5)).toBe("medium");
  });

  it("treats unknown dispersion as no dispersion, judging on n alone", () => {
    expect(confidenceFor(50, null)).toBe("high");
    expect(confidenceFor(6, null)).toBe("low");
  });

  it("is monotone in n at fixed dispersion", () => {
    const order = { insufficient: 0, low: 1, medium: 2, high: 3 };
    const ns = [1, 5, 10, 30, 100];
    const ranks = ns.map((n) => order[confidenceFor(n, 0.3)]);
    for (let i = 1; i < ranks.length; i++) {
      expect(ranks[i]!).toBeGreaterThanOrEqual(ranks[i - 1]!);
    }
  });
});

const base: Kpi = {
  id: "net_yield.jvc.apartment.1br",
  label: "Net yield",
  value: 6.42,
  unit: "%",
  format: "percent",
  n: 1284,
  asof: "2026-09-01",
  confidence: "high",
  method_id: "net_yield_v1",
  sql: "select 1",
  sql_hash: "abc123",
  sources: [{ kind: "sql", ref: "net_yield_v1" }],
};

describe("formatKpi", () => {
  it("formats a percent", () => {
    expect(formatKpi(base)).toBe("6.42%");
  });

  it("formats currency without decimals", () => {
    expect(formatKpi({ ...base, value: 1250000, format: "currency_aed" })).toContain("1,250,000");
  });

  it("renders a dash rather than a number when the sample is too small", () => {
    expect(formatKpi({ ...base, confidence: "insufficient" })).toBe("—");
    expect(formatKpi({ ...base, value: null })).toBe("—");
  });
});

describe("isSuppressed", () => {
  it("suppresses on a null value or insufficient confidence", () => {
    expect(isSuppressed({ value: null, confidence: "high" })).toBe(true);
    expect(isSuppressed({ value: 1, confidence: "insufficient" })).toBe(true);
    expect(isSuppressed({ value: 1, confidence: "low" })).toBe(false);
  });
});
