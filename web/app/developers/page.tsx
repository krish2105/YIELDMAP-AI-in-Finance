"use client";

import { DataTable } from "@/components/DataTable";
import { AdviceNotice, ProvenanceNotice } from "@/components/Notices";
import { Card, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useResult } from "@/lib/hooks";
import { aed, percent } from "@/lib/format";

interface Developers {
  provenance: "REAL" | "SYNTHETIC";
  premium_definition: string;
  limitation: string;
  min_transactions: number;
  summary: {
    developers: number;
    median_premium_pct: number | null;
    above_their_areas: number;
    below_their_areas: number;
  };
  league: {
    project_name: string;
    n: number;
    areas: number;
    median_price: number;
    premium_pct: number;
    offplan_share: number;
    years_active: number;
    sales_per_year: number;
    verdict: string;
  }[];
}

export default function DevelopersPage() {
  const { t } = useShell();
  const developers = useResult<Developers>("/developers");

  // The header stays even when the data does not. Returning only an error box drops the page's
  // own title, so someone looking at it cannot tell which page failed — and leaves the document
  // with no h1 at all, which is both an accessibility fault and how the degraded-mode test found
  // this.
  if (developers.isLoading || developers.isError || !developers.data) {
    return (
      <>
        <PageHeader title={t("nav.developers")} />
        {developers.isError ? (
          <ErrorState
            message={(developers.error as Error).message}
            onRetry={() => developers.refetch()}
          />
        ) : (
          <Loading label={t("common.loading")} />
        )}
      </>
    );
  }

  const { summary, league } = developers.data;

  return (
    <>
      <PageHeader
        title={t("nav.developers")}
        lede="Whether a developer's stock holds its value, measured against the same areas at the same time rather than against the market as a whole."
      />
      <div className="mb-4 space-y-3">
        <ProvenanceNotice provenance={developers.data.provenance} />
        <AdviceNotice compact />
      </div>

      <Section title="The measure" hint={developers.data.premium_definition}>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[
            ["Projects ranked", String(summary.developers)],
            [
              "Median premium",
              summary.median_premium_pct !== null
                ? `${summary.median_premium_pct >= 0 ? "+" : ""}${summary.median_premium_pct.toFixed(1)}%`
                : "—",
            ],
            ["Above their areas", String(summary.above_their_areas)],
            ["Below their areas", String(summary.below_their_areas)],
          ].map(([label, value]) => (
            <Card key={label}>
              <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
              <p className="mt-1 font-display text-2xl text-ink">{value}</p>
            </Card>
          ))}
        </div>
        <p className="mt-2 text-xs" style={{ color: "var(--warn-ink)" }}>
          Limitation: {developers.data.limitation}.
        </p>
      </Section>

      <Section title="The league table">
        <DataTable
          columns={[
            { key: "project_name", label: "Project" },
            { key: "n", label: "Sales", align: "right" },
            { key: "areas", label: "Areas", align: "right" },
            { key: "median_price", label: "Median price", align: "right" },
            { key: "premium_pct", label: "Premium", align: "right" },
            { key: "offplan_share", label: "Off-plan", align: "right" },
            { key: "verdict", label: "Verdict" },
          ]}
          rows={league.slice(0, 60).map((row) => ({
            project_name: row.project_name,
            n: row.n.toLocaleString(),
            areas: row.areas,
            median_price: aed(row.median_price),
            premium_pct: `${row.premium_pct >= 0 ? "+" : ""}${row.premium_pct.toFixed(1)}%`,
            offplan_share: percent(row.offplan_share * 100, 0),
            verdict: row.verdict,
          }))}
          caption={`Projects with at least ${developers.data.min_transactions} recorded sales.`}
        />
      </Section>
    </>
  );
}
