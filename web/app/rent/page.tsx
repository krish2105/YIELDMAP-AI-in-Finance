"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { DataTable, TimeSeries } from "@/components/Charts";
import { AdviceNotice } from "@/components/Notices";
import { Card, ErrorState, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { api } from "@/lib/api";
import { aed, compactAed } from "@/lib/format";

interface RentBuy {
  break_even_year: number | null;
  horizon_years: number;
  verdict: string;
  inputs: Record<string, number>;
  years: {
    year: number;
    buyer_equity: number;
    renter_wealth: number;
    buyer_outlay: number;
    renter_outlay: number;
    advantage: number;
  }[];
  disclaimer: string;
}

export default function RentPage() {
  const { t } = useShell();
  const [price, setPrice] = useState(1_500_000);
  const [rent, setRent] = useState(105_000);
  const [sqm, setSqm] = useState(95);
  const [years, setYears] = useState(15);
  const [growth, setGrowth] = useState(3);
  const [investment, setInvestment] = useState(5);

  const compare = useMutation({
    mutationFn: () =>
      api.post<RentBuy>(
        "/simulate/rent-vs-buy",
        {
          price,
          annual_rent: rent,
          sqm,
          years,
          price_growth: growth / 100,
          rent_growth: growth / 100,
          investment_return: investment / 100,
        },
        "viewer",
      ),
  });

  const field = (
    label: string,
    value: number,
    setValue: (value: number) => void,
    step = 1,
    suffix = "",
  ) => (
    <label className="text-xs">
      <span className="mb-1 block text-ink-muted">
        {label}
        {suffix}
      </span>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(event) => setValue(Number(event.target.value))}
        className="w-full rounded border border-line bg-bg px-2 py-1.5 text-sm text-ink"
      />
    </label>
  );

  return (
    <>
      <PageHeader
        title={t("nav.rent")}
        lede="Rent or buy, done properly. The usual comparison of monthly rent against a mortgage payment is wrong twice over: it ignores the fees and upkeep a renter never pays, and it ignores that a renter keeps their deposit and can invest it."
      />
      <div className="mb-4">
        <AdviceNotice />
      </div>

      <Section title="The two options">
        <Card>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {field("Purchase price", price, setPrice, 50_000)}
            {field("Annual rent", rent, setRent, 5_000)}
            {field("Floor area", sqm, setSqm, 5, " (sqm)")}
            {field("Horizon", years, setYears, 1, " (years)")}
            {field("Price growth", growth, setGrowth, 0.5, " (%)")}
            {field("Investment return", investment, setInvestment, 0.5, " (%)")}
          </div>
          <button
            type="button"
            onClick={() => compare.mutate()}
            className="mt-3 rounded-lg border border-teal bg-sunken px-3 py-1.5 text-sm font-medium text-ink"
          >
            Compare
          </button>
          <p className="mt-2 text-xs text-ink-muted">
            The renter starts with the buyer&rsquo;s deposit and fees invested rather than spent, and
            invests the difference whenever the buyer pays more.
          </p>
        </Card>
      </Section>

      {compare.isError ? <ErrorState message={(compare.error as Error).message} /> : null}

      {compare.data ? (
        <>
          <Section title="The verdict">
            <Card>
              <p className="font-display text-xl text-ink">{compare.data.verdict}</p>
              <p className="mt-1 text-xs text-ink-muted">
                Upfront cost of buying: {aed(compare.data.inputs.upfront_cost ?? 0)}
              </p>
            </Card>
          </Section>

          <Section title="Buyer equity against renter wealth">
            <Card>
              <TimeSeries
                data={compare.data.years.map((row) => ({
                  x: `Yr ${row.year}`,
                  buyer: Math.round(row.buyer_equity),
                  renter: Math.round(row.renter_wealth),
                }))}
                series={[
                  { key: "buyer", label: "Buyer equity" },
                  { key: "renter", label: "Renter wealth" },
                ]}
                yFormatter={compactAed}
                valueFormatter={(value) => aed(value)}
                height={300}
              />
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-ink-muted hover:text-ink">
                  Year by year
                </summary>
                <div className="mt-2">
                  <DataTable
                    columns={[
                      { key: "year", label: "Year" },
                      { key: "buyer_equity", label: "Buyer equity", align: "right" },
                      { key: "renter_wealth", label: "Renter wealth", align: "right" },
                      { key: "advantage", label: "Advantage", align: "right" },
                    ]}
                    rows={compare.data.years.map((row) => ({
                      year: row.year,
                      buyer_equity: Math.round(row.buyer_equity).toLocaleString(),
                      renter_wealth: Math.round(row.renter_wealth).toLocaleString(),
                      advantage: Math.round(row.advantage).toLocaleString(),
                    }))}
                  />
                </div>
              </details>
              <p className="mt-3 text-xs text-ink-muted">{compare.data.disclaimer}</p>
            </Card>
          </Section>
        </>
      ) : null}

      <Section title="How rent increases work in Dubai" hint="From the archived reference corpus.">
        <Card>
          <p className="text-sm text-ink-secondary">
            A landlord cannot raise the rent on renewal by an arbitrary amount. The permitted
            increase depends on how far the current rent sits below the market rate for comparable
            property, as measured by RERA&rsquo;s rental index — not on the percentage alone. A tenant
            paying close to the market rate is generally protected from any increase.
          </p>
          <p className="mt-2 text-xs text-ink-muted">
            The specific bands are deliberately not reproduced here. They could not be retrieved
            from the publisher, and stating a band from memory in a tool people might rely on would
            be worse than stating none. Use the official calculator for a specific tenancy, and see{" "}
            <a className="underline underline-offset-2 hover:text-teal-ink" href="/ask">
              Ask
            </a>{" "}
            for the cited source.
          </p>
        </Card>
      </Section>
    </>
  );
}
