"use client";

import { use } from "react";
import Link from "next/link";

import { Bars, DataTable, TimeSeries } from "@/components/Charts";
import KpiTile from "@/components/KpiTile";
import { AdviceNotice, ProvenanceNotice } from "@/components/Notices";
import { Card, Empty, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useArea } from "@/lib/hooks";
import { compactAed, monthLabel, percent } from "@/lib/format";

export default function AreaPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = use(params);
  const areaKey = decodeURIComponent(key);
  const { t } = useShell();
  const area = useArea(areaKey);

  if (area.isLoading) return <Loading label={t("common.loading")} />;
  if (area.isError) {
    return (
      <>
        <PageHeader title={areaKey} />
        <ErrorState message={(area.error as Error).message} onRetry={() => area.refetch()} />
      </>
    );
  }
  if (!area.data) return <Empty message={t("common.none")} />;

  const { kpis, series, risk, forecast, provenance } = area.data;
  const points = series.points.map((point) => ({
    x: monthLabel(point.month),
    ppsqm: point.median_ppsqm,
    n: point.n,
  }));
  const spark = series.points.slice(-24).map((point) => point.median_ppsqm);

  const components = risk?.components
    ? Object.entries(risk.components)
        .filter(([, value]) => value !== null)
        .map(([name, value]) => ({ x: name.replace(/_/g, " "), score: value as number }))
    : [];

  return (
    <>
      <PageHeader
        title={areaKey}
        lede="Everything the registry records for this community, and what the models make of it."
        actions={
          <Link
            href={`/compare?areas=${encodeURIComponent(areaKey)}`}
            className="rounded-lg border border-line px-3 py-1.5 text-xs text-ink-secondary hover:border-teal hover:text-teal-ink"
          >
            Compare with another
          </Link>
        }
      />

      <div className="mb-4 space-y-3">
        <ProvenanceNotice provenance={provenance} />
        <AdviceNotice compact />
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {kpis.map((kpi, i) => (
          <KpiTile key={kpi.id} kpi={kpi} spark={i === 0 ? spark : undefined} />
        ))}
      </div>

      <Section
        title="Median price per square metre"
        hint="Monthly, from every recorded sale. Months with fewer than three sales are not plotted."
      >
        <Card>
          {points.length ? (
            <>
              <TimeSeries
                data={points}
                series={[{ key: "ppsqm", label: "Median AED/sqm" }]}
                yFormatter={compactAed}
                valueFormatter={(value) => `${compactAed(value)} AED`}
              />
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-ink-muted hover:text-ink">
                  View as a table
                </summary>
                <div className="mt-2">
                  <DataTable
                    columns={[
                      { key: "x", label: "Month" },
                      { key: "ppsqm", label: "AED/sqm", align: "right" },
                      { key: "n", label: "Sales", align: "right" },
                    ]}
                    rows={points.slice(-24).map((point) => ({
                      ...point,
                      ppsqm: Math.round(point.ppsqm).toLocaleString(),
                    }))}
                  />
                </div>
              </details>
            </>
          ) : (
            <Empty message="No month in this area has enough sales to plot." />
          )}
        </Card>
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Risk" hint="A judgement, not a measurement. The weights are published.">
          <Card>
            {risk?.score !== null && risk?.score !== undefined ? (
              <>
                <p className="mb-3 font-display text-3xl text-ink">
                  {risk.score.toFixed(0)}
                  <span className="ml-1 text-base text-ink-muted">/ 100</span>
                </p>
                <Bars
                  data={components}
                  series={[{ key: "score", label: "Component" }]}
                  horizontal
                  height={180}
                />
              </>
            ) : (
              <Empty message={risk?.reason ?? "No risk score for this area."} />
            )}
          </Card>
        </Section>

        <Section
          title="Forecast"
          hint="Twelve months ahead, scored against a seasonal naive benchmark."
        >
          <Card>
            {forecast ? (
              <>
                <dl className="mb-3 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-xs text-ink-muted">Model error</dt>
                    <dd className="text-ink">
                      {forecast.backtest_mape !== null
                        ? percent(forecast.backtest_mape * 100, 1)
                        : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">Benchmark error</dt>
                    <dd className="text-ink">
                      {forecast.naive_mape !== null ? percent(forecast.naive_mape * 100, 1) : "—"}
                    </dd>
                  </div>
                </dl>
                <p
                  className="rounded-lg px-3 py-2 text-xs"
                  style={{
                    background: "var(--bg-sunken)",
                    color: forecast.beats_naive ? "var(--teal-ink)" : "var(--sand)",
                  }}
                >
                  {forecast.beats_naive
                    ? "The model beat the naive benchmark here, so the projection carries some weight."
                    : "The model did not beat a naive benchmark here. Treat its projection with caution."}
                </p>
              </>
            ) : (
              <Empty message="Not enough history in this area to forecast." />
            )}
          </Card>
        </Section>
      </div>
    </>
  );
}
