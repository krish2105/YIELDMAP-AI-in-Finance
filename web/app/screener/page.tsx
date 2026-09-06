"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { AdviceNotice, ProvenanceNotice } from "@/components/Notices";
import { Card, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useScreener } from "@/lib/hooks";
import { aed, compactAed, count, percent } from "@/lib/format";
import { confidenceFor } from "@/lib/kpi";
import { CONFIDENCE } from "@/lib/theme";

type SortKey = "n" | "median_price" | "median_ppsqm" | "offplan_share";

// The bounds the API declares on /screener's min_sales (Query(ge=1, le=1000)). They live here as
// named constants so the input cannot drift away from what the endpoint will accept.
const MIN_SALES_FLOOR = 1;
const MIN_SALES_CEILING = 1000;

export default function ScreenerPage() {
  const { t } = useShell();
  const [minSales, setMinSales] = useState(5);
  const [propertyType, setPropertyType] = useState<string>("");
  const [rooms, setRooms] = useState<string>("");
  const [sort, setSort] = useState<SortKey>("n");
  const [descending, setDescending] = useState(true);

  const screener = useScreener({
    min_sales: minSales,
    property_type: propertyType || undefined,
    rooms: rooms === "" ? undefined : Number(rooms),
  });

  const rows = useMemo(() => {
    const data = [...(screener.data?.rows ?? [])];
    data.sort((a, b) => {
      const left = (a[sort] ?? 0) as number;
      const right = (b[sort] ?? 0) as number;
      return descending ? right - left : left - right;
    });
    return data;
  }, [screener.data, sort, descending]);

  const mode =
    typeof document !== "undefined" && document.documentElement.dataset.theme === "dark"
      ? "dark"
      : "light";

  const header = (key: SortKey, label: string) => (
    // aria-sort belongs on the columnheader. It was on the button inside it, where the attribute
    // is not allowed and assistive technology does not look for it — so the sort state was
    // announced to nobody.
    <th
      scope="col"
      aria-sort={sort === key ? (descending ? "descending" : "ascending") : "none"}
      className="px-3 py-2 text-right font-medium text-ink-secondary"
    >
      <button
        type="button"
        onClick={() => {
          if (sort === key) setDescending((value) => !value);
          else {
            setSort(key);
            setDescending(true);
          }
        }}
        className="hover:text-ink"
      >
        {label} {sort === key ? (descending ? "↓" : "↑") : ""}
      </button>
    </th>
  );

  return (
    <>
      <PageHeader
        title={t("nav.screener")}
        lede="Every community, property type and bedroom count the registry records, ranked however you like."
      />
      <div className="mb-4 space-y-3">
        <ProvenanceNotice provenance={screener.data?.provenance as "REAL" | "SYNTHETIC" | undefined} />
        <AdviceNotice compact />
      </div>

      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-4">
          <label className="text-xs">
            <span className="mb-1 block text-ink-muted">Minimum sales</span>
            <input
              type="number"
              min={MIN_SALES_FLOOR}
              max={MIN_SALES_CEILING}
              value={minSales}
              // Clamped at both ends, not just the bottom. The `max` attribute is advisory —
              // a browser will happily let someone type past it — and the API rejects an
              // out-of-range value with a 422, so without this the UI turns a plausible number
              // into a validation error instead of an empty result.
              onChange={(event) =>
                setMinSales(
                  Math.min(
                    MIN_SALES_CEILING,
                    Math.max(MIN_SALES_FLOOR, Number(event.target.value) || MIN_SALES_FLOOR),
                  ),
                )
              }
              className="w-24 rounded border border-line bg-bg px-2 py-1 text-ink"
            />
          </label>
          <label className="text-xs">
            <span className="mb-1 block text-ink-muted">Property type</span>
            <select
              value={propertyType}
              onChange={(event) => setPropertyType(event.target.value)}
              className="rounded border border-line bg-bg px-2 py-1 text-ink"
            >
              <option value="">Any</option>
              <option value="unit">Unit</option>
              <option value="villa">Villa</option>
              <option value="land">Land</option>
              <option value="building">Building</option>
            </select>
          </label>
          <label className="text-xs">
            <span className="mb-1 block text-ink-muted">Bedrooms</span>
            <select
              value={rooms}
              onChange={(event) => setRooms(event.target.value)}
              className="rounded border border-line bg-bg px-2 py-1 text-ink"
            >
              <option value="">Any</option>
              <option value="0">Studio</option>
              <option value="1">1</option>
              <option value="2">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
            </select>
          </label>
          <p className="ml-auto text-xs text-ink-muted">
            {screener.data ? `${count(screener.data.total_matching)} cells match` : ""}
          </p>
        </div>
      </Card>

      {screener.isLoading ? <Loading label={t("common.loading")} /> : null}
      {screener.isError ? (
        <ErrorState message={(screener.error as Error).message} onRetry={() => screener.refetch()} />
      ) : null}

      {screener.data ? (
        <Section title={`${rows.length} cells`}>
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-xs">
              <thead className="bg-sunken">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-medium text-ink-secondary">
                    Community
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium text-ink-secondary">
                    Type
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium text-ink-secondary">
                    Beds
                  </th>
                  {header("n", "Sales")}
                  {header("median_price", "Median price")}
                  {header("median_ppsqm", "AED/sqm")}
                  {header("offplan_share", "Off-plan")}
                  <th scope="col" className="px-3 py-2 text-left font-medium text-ink-secondary">
                    Confidence
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 300).map((row, i) => {
                  const confidence = confidenceFor(row.n, row.cv);
                  return (
                    <tr key={i} className="border-t border-line hover:bg-sunken">
                      <td className="px-3 py-1.5">
                        <Link
                          href={`/areas/${encodeURIComponent(row.area_key)}`}
                          className="text-ink hover:text-teal-ink hover:underline"
                        >
                          {row.area_name ?? row.area_key}
                        </Link>
                      </td>
                      <td className="px-3 py-1.5 text-ink-secondary">{row.property_type ?? "—"}</td>
                      <td className="px-3 py-1.5 text-right text-ink-secondary">
                        {row.rooms === null ? "—" : row.rooms === 0 ? "studio" : row.rooms}
                      </td>
                      <td className="px-3 py-1.5 text-right text-ink-secondary">{count(row.n)}</td>
                      <td className="px-3 py-1.5 text-right text-ink-secondary">
                        {aed(row.median_price)}
                      </td>
                      <td className="px-3 py-1.5 text-right text-ink-secondary">
                        {compactAed(row.median_ppsqm)}
                      </td>
                      <td className="px-3 py-1.5 text-right text-ink-secondary">
                        {row.offplan_share === null ? "—" : percent(row.offplan_share * 100, 0)}
                      </td>
                      <td className="px-3 py-1.5">
                        <span className="flex items-center gap-1.5 text-ink-muted">
                          <span
                            className="h-2 w-2 rounded-full"
                            style={{ background: CONFIDENCE[confidence][mode] }}
                            aria-hidden="true"
                          />
                          {confidence}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-ink-muted">
            Confidence combines the number of sales with how spread out their prices are. A cell
            marked insufficient is not shown as a number anywhere else in the application.
          </p>
        </Section>
      ) : null}
    </>
  );
}
