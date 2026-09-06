"use client";

import Link from "next/link";

import { Card, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useResult } from "@/lib/hooks";
import { percent } from "@/lib/format";

export default function ReportPage() {
  const { t } = useShell();
  const hedonic = useResult<{ metrics: { test: { mape: number }; baseline: { mape: number }; skill_vs_baseline: number } }>("/hedonic");
  const forecast = useResult<{ summary: { win_rate: number | null; areas_compared: number } }>("/forecast");
  const evals = useResult<{ recall_at_k: number; faithfulness: number }>("/evals");

  return (
    <>
      <PageHeader
        title={t("nav.report")}
        lede="What this project set out to do, what it measured, and what it does not know."
      />

      <Section title="The problem">
        <Card>
          <p className="text-sm text-ink-secondary">
            Dubai&rsquo;s property registry is public, unit-level and daily. Every sale and every
            registered tenancy is recorded. Yet buyers, tenants and small investors still decide
            from broker claims and portal listings, because nothing turns that registry into a
            valuation, a yield, a risk score and a plain-language explanation that can be checked.
          </p>
          <p className="mt-2 text-sm text-ink-secondary">
            YIELDMAP does that, and its distinguishing property is that every number it shows can be
            traced back to the query that produced it. That is not a promise in a document — a
            figure cannot leave the API without carrying its own SQL, and a test at the boundary
            fails if one does.
          </p>
        </Card>
      </Section>

      <Section title="What was measured">
        <Card>
          <ul className="space-y-2 text-sm text-ink-secondary">
            <li>
              <strong className="font-medium text-ink">Valuation.</strong>{" "}
              {hedonic.data
                ? `${percent(hedonic.data.metrics.test.mape * 100, 1)} error on a time-split holdout, against ${percent(hedonic.data.metrics.baseline.mape * 100, 1)} for a cell-median baseline — a ${percent(hedonic.data.metrics.skill_vs_baseline * 100, 0)} reduction.`
                : "not yet computed."}
            </li>
            <li>
              <strong className="font-medium text-ink">Forecast.</strong>{" "}
              {forecast.data?.summary.win_rate !== null && forecast.data
                ? `Beats a seasonal naive benchmark on ${percent(forecast.data.summary.win_rate! * 100, 0)} of ${forecast.data.summary.areas_compared} areas, against a 60% target.`
                : "not yet computed."}
            </li>
            <li>
              <strong className="font-medium text-ink">Retrieval.</strong>{" "}
              {evals.data
                ? `Recall ${percent(evals.data.recall_at_k * 100, 0)} and faithfulness ${percent(evals.data.faithfulness * 100, 0)} across thirty cases in three languages.`
                : "not yet computed."}
            </li>
            <li>
              <strong className="font-medium text-ink">Cost.</strong> Zero. Every model backend in
              the chain is a free tier, the paid one is off behind two switches, and requests are
              counted in a durable ledger.
            </li>
          </ul>
        </Card>
      </Section>

      <Section title="What it does not know">
        <Card>
          <ul className="space-y-1.5 text-sm text-ink-secondary">
            <li>· Service charges are an estimate, and they are the largest input to any net yield here.</li>
            <li>· Vacancy cannot be measured from the open data at all, so it is assumed.</li>
            <li>· Lending caps are carried as assumptions because the Central Bank site refuses automated clients.</li>
            <li>· Yields use medians for a community and unit type, not the rent of a specific unit.</li>
            <li>· Community shapes are curated centroids rendered as hex cells, not boundaries.</li>
            <li>· Forecasts are projections under stated assumptions. Nothing here is advice.</li>
          </ul>
        </Card>
      </Section>

      <Section title="Read further">
        <Card>
          <ul className="space-y-1.5 text-sm">
            {[
              { href: "/methodology", label: "Every measure, defined" },
              { href: "/models", label: "Model cards and how each was tested" },
              { href: "/evals", label: "Retrieval scores, by language" },
              { href: "/security", label: "What agents may do, and what stops them" },
              { href: "/data", label: "What is loaded and where it came from" },
            ].map(({ href, label }) => (
              <li key={href}>
                <Link
                  href={href}
                  className="text-ink-secondary underline decoration-line underline-offset-2 hover:text-teal-ink"
                >
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      </Section>
    </>
  );
}
