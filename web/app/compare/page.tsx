"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { DataTable, TimeSeries } from "@/components/Charts";
import { AdviceNotice } from "@/components/Notices";
import { Card, Empty, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useAreas } from "@/lib/hooks";
import { api, type AreaDetail } from "@/lib/api";
import { compactAed, monthLabel } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";
import { formatKpi, isSuppressed } from "@/lib/kpi";

const MAX = 6;

function CompareInner() {
  const { t } = useShell();
  const search = useSearchParams();
  const initial = search.getAll("areas").filter(Boolean);
  const [picked, setPicked] = useState<string[]>(initial);
  const areas = useAreas();

  const query = useQuery({
    queryKey: ["compare", picked.join("|")],
    queryFn: () =>
      api.get<{ areas: { area_key: string; found: boolean; kpis: AreaDetail["kpis"]; series: AreaDetail["series"] | null }[] }>(
        `/compare?${picked.map((a) => `areas=${encodeURIComponent(a)}`).join("&")}`,
      ),
    enabled: picked.length > 0,
  });

  const chart = useMemo(() => {
    const found = (query.data?.areas ?? []).filter((a) => a.found && a.series);
    if (!found.length) return { rows: [], series: [] };
    const months = new Map<string, Record<string, unknown>>();
    for (const area of found) {
      for (const point of area.series!.points) {
        const label = monthLabel(point.month);
        const row = months.get(label) ?? { x: label };
        row[area.area_key] = point.median_ppsqm;
        months.set(label, row);
      }
    }
    return {
      rows: [...months.values()],
      series: found.map((area) => ({ key: area.area_key, label: area.area_key })),
    };
  }, [query.data]);

  const toggle = (key: string) =>
    setPicked((current) =>
      current.includes(key)
        ? current.filter((item) => item !== key)
        : current.length >= MAX
          ? current
          : [...current, key],
    );

  // The KPI labels present across every compared area, so the table has stable rows.
  const labels = useMemo(() => {
    const found = (query.data?.areas ?? []).filter((a) => a.found);
    const seen: string[] = [];
    for (const area of found) {
      for (const kpi of area.kpis) if (!seen.includes(kpi.label)) seen.push(kpi.label);
    }
    return seen;
  }, [query.data]);

  return (
    <>
      <PageHeader
        title={t("nav.compare")}
        lede={`Up to ${MAX} communities side by side, on identical measures. More than that and the chart stops being readable.`}
      />
      <div className="mb-4">
        <AdviceNotice compact />
      </div>

      <Section title="Choose communities" hint={`${picked.length} of ${MAX} selected`}>
        <Card>
          <div className="flex max-h-52 flex-wrap gap-1.5 overflow-y-auto">
            {(areas.data?.areas ?? []).slice(0, 60).map((area) => {
              const on = picked.includes(area.area_key);
              const full = picked.length >= MAX && !on;
              return (
                <button
                  key={area.area_key}
                  type="button"
                  onClick={() => toggle(area.area_key)}
                  disabled={full}
                  aria-pressed={on}
                  className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                    on
                      ? "border-teal bg-sunken font-medium text-ink"
                      : full
                        ? "cursor-not-allowed border-line text-ink-muted opacity-50"
                        : "border-line text-ink-secondary hover:border-teal hover:text-teal-ink"
                  }`}
                >
                  {area.name}
                </button>
              );
            })}
          </div>
        </Card>
      </Section>

      {picked.length === 0 ? (
        <Empty message="Pick at least one community above." />
      ) : query.isLoading ? (
        <Loading label={t("common.loading")} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : (
        <>
          <Section title="Median price per square metre">
            <Card>
              {chart.rows.length ? (
                <TimeSeries
                  data={chart.rows}
                  series={chart.series}
                  yFormatter={compactAed}
                  valueFormatter={(value) => `${compactAed(value)} AED`}
                  height={300}
                />
              ) : (
                <Empty message="None of the selected communities has a plottable series." />
              )}
            </Card>
          </Section>

          <Section title="Side by side">
            <DataTable
              columns={[
                { key: "measure", label: "Measure" },
                ...(query.data?.areas ?? [])
                  .filter((a) => a.found)
                  .map((a) => ({ key: a.area_key, label: a.area_key, align: "right" as const })),
              ]}
              rows={labels.map((label) => {
                const row: Record<string, unknown> = { measure: label };
                for (const area of query.data?.areas ?? []) {
                  if (!area.found) continue;
                  const kpi = area.kpis.find((k) => k.label === label);
                  row[area.area_key] = kpi
                    ? isSuppressed(kpi)
                      ? "insufficient"
                      : `${formatKpi(kpi)} (n=${kpi.n.toLocaleString()})`
                    : "—";
                }
                return row;
              })}
            />
          </Section>

          {(query.data?.areas ?? []).some((a) => !a.found) ? (
            <p className="text-xs" style={{ color: "var(--warn-ink)" }}>
              No recent transactions for:{" "}
              {(query.data?.areas ?? [])
                .filter((a) => !a.found)
                .map((a) => a.area_key)
                .join(", ")}
            </p>
          ) : null}
        </>
      )}
    </>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<Loading label="Loading" />}>
      <CompareInner />
    </Suspense>
  );
}
