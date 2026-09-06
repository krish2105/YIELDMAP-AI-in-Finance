"use client";

import Link from "next/link";
import { useState } from "react";

import { ProvenanceNotice } from "@/components/Notices";
import { Card, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useAreas } from "@/lib/hooks";
import { count } from "@/lib/format";

export default function AreasPage() {
  const { t } = useShell();
  const [query, setQuery] = useState("");
  const areas = useAreas();

  const rows = (areas.data?.areas ?? []).filter((area) =>
    `${area.name} ${area.dld_name}`.toLowerCase().includes(query.trim().toLowerCase()),
  );
  const unmapped = rows.filter((area) => !area.has_location);

  return (
    <>
      <PageHeader
        title={t("nav.areas")}
        lede="Every community the registry names, with the official DLD sector name beside the one people use."
      />
      <div className="mb-4">
        <ProvenanceNotice provenance={areas.data?.provenance as "REAL" | "SYNTHETIC" | undefined} />
      </div>

      <label className="mb-4 block max-w-sm">
        <span className="sr-only">{t("common.search")}</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("common.search")}
          className="w-full rounded-lg border border-line bg-raised px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-muted focus:border-teal"
        />
      </label>

      {areas.isLoading ? <Loading label={t("common.loading")} /> : null}
      {areas.isError ? (
        <ErrorState message={(areas.error as Error).message} onRetry={() => areas.refetch()} />
      ) : null}

      {areas.data ? (
        <Section title={`${rows.length} communities`}>
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-sm">
              <thead className="bg-sunken text-xs">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-medium text-ink-secondary">
                    Community
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium text-ink-secondary">
                    DLD sector name
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium text-ink-secondary">
                    Sales
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium text-ink-secondary">
                    Location
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((area) => (
                  <tr key={area.area_key} className="border-t border-line hover:bg-sunken">
                    <td className="px-3 py-1.5">
                      <Link
                        href={`/areas/${encodeURIComponent(area.area_key)}`}
                        className="text-ink hover:text-teal-ink hover:underline"
                      >
                        {area.name}
                      </Link>
                    </td>
                    <td className="px-3 py-1.5 text-xs text-ink-muted">{area.dld_name}</td>
                    <td className="px-3 py-1.5 text-right text-ink-secondary">
                      {count(area.n_transactions)}
                    </td>
                    <td className="px-3 py-1.5 text-xs">
                      {area.has_location ? (
                        <span className="text-ink-muted">
                          {area.coord_confidence ?? "mapped"}
                        </span>
                      ) : (
                        <span style={{ color: "var(--warn-ink)" }}>no centroid</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {unmapped.length ? (
            <Card className="mt-4">
              <p className="text-xs text-ink-secondary">
                <strong className="font-medium text-ink">
                  {unmapped.length} area{unmapped.length === 1 ? "" : "s"} have no mapped centroid.
                </strong>{" "}
                They are listed here with their figures intact rather than drawn at an arbitrary
                point on the map. No open source of Dubai community boundaries was reachable, so
                coordinates are curated per sector and gaps are shown rather than filled.
              </p>
            </Card>
          ) : null}
        </Section>
      ) : null}
    </>
  );
}
