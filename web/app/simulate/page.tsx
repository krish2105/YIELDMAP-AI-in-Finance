"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Bars, DataTable } from "@/components/Charts";
import { AdviceNotice } from "@/components/Notices";
import { Card, ErrorState, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { api } from "@/lib/api";
import { aed, percent } from "@/lib/format";

interface Assumption {
  key: string;
  label: string;
  value: number | null;
  unit: string | null;
  status: string;
  source: string | null;
  source_url: string | null;
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-ink-secondary">{label}</span>
        <span className="font-medium text-ink">
          {value.toLocaleString()}
          {suffix}
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-[var(--teal)]"
      />
    </label>
  );
}

export default function SimulatePage() {
  const { t } = useShell();
  const [price, setPrice] = useState(1_500_000);
  const [rent, setRent] = useState(105_000);
  const [sqm, setSqm] = useState(95);
  const [years, setYears] = useState(5);
  const [growth, setGrowth] = useState(3);
  const [ltv, setLtv] = useState(60);
  const [rate, setRate] = useState(4.25);
  const [vacancy, setVacancy] = useState(8);
  const [income, setIncome] = useState(45_000);

  const assumptions = useQuery({
    queryKey: ["assumptions"],
    queryFn: () =>
      api.get<{ yield: Assumption[]; mortgage: Assumption[]; unverified: string[]; notice: string }>(
        "/simulate/assumptions",
      ),
  });

  const projection = useMutation({
    mutationFn: () =>
      api.post<{
        irr: number | null;
        unlevered_irr: number | null;
        npv: number;
        equity_invested: number;
        equity_multiple: number | null;
        flows: { year: number; rent: number; operating_costs: number; interest: number; principal: number; capital: number; net: number }[];
        yield: Record<string, number> | null;
        disclaimer: string;
      }>("/simulate/projection", {
        price,
        annual_rent: rent,
        sqm,
        years,
        price_growth: growth / 100,
        rent_growth: growth / 100,
        loan_amount: (price * ltv) / 100,
        interest_rate: rate / 100,
        vacancy: vacancy / 100,
      }),
  });

  const affordability = useMutation({
    mutationFn: () =>
      api.post<{
        max_loan: number;
        deposit_required: number;
        monthly_payment: number;
        binding_constraint: string;
        ltv_cap: number;
        loan_by_ltv: number;
        loan_by_income: number;
        caveat: string | null;
      }>("/simulate/affordability", { price, monthly_income: income }),
  });

  return (
    <>
      <PageHeader
        title={t("nav.simulate")}
        lede="What a purchase would return under assumptions you set. Change any of them and watch the answer move."
      />
      <div className="mb-4">
        <AdviceNotice />
      </div>

      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <Card>
          <h2 className="mb-3 text-lg text-ink">The property</h2>
          <div className="space-y-3">
            <Slider label="Purchase price" value={price} min={200_000} max={20_000_000} step={50_000} suffix=" AED" onChange={setPrice} />
            <Slider label="Annual rent" value={rent} min={10_000} max={1_500_000} step={5_000} suffix=" AED" onChange={setRent} />
            <Slider label="Floor area" value={sqm} min={20} max={800} step={5} suffix=" sqm" onChange={setSqm} />
          </div>

          <h2 className="mb-3 mt-6 text-lg text-ink">The finance</h2>
          <div className="space-y-3">
            <Slider label="Loan to value" value={ltv} min={0} max={80} step={5} suffix="%" onChange={setLtv} />
            <Slider label="Interest rate" value={rate} min={0} max={12} step={0.25} suffix="%" onChange={setRate} />
            <Slider label="Holding period" value={years} min={1} max={25} step={1} suffix=" yr" onChange={setYears} />
            <Slider label="Annual growth" value={growth} min={-10} max={15} step={0.5} suffix="%" onChange={setGrowth} />
            <Slider label="Vacancy" value={vacancy} min={0} max={40} step={1} suffix="%" onChange={setVacancy} />
          </div>

          <button
            type="button"
            onClick={() => projection.mutate()}
            className="mt-5 w-full rounded-lg border border-teal bg-sunken px-3 py-2 text-sm font-medium text-ink hover:bg-raised"
          >
            Project the cash flows
          </button>

          <h2 className="mb-3 mt-6 text-lg text-ink">Affordability</h2>
          <Slider label="Monthly income" value={income} min={5_000} max={500_000} step={1_000} suffix=" AED" onChange={setIncome} />
          <button
            type="button"
            onClick={() => affordability.mutate()}
            className="mt-3 w-full rounded-lg border border-line px-3 py-2 text-sm text-ink-secondary hover:border-teal hover:text-teal-ink"
          >
            What could I borrow?
          </button>
        </Card>

        <div className="min-w-0 space-y-4">
          {projection.isError ? (
            <ErrorState message={(projection.error as Error).message} />
          ) : null}

          {projection.data ? (
            <Section title="The projection">
              <Card>
                <dl className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-4">
                  <div>
                    <dt className="text-xs text-ink-muted">Levered IRR</dt>
                    <dd className="font-display text-2xl text-ink">
                      {projection.data.irr !== null ? percent(projection.data.irr * 100) : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">Unlevered IRR</dt>
                    <dd className="font-display text-2xl text-ink">
                      {projection.data.unlevered_irr !== null
                        ? percent(projection.data.unlevered_irr * 100)
                        : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">Equity in</dt>
                    <dd className="font-display text-2xl text-ink">
                      {aed(projection.data.equity_invested)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">Multiple</dt>
                    <dd className="font-display text-2xl text-ink">
                      {projection.data.equity_multiple
                        ? `${projection.data.equity_multiple.toFixed(2)}×`
                        : "—"}
                    </dd>
                  </div>
                </dl>

                <p className="mb-4 text-xs text-ink-secondary">
                  The unlevered figure is the same property bought outright. Quoting a levered
                  return on its own describes the loan as much as the property, so both are shown.
                </p>

                <Bars
                  data={projection.data.flows.map((flow) => ({
                    x: `Yr ${flow.year}`,
                    net: Math.round(flow.net),
                  }))}
                  series={[{ key: "net", label: "Net cash flow" }]}
                  yFormatter={(value) => `${Math.round(value / 1000)}k`}
                  valueFormatter={(value) => aed(value)}
                  height={200}
                />

                <details className="mt-3">
                  <summary className="cursor-pointer text-xs text-ink-muted hover:text-ink">
                    Every line of the projection
                  </summary>
                  <div className="mt-2">
                    <DataTable
                      columns={[
                        { key: "year", label: "Year" },
                        { key: "rent", label: "Rent", align: "right" },
                        { key: "operating_costs", label: "Costs", align: "right" },
                        { key: "interest", label: "Interest", align: "right" },
                        { key: "principal", label: "Principal", align: "right" },
                        { key: "capital", label: "Capital", align: "right" },
                        { key: "net", label: "Net", align: "right" },
                      ]}
                      rows={projection.data.flows.map((flow) => ({
                        year: flow.year,
                        rent: Math.round(flow.rent).toLocaleString(),
                        operating_costs: Math.round(flow.operating_costs).toLocaleString(),
                        interest: Math.round(flow.interest).toLocaleString(),
                        principal: Math.round(flow.principal).toLocaleString(),
                        capital: Math.round(flow.capital).toLocaleString(),
                        net: Math.round(flow.net).toLocaleString(),
                      }))}
                    />
                  </div>
                </details>

                <p className="mt-3 text-xs text-ink-muted">{projection.data.disclaimer}</p>
              </Card>
            </Section>
          ) : null}

          {affordability.data ? (
            <Section title="What the rules allow">
              <Card>
                <dl className="grid grid-cols-2 gap-4 md:grid-cols-4">
                  <div>
                    <dt className="text-xs text-ink-muted">Maximum loan</dt>
                    <dd className="font-display text-xl text-ink">
                      {aed(affordability.data.max_loan)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">Deposit needed</dt>
                    <dd className="font-display text-xl text-ink">
                      {aed(affordability.data.deposit_required)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">Monthly payment</dt>
                    <dd className="font-display text-xl text-ink">
                      {aed(affordability.data.monthly_payment)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">What limits it</dt>
                    <dd className="text-sm text-ink">{affordability.data.binding_constraint}</dd>
                  </div>
                </dl>
                {affordability.data.caveat ? (
                  <p
                    className="mt-3 rounded-lg px-3 py-2 text-xs"
                    style={{
                      background: "color-mix(in oklab, var(--sand) 12%, transparent)",
                      color: "var(--ink-secondary)",
                    }}
                  >
                    {affordability.data.caveat}
                  </p>
                ) : null}
              </Card>
            </Section>
          ) : null}

          <Section
            title="The assumptions behind every figure"
            hint="Marked honestly. Anything unverified is an assumption, not a rule."
          >
            <Card>
              {assumptions.data ? (
                <DataTable
                  columns={[
                    { key: "label", label: "Assumption" },
                    { key: "value", label: "Value", align: "right" },
                    { key: "unit", label: "Unit" },
                    { key: "status", label: "Status" },
                  ]}
                  rows={[...assumptions.data.yield, ...assumptions.data.mortgage].map((row) => ({
                    label: row.label,
                    value: row.value === null ? "—" : row.value.toLocaleString(),
                    unit: row.unit ?? "",
                    status: row.status,
                  }))}
                />
              ) : null}
              {assumptions.data ? (
                <p className="mt-3 text-xs text-ink-muted">{assumptions.data.notice}</p>
              ) : null}
            </Card>
          </Section>
        </div>
      </div>
    </>
  );
}
