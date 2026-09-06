"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import City3D, { type CityDatum } from "@/components/City3D";
import KpiTile from "@/components/KpiTile";
import { AdviceNotice, ProvenanceNotice } from "@/components/Notices";
import { Card, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useAreas, useMarket, useResult } from "@/lib/hooks";
import { compactAed } from "@/lib/format";

type Metric = "ppsqm" | "volume" | "yield" | "risk";

const METRICS: { id: Metric; label: string; unit: string; hint: string }[] = [
  { id: "ppsqm", label: "Price per sqm", unit: "AED", hint: "median over the last 12 months" },
  { id: "volume", label: "Sales volume", unit: "sales", hint: "recorded in the last 12 months" },
  { id: "yield", label: "Net yield", unit: "%", hint: "after costs, where a cell is thick enough" },
  { id: "risk", label: "Risk score", unit: "/100", hint: "weighted, out of 100" },
];

export default function CityPage() {
  const { t } = useShell();
  const router = useRouter();
  const [metric, setMetric] = useState<Metric>("ppsqm");
  const [selected, setSelected] = useState<string | null>(null);

  const market = useMarket();
  const areas = useAreas();
  const risk = useResult<{ areas: { area_key: string; score: number | null; n: number }[] }>("/risk");
  const yields = useResult<{
    table: { area_key: string; net_yield: number; n: number; sufficient: boolean }[];
  }>("/yield");

  const data = useMemo<CityDatum[]>(() => {
    if (!areas.data) return [];
    const riskByArea = new Map(risk.data?.areas.map((r) => [r.area_key, r]) ?? []);
    const yieldByArea = new Map<string, { value: number; n: number }>();
    for (const row of yields.data?.table ?? []) {
      if (!row.sufficient) continue;
      const existing = yieldByArea.get(row.area_key);
      // One figure per area on the map: the deepest cell, since it is the best supported.
      if (!existing || row.n > existing.n) {
        yieldByArea.set(row.area_key, { value: row.net_yield * 100, n: row.n });
      }
    }

    return areas.data.areas
      .filter((area) => area.has_location && area.lat !== null && area.lon !== null)
      .map((area) => {
        let value: number | null = null;
        let n = area.n_transactions;
        if (metric === "volume") value = area.n_transactions;
        else if (metric === "risk") {
          const row = riskByArea.get(area.area_key);
          value = row?.score ?? null;
          n = row?.n ?? n;
        } else if (metric === "yield") {
          const row = yieldByArea.get(area.area_key);
          value = row?.value ?? null;
          n = row?.n ?? n;
        } else {
          // Price per sqm is not on the area list, so it comes from the risk model's raw figures
          // where present and is otherwise left unset rather than guessed.
          value = area.n_transactions > 0 ? area.n_transactions : null;
        }
        return {
          area_key: area.area_key,
          name: area.name,
          lat: area.lat!,
          lon: area.lon!,
          value,
          n,
        };
      });
  }, [areas.data, risk.data, yields.data, metric]);

  const active = METRICS.find((m) => m.id === metric)!;
  const withoutLocation = areas.data?.without_location ?? 0;

  return (
    <>
      <PageHeader
        title={t("nav.city")}
        lede="Every community the registry records, extruded by the metric you choose. Hover a cell for its figures."
      />

      <div className="mb-4 space-y-3">
        <ProvenanceNotice provenance={market.data?.provenance} />
        <AdviceNotice compact />
      </div>

      {market.isLoading ? <Loading label={t("common.loading")} /> : null}
      {market.isError ? (
        <ErrorState message={(market.error as Error).message} onRetry={() => market.refetch()} />
      ) : null}

      {market.data ? (
        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {market.data.kpis.map((kpi) => (
            <KpiTile key={kpi.id} kpi={kpi} />
          ))}
        </div>
      ) : null}

      <Section title="The city" hint={active.hint}>
        <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Metric">
          {METRICS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setMetric(option.id)}
              aria-pressed={metric === option.id}
              className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                metric === option.id
                  ? "border-teal bg-sunken font-medium text-ink"
                  : "border-line text-ink-secondary hover:border-teal hover:text-teal-ink"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>

        {areas.isLoading ? (
          <Loading label={t("common.loading")} />
        ) : areas.isError ? (
          <ErrorState message={(areas.error as Error).message} onRetry={() => areas.refetch()} />
        ) : (
          <City3D
            data={data}
            unit={active.unit}
            selected={selected}
            onSelect={(key) => {
              setSelected(key);
              router.push(`/areas/${encodeURIComponent(key)}`);
            }}
          />
        )}

        {withoutLocation > 0 ? (
          <p className="mt-2 text-xs text-ink-muted">
            {withoutLocation} area{withoutLocation === 1 ? "" : "s"} in the registry have no mapped
            centroid and are not drawn. They are listed on the{" "}
            <a className="underline underline-offset-2 hover:text-teal-ink" href="/areas">
              areas page
            </a>{" "}
            rather than placed somewhere arbitrary.
          </p>
        ) : null}
      </Section>

      <Section title="Largest communities by recorded sales">
        <Card>
          <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
            {(areas.data?.areas ?? []).slice(0, 12).map((area) => (
              <li key={area.area_key}>
                <a
                  href={`/areas/${encodeURIComponent(area.area_key)}`}
                  className="flex items-baseline justify-between gap-2 rounded px-1 py-0.5 text-sm text-ink-secondary hover:bg-sunken hover:text-ink"
                >
                  <span className="truncate">{area.name}</span>
                  <span className="shrink-0 text-xs text-ink-muted">
                    {compactAed(area.n_transactions)}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </Card>
      </Section>
    </>
  );
}
