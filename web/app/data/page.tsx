"use client";

import { DataTable } from "@/components/Charts";
import { ProvenanceNotice } from "@/components/Notices";
import { Card, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useResult } from "@/lib/hooks";
import { dateLabel } from "@/lib/format";

interface Freshness {
  tables: {
    table_name: string;
    rows: number;
    as_of: string | null;
    provenance: "REAL" | "SYNTHETIC";
    source_sha256: string | null;
    refreshed_at: string;
  }[];
  sql: string;
  provenance: "REAL" | "SYNTHETIC";
  warning: string | null;
}

export default function DataPage() {
  const { t } = useShell();
  const freshness = useResult<Freshness>("/data/freshness");

  if (freshness.isLoading) return <Loading label={t("common.loading")} />;
  if (freshness.isError) {
    return <ErrorState message={(freshness.error as Error).message} onRetry={() => freshness.refetch()} />;
  }
  if (!freshness.data) return null;

  return (
    <>
      <PageHeader
        title={t("nav.data")}
        lede="What is loaded, how much of it, as of when, and where it came from."
      />
      <div className="mb-4">
        <ProvenanceNotice provenance={freshness.data.provenance} />
      </div>

      <Section title="Loaded tables">
        <DataTable
          columns={[
            { key: "table_name", label: "Table" },
            { key: "rows", label: "Rows", align: "right" },
            { key: "as_of", label: "Latest record" },
            { key: "provenance", label: "Provenance" },
            { key: "source_sha256", label: "Source hash" },
          ]}
          rows={freshness.data.tables.map((row) => ({
            table_name: row.table_name,
            rows: row.rows.toLocaleString(),
            as_of: row.as_of ? dateLabel(row.as_of) : "—",
            provenance: row.provenance,
            source_sha256: row.source_sha256 ? row.source_sha256.slice(0, 12) : "—",
          }))}
        />
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-ink-muted hover:text-ink">
            The query behind this table
          </summary>
          <pre className="mt-2 overflow-auto rounded-lg bg-sunken p-3 font-mono text-[11px] text-ink-secondary">
            <code>{freshness.data.sql}</code>
          </pre>
        </details>
      </Section>

      <Section title="How data reaches this project">
        <Card>
          <p className="text-sm text-ink-secondary">
            The Dubai Land Department publishes its registry as open data. Downloads run inside a
            GitHub Actions job rather than from a developer machine, because this project&rsquo;s
            sandbox cannot reach any government domain.
          </p>
          <ol className="mt-3 space-y-2 text-sm text-ink-secondary">
            <li>
              <strong className="font-medium text-ink">1. Automated download.</strong> The ingest
              job probes every candidate source and publishes a reachability table. Driving the
              open-data page in a real browser established that its dataset tabs fetch through the
              site&rsquo;s own API and that bulk files are published only on Dubai Pulse, which
              refuses connections from automated clients.
            </li>
            <li>
              <strong className="font-medium text-ink">2. Operator upload.</strong> The same
              published files, downloaded through an ordinary browser and attached to a release.
              This is the correct route to real data, not a workaround.
            </li>
            <li>
              <strong className="font-medium text-ink">3. Labelled stand-in.</strong> Generated rows
              with realistic structure and invented levels, used to exercise the pipeline. Every row
              is stamped, results are written to a separate directory, and a guard blocks them from
              reaching any graded artefact.
            </li>
          </ol>
          {freshness.data.warning ? (
            <p className="mt-3 text-xs" style={{ color: "var(--sand)" }}>
              {freshness.data.warning}
            </p>
          ) : null}
        </Card>
      </Section>

      <Section title="What the data does not contain">
        <Card>
          <ul className="space-y-1.5 text-sm text-ink-secondary">
            <li>
              · Older rows carry no stable unit identifier, so repeat-sale pairs fall back to
              building, bedroom count and floor area.
            </li>
            <li>
              · Tenancies are recorded but the gaps between them are not, so vacancy cannot be
              measured and has to be assumed.
            </li>
            <li>
              · Service charges are not in the open registry. A single estimate stands in for
              per-building figures, and it is the largest source of error in any net yield here.
            </li>
            <li>
              · Community boundaries are not published under an open licence anywhere reachable, so
              the map uses curated centroids and says so.
            </li>
          </ul>
        </Card>
      </Section>
    </>
  );
}
