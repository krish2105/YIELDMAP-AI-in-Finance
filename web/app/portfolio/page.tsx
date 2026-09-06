"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { DataTable } from "@/components/DataTable";
import { AdviceNotice } from "@/components/Notices";
import { Card, ErrorState, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { api } from "@/lib/api";
import { useAreas } from "@/lib/hooks";
import { aed, percent } from "@/lib/format";

interface Holding {
  area_key: string;
  value: number;
  annual_rent: number;
  sqm: number;
  loan: number;
}

interface PortfolioResult {
  holdings: number;
  blended_yield: { gross: number | null; net: number | null; total_value: number };
  projection: { irr: number | null };
  concentration: {
    by_area: { groups: number; hhi: number; effective: number; largest_share: number };
    by_holding: { count: number; hhi: number; effective: number };
  };
  correlation: { mean_correlation: number | null; areas: string[]; matrix: number[][] | null };
  diversification: {
    naive_effective_holdings: number;
    correlation_adjusted: number | null;
    mean_correlation?: number;
    note: string;
  };
  notice: string;
}

export default function PortfolioPage() {
  const { t } = useShell();
  const areas = useAreas();
  const [holdings, setHoldings] = useState<Holding[]>([
    { area_key: "", value: 1_500_000, annual_rent: 105_000, sqm: 95, loan: 0 },
  ]);

  const analyse = useMutation({
    mutationFn: () =>
      api.post<PortfolioResult>(
        "/simulate/portfolio",
        { holdings: holdings.filter((h) => h.area_key) },
      ),
  });

  const update = (index: number, patch: Partial<Holding>) =>
    setHoldings((current) => current.map((h, i) => (i === index ? { ...h, ...patch } : h)));

  return (
    <>
      <PageHeader
        title={t("nav.portfolio")}
        lede="What changes once you own more than one. Concentration, correlation, and how many genuinely independent positions you actually hold."
      />
      <div className="mb-4">
        <AdviceNotice />
      </div>

      <Section title="Your holdings">
        <Card>
          <div className="space-y-3">
            {holdings.map((holding, index) => (
              <div key={index} className="grid gap-2 sm:grid-cols-[1fr_repeat(4,7rem)_2rem]">
                <select
                  value={holding.area_key}
                  onChange={(event) => update(index, { area_key: event.target.value })}
                  className="rounded border border-line bg-bg px-2 py-1.5 text-sm text-ink"
                  aria-label={`Community for holding ${index + 1}`}
                >
                  <option value="">Choose a community…</option>
                  {(areas.data?.areas ?? []).map((area) => (
                    <option key={area.area_key} value={area.area_key}>
                      {area.name}
                    </option>
                  ))}
                </select>
                {(
                  [
                    ["value", "Value"],
                    ["annual_rent", "Rent"],
                    ["sqm", "sqm"],
                    ["loan", "Loan"],
                  ] as const
                ).map(([field, label]) => (
                  <label key={field} className="text-xs">
                    <span className="sr-only">{`${label} for holding ${index + 1}`}</span>
                    <input
                      type="number"
                      value={holding[field]}
                      min={0}
                      onChange={(event) => update(index, { [field]: Number(event.target.value) })}
                      placeholder={label}
                      className="w-full rounded border border-line bg-bg px-2 py-1.5 text-ink"
                    />
                  </label>
                ))}
                <button
                  type="button"
                  onClick={() => setHoldings((current) => current.filter((_, i) => i !== index))}
                  disabled={holdings.length === 1}
                  aria-label={`Remove holding ${index + 1}`}
                  className="rounded border border-line text-ink-muted hover:border-teal disabled:opacity-40"
                >
                  ×
                </button>
              </div>
            ))}
          </div>

          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() =>
                setHoldings((current) => [
                  ...current,
                  { area_key: "", value: 1_000_000, annual_rent: 70_000, sqm: 80, loan: 0 },
                ])
              }
              disabled={holdings.length >= 12}
              className="rounded-lg border border-line px-3 py-1.5 text-xs text-ink-secondary hover:border-teal hover:text-teal-ink disabled:opacity-40"
            >
              Add a holding
            </button>
            <button
              type="button"
              onClick={() => analyse.mutate()}
              disabled={!holdings.some((h) => h.area_key)}
              className="rounded-lg border border-teal bg-sunken px-3 py-1.5 text-xs font-medium text-ink disabled:opacity-40"
            >
              Analyse the basket
            </button>
          </div>
        </Card>
      </Section>

      {analyse.isError ? <ErrorState message={(analyse.error as Error).message} /> : null}

      {analyse.data ? (
        <>
          <Section title="The basket">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[
                ["Total value", aed(analyse.data.blended_yield.total_value)],
                [
                  "Blended gross yield",
                  analyse.data.blended_yield.gross !== null
                    ? percent(analyse.data.blended_yield.gross * 100)
                    : "—",
                ],
                [
                  "Blended net yield",
                  analyse.data.blended_yield.net !== null
                    ? percent(analyse.data.blended_yield.net * 100)
                    : "—",
                ],
                [
                  "Portfolio IRR",
                  analyse.data.projection.irr !== null
                    ? percent(analyse.data.projection.irr * 100)
                    : "—",
                ],
              ].map(([label, value]) => (
                <Card key={label}>
                  <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
                  <p className="mt-1 font-display text-2xl text-ink">{value}</p>
                </Card>
              ))}
            </div>
            <p className="mt-2 text-xs text-ink-muted">
              Blended yield is weighted by value, not averaged. A two-million holding at 4% beside a
              two-hundred-thousand one at 10% is a 4.5% portfolio; a simple mean would call it 7%.
            </p>
          </Section>

          <Section
            title="The diversification illusion"
            hint="Four apartments in four Dubai communities feel diversified and largely are not."
          >
            <Card>
              <div className="grid gap-4 sm:grid-cols-3">
                <div>
                  <p className="text-xs text-ink-muted">Holdings</p>
                  <p className="font-display text-2xl text-ink">
                    {analyse.data.concentration.by_holding.count}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-ink-muted">Effective, by size</p>
                  <p className="font-display text-2xl text-ink">
                    {analyse.data.diversification.naive_effective_holdings.toFixed(2)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-ink-muted">After correlation</p>
                  <p className="font-display text-2xl" style={{ color: "var(--warn-ink)" }}>
                    {analyse.data.diversification.correlation_adjusted !== null
                      ? analyse.data.diversification.correlation_adjusted.toFixed(2)
                      : "—"}
                  </p>
                </div>
              </div>
              <p className="mt-3 text-xs text-ink-secondary">{analyse.data.diversification.note}</p>
              <dl className="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-3">
                <div>
                  <dt className="text-ink-muted">Area concentration (HHI)</dt>
                  <dd className="text-ink">{analyse.data.concentration.by_area.hhi.toFixed(3)}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">Largest area share</dt>
                  <dd className="text-ink">
                    {percent(analyse.data.concentration.by_area.largest_share * 100, 0)}
                  </dd>
                </div>
                <div>
                  <dt className="text-ink-muted">Mean correlation</dt>
                  <dd className="text-ink">
                    {analyse.data.correlation.mean_correlation !== null
                      ? analyse.data.correlation.mean_correlation.toFixed(2)
                      : "not measurable"}
                  </dd>
                </div>
              </dl>
            </Card>
          </Section>

          {analyse.data.correlation.matrix ? (
            <Section title="How the areas move together" hint="Correlation of monthly returns.">
              <DataTable
                columns={[
                  { key: "area", label: "Area" },
                  ...analyse.data.correlation.areas.map((area) => ({
                    key: area,
                    label: area,
                    align: "right" as const,
                  })),
                ]}
                rows={analyse.data.correlation.matrix.map((row, i) => {
                  const record: Record<string, unknown> = {
                    area: analyse.data!.correlation.areas[i],
                  };
                  row.forEach((value, j) => {
                    record[analyse.data!.correlation.areas[j]!] = value.toFixed(2);
                  });
                  return record;
                })}
              />
            </Section>
          ) : null}
        </>
      ) : null}
    </>
  );
}
