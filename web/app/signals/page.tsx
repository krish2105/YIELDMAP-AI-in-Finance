"use client";

import { Bars, DataTable } from "@/components/Charts";
import { AdviceNotice, ProvenanceNotice } from "@/components/Notices";
import { Card, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useResult } from "@/lib/hooks";
import { aed, dateLabel, percent } from "@/lib/format";

interface Anomalies {
  total_transactions: number;
  flagged: number;
  rate: number;
  by_rule: Record<string, number>;
  examples: {
    ts: string;
    area_key: string;
    price_aed: number;
    price_per_sqm: number;
    reasons: string;
  }[];
}

export default function SignalsPage() {
  const { t } = useShell();
  const anomalies = useResult<Anomalies>("/anomalies?limit=100");
  const risk = useResult<{ provenance: "REAL" | "SYNTHETIC" }>("/risk");

  // The header stays even when the data does not. Returning only an error box drops the page's
  // own title, so someone looking at it cannot tell which page failed — and leaves the document
  // with no h1 at all, which is both an accessibility fault and how the degraded-mode test found
  // this.
  if (anomalies.isLoading || anomalies.isError || !anomalies.data) {
    return (
      <>
        <PageHeader title={t("nav.signals")} />
        {anomalies.isError ? (
          <ErrorState
            message={(anomalies.error as Error).message}
            onRetry={() => anomalies.refetch()}
          />
        ) : (
          <Loading label={t("common.loading")} />
        )}
      </>
    );
  }

  const rules = Object.entries(anomalies.data.by_rule).map(([rule, count]) => ({
    x: rule,
    count,
  }));

  return (
    <>
      <PageHeader
        title={t("nav.signals")}
        lede="Transactions that do not look like their neighbours. Every flag names the rule that fired, because 'unusual' without a reason is not actionable."
      />
      <div className="mb-4 space-y-3">
        <ProvenanceNotice provenance={risk.data?.provenance} />
        <AdviceNotice compact />
      </div>

      <Section title="What is flagged">
        <div className="grid gap-3 lg:grid-cols-[16rem_1fr]">
          <Card>
            <p className="text-xs uppercase tracking-wide text-ink-muted">Flagged</p>
            <p className="mt-1 font-display text-3xl text-ink">
              {percent(anomalies.data.rate * 100)}
            </p>
            <p className="mt-1 text-xs text-ink-muted">
              {anomalies.data.flagged.toLocaleString()} of{" "}
              {anomalies.data.total_transactions.toLocaleString()} transactions
            </p>
          </Card>
          <Card>
            <Bars
              data={rules}
              series={[{ key: "count", label: "Transactions" }]}
              horizontal
              height={160}
            />
          </Card>
        </div>
        <p className="mt-2 text-xs text-ink-muted">
          Three independent rules. An isolation forest on price residuals against the area and type
          norm — not on raw prices, which would flag every large villa in an expensive area. A
          rapid-resale rule for properties changing hands within ninety days. And a round-number
          rule for prices landing exactly on a large round figure, which usually marks an agreed
          rather than a market price.
        </p>
      </Section>

      <Section title="The feed">
        <DataTable
          columns={[
            { key: "ts", label: "Date" },
            { key: "area_key", label: "Area" },
            { key: "price_aed", label: "Price", align: "right" },
            { key: "price_per_sqm", label: "AED/sqm", align: "right" },
            { key: "reasons", label: "Why it was flagged" },
          ]}
          rows={anomalies.data.examples.map((row) => ({
            ts: dateLabel(row.ts),
            area_key: row.area_key,
            price_aed: aed(row.price_aed),
            price_per_sqm: Math.round(row.price_per_sqm).toLocaleString(),
            reasons: row.reasons,
          }))}
          caption="A flag is a prompt to look, not a finding of wrongdoing."
        />
      </Section>
    </>
  );
}
