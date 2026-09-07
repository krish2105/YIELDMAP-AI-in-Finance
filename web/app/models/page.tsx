"use client";

import { Bars, DataTable } from "@/components/Charts";
import { ProvenanceNotice } from "@/components/Notices";
import { Card, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useResult } from "@/lib/hooks";
import { percent } from "@/lib/format";

interface Hedonic {
  n_train: number;
  n_test: number;
  train_period: [string, string];
  test_period: [string, string];
  test: { mape: number; median_ape: number; mae_ppsqm: number; bias: number };
  baseline: { method: string; mape: number };
  skill_vs_baseline: number;
  estimated_noise_floor_mape: number;
  importance: { feature: string; importance: number; std: number }[];
}

interface IndexPayload {
  provenance: "REAL" | "SYNTHETIC";
  method: string;
  identity: string;
  weighting: string;
  diagnostics: Record<string, number | null>;
  annual: { year: number; index: number; growth: number | null; n_pairs: number }[];
  // Absent on older result files, which is why the check below treats undefined as estimated.
  estimated?: boolean;
  reason?: string;
  note?: string;
  n_pairs?: number;
}

export default function ModelsPage() {
  const { t } = useShell();
  const hedonic = useResult<{
    metrics: Hedonic;
    provenance: "REAL" | "SYNTHETIC";
    target: string;
    holdout: string;
    // Absent on older result files, so undefined means estimated.
    estimated?: boolean;
    reason?: string;
    note?: string;
    n_rows?: number;
  }>("/hedonic");
  const index = useResult<IndexPayload>("/index");

  // The header stays even when the data does not. Returning only an error box drops the page's
  // own title, so someone looking at it cannot tell which page failed — and leaves the document
  // with no h1 at all, which is both an accessibility fault and how the degraded-mode test found
  // this.
  if (hedonic.isLoading || hedonic.isError || !hedonic.data) {
    return (
      <>
        <PageHeader title={t("nav.models")} />
        {hedonic.isError ? (
          <ErrorState
            message={(hedonic.error as Error).message}
            onRetry={() => hedonic.refetch()}
          />
        ) : (
          <Loading label={t("common.loading")} />
        )}
      </>
    );
  }

  // A drop too short to hold out a final year cannot be scored, and the result says so rather
  // than shipping empty metrics that would render as NaN across the page.
  if (hedonic.data.estimated === false) {
    return (
      <>
        <PageHeader title={t("nav.models")} />
        <ProvenanceNotice provenance={hedonic.data.provenance} />
        <Section title="Valuation" hint={hedonic.data.target}>
          <Card>
            <p className="text-sm text-ink-secondary">{hedonic.data.note}</p>
            <p className="mt-2 text-xs" style={{ color: "var(--warn-ink)" }}>
              {hedonic.data.reason}
            </p>
            <p className="mt-2 text-xs text-ink-muted">
              {(hedonic.data.n_rows ?? 0).toLocaleString()} rows available
            </p>
          </Card>
        </Section>
      </>
    );
  }

  const m = hedonic.data.metrics;

  return (
    <>
      <PageHeader
        title={t("nav.models")}
        lede="Model cards. What each model is for, how it was tested, and how well it did against something it had to beat."
      />
      <div className="mb-4">
        <ProvenanceNotice provenance={hedonic.data.provenance} />
      </div>

      <Section title="Valuation" hint={hedonic.data.target}>
        <Card>
          <p className="mb-3 text-sm text-ink-secondary">
            Trained on {m.n_train.toLocaleString()} sales from {m.train_period[0]} to{" "}
            {m.train_period[1]}, and tested on {m.n_test.toLocaleString()} sales from{" "}
            {m.test_period[0]} to {m.test_period[1]}. {hedonic.data.holdout}.
          </p>

          <Bars
            data={[
              { x: "Cell-median baseline", error: Number((m.baseline.mape * 100).toFixed(1)) },
              { x: "Hedonic model", error: Number((m.test.mape * 100).toFixed(1)) },
              { x: "Estimated noise floor", error: Number((m.estimated_noise_floor_mape * 100).toFixed(1)) },
            ]}
            series={[{ key: "error", label: "Mean absolute percentage error" }]}
            yFormatter={(value) => `${value}%`}
            valueFormatter={(value) => `${value.toFixed(1)}%`}
            height={220}
          />

          <p className="mt-2 text-xs text-ink-secondary">
            An error figure alone says nothing. It is shown against what a careful person with a
            spreadsheet would achieve — the median price per square metre for the same area, type
            and bedroom count — and against an estimate of the data&rsquo;s own irreducible scatter.
            The model reduces the baseline&rsquo;s error by {percent(m.skill_vs_baseline * 100, 0)} and
            sits close to the floor, which means it is extracting most of the signal that is there.
          </p>

          <div className="mt-4">
            <h3 className="mb-2 text-sm font-medium text-ink">What the model relies on</h3>
            <Bars
              data={m.importance.map((row) => ({ x: row.feature, importance: Number(row.importance.toFixed(4)) }))}
              series={[{ key: "importance", label: "Permutation importance" }]}
              horizontal
              height={200}
            />
            <p className="mt-1 text-xs text-ink-muted">
              Measured by shuffling each feature on the holdout and seeing how much worse the model
              gets — so this is what it actually uses, not what it was given.
            </p>
          </div>
        </Card>
      </Section>

      {index.data && index.data.estimated === false ? (
        <Section title="Price index" hint={index.data.method}>
          <Card>
            <p className="text-sm text-ink-secondary">{index.data.note}</p>
            <p className="mt-2 text-xs" style={{ color: "var(--warn-ink)" }}>
              {index.data.reason}
            </p>
            <p className="mt-2 text-xs text-ink-muted">
              {(index.data.n_pairs ?? 0).toLocaleString()} repeat pairs found
            </p>
          </Card>
        </Section>
      ) : index.data ? (
        <Section title="Price index" hint={index.data.method}>
          <Card>
            <p className="mb-3 text-sm text-ink-secondary">
              A median moves when the mix of what sold changes, not only when prices change.
              Comparing each property against itself cancels that out. Identity here is{" "}
              {index.data.identity}. Pairs are weighted by {index.data.weighting}.
            </p>
            <DataTable
              columns={[
                { key: "year", label: "Year" },
                { key: "index", label: "Index", align: "right" },
                { key: "growth", label: "Change", align: "right" },
                { key: "n_pairs", label: "Pairs", align: "right" },
              ]}
              rows={index.data.annual.map((row) => ({
                year: row.year,
                index: row.index.toFixed(1),
                growth: row.growth === null ? "—" : `${row.growth >= 0 ? "+" : ""}${(row.growth * 100).toFixed(1)}%`,
                n_pairs: row.n_pairs.toLocaleString(),
              }))}
            />
            <dl className="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
              {Object.entries(index.data.diagnostics).map(([key, value]) => (
                <div key={key}>
                  <dt className="text-ink-muted">{key.replace(/_/g, " ")}</dt>
                  <dd className="text-ink">
                    {value === null ? "—" : typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : String(value)}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-2 text-xs text-ink-muted">
              A repeat-sales index is only identified within a connected set of periods. Periods
              that share no repeat sale with the rest are dropped and counted here rather than
              being given a level the data cannot support.
            </p>
          </Card>
        </Section>
      ) : null}
    </>
  );
}
