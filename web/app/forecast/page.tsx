"use client";

import { DataTable, Dots } from "@/components/Charts";
import { AdviceNotice, ProvenanceNotice } from "@/components/Notices";
import { Card, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useResult } from "@/lib/hooks";
import { percent } from "@/lib/format";

interface ForecastPayload {
  provenance: "REAL" | "SYNTHETIC";
  method: string;
  benchmark: string;
  horizon_months: number;
  summary: {
    areas_forecast: number;
    areas_skipped: number;
    areas_compared: number;
    areas_beating_naive: number;
    win_rate: number | null;
    median_model_mape: number | null;
    median_naive_mape: number | null;
  };
  skipped: { area_key: string; n_months: number; reason: string }[];
  areas: {
    area_key: string;
    backtest_mape: number | null;
    naive_mape: number | null;
    beats_naive: boolean | null;
  }[];
}

export default function ForecastPage() {
  const { t } = useShell();
  const forecast = useResult<ForecastPayload>("/forecast");

  // The header stays even when the data does not. Returning only an error box drops the page's
  // own title, so someone looking at it cannot tell which page failed — and leaves the document
  // with no h1 at all, which is both an accessibility fault and how the degraded-mode test found
  // this.
  if (forecast.isLoading || forecast.isError || !forecast.data) {
    return (
      <>
        <PageHeader title={t("nav.forecast")} />
        {forecast.isError ? (
          <ErrorState
            message={(forecast.error as Error).message}
            onRetry={() => forecast.refetch()}
          />
        ) : (
          <Loading label={t("common.loading")} />
        )}
      </>
    );
  }

  const { summary, areas, skipped } = forecast.data;
  const scatter = areas
    .filter((area) => area.backtest_mape !== null && area.naive_mape !== null)
    .map((area) => ({
      area: area.area_key,
      naive: Number((area.naive_mape! * 100).toFixed(2)),
      model: Number((area.backtest_mape! * 100).toFixed(2)),
    }));

  return (
    <>
      <PageHeader
        title={t("nav.forecast")}
        lede="Any model can draw a line past the end of a chart. The question is whether it beats the cheapest sensible alternative."
      />
      <div className="mb-4 space-y-3">
        <ProvenanceNotice provenance={forecast.data.provenance} />
        <AdviceNotice />
      </div>

      <Section title="Against the benchmark" hint={forecast.data.benchmark}>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[
            ["Areas forecast", String(summary.areas_forecast)],
            [
              "Beat the benchmark",
              summary.win_rate !== null
                ? `${summary.areas_beating_naive}/${summary.areas_compared} (${percent(summary.win_rate * 100, 0)})`
                : "—",
            ],
            [
              "Median model error",
              summary.median_model_mape !== null ? percent(summary.median_model_mape * 100, 1) : "—",
            ],
            [
              "Median benchmark error",
              summary.median_naive_mape !== null ? percent(summary.median_naive_mape * 100, 1) : "—",
            ],
          ].map(([label, value]) => (
            <Card key={label}>
              <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
              <p className="mt-1 font-display text-2xl text-ink">{value}</p>
            </Card>
          ))}
        </div>
        <p className="mt-2 text-xs text-ink-muted">
          The plan&rsquo;s target was to beat the benchmark on at least 60% of areas.{" "}
          {summary.win_rate !== null && summary.win_rate >= 0.6
            ? "That target is met."
            : "That target is not currently met."}
        </p>
      </Section>

      <Section
        title="Every area, model error against benchmark error"
        hint="A point below the diagonal is an area where the model beat the benchmark."
      >
        <Card>
          <Dots
            data={scatter}
            xKey="naive"
            yKey="model"
            xLabel="Seasonal naive error (%)"
            yLabel="Model error (%)"
            diagonal
            height={360}
          />
        </Card>
      </Section>

      <Section title="Where it lost">
        <DataTable
          columns={[
            { key: "area", label: "Area" },
            { key: "model", label: "Model error", align: "right" },
            { key: "naive", label: "Benchmark error", align: "right" },
          ]}
          rows={areas
            .filter((area) => area.beats_naive === false)
            .map((area) => ({
              area: area.area_key,
              model: percent((area.backtest_mape ?? 0) * 100, 1),
              naive: percent((area.naive_mape ?? 0) * 100, 1),
            }))}
          caption="In these areas the naive benchmark did better, so the projection deserves less weight."
        />
      </Section>

      {skipped.length ? (
        <Section title="Areas that got no forecast at all">
          <Card>
            <p className="mb-2 text-xs text-ink-secondary">
              A projection from a handful of observations is decoration. These areas were refused
              rather than given a line.
            </p>
            <ul className="grid gap-x-6 gap-y-1 text-xs text-ink-muted sm:grid-cols-2 lg:grid-cols-3">
              {skipped.map((area) => (
                <li key={area.area_key}>
                  {area.area_key} — {area.n_months} months
                </li>
              ))}
            </ul>
          </Card>
        </Section>
      ) : null}
    </>
  );
}
