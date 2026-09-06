"use client";

import { PageHeader, Section, Card } from "@/components/Page";
import { useShell } from "@/components/Providers";

/**
 * Every method id a KPI can carry has an anchor here, so the traceability drawer's link always
 * lands somewhere real.
 */
const METHODS = [
  {
    id: "median_ppsqm_v1",
    title: "Median price per square metre",
    body:
      "The median of price divided by floor area across every recorded sale in the window. Per square metre because it compares across unit sizes; median rather than mean because a handful of penthouses would otherwise carry the figure.",
    caveat: "Moves when the mix of what sold changes, not only when prices change. The repeat-sales index exists for that reason.",
  },
  {
    id: "volume_12m_v1",
    title: "Sales in the last twelve months",
    body: "A count of recorded transactions, not of listings or of viewings. Every row is a completed registration.",
  },
  {
    id: "total_value_12m_v1",
    title: "Total value transacted",
    body: "The sum of recorded prices over the window. It measures money that changed hands, not the value of the housing stock.",
  },
  {
    id: "offplan_share_v1",
    title: "Off-plan share",
    body: "The proportion of sales registered as off-plan rather than existing property, read from the registration type and falling back to the procedure name where that is blank.",
  },
  {
    id: "gross_yield_v1",
    title: "Gross yield",
    body: "Median annual registered rent divided by median sale price for the same community, property type and bedroom count, over the same window.",
    caveat: "The number every portal quotes, and close to meaningless alone: it ignores the service charge, the transfer fee, vacancy and management.",
  },
  {
    id: "net_yield_v1",
    title: "Net yield",
    body: "Rent after vacancy, less the service charge, management fee, maintenance and the one-off purchase costs spread over an assumed holding period, divided by the full acquisition cost including fees.",
    caveat: "Every input is an editable assumption, and the largest of them — the service charge — is currently an estimate rather than a per-building measurement.",
  },
  {
    id: "hedonic_v1",
    title: "Hedonic valuation",
    body: "A gradient-boosted regressor on log price per square metre, using community, property type, bedroom count, floor area, off-plan status and time. Predictions are transformed back with Duan's smearing correction, without which they would be biased low.",
    caveat: "Tested on the most recent twelve months only, never on data it was trained on.",
  },
  {
    id: "repeat_sales_v1",
    title: "Repeat-sales index",
    body: "Bailey-Muth-Nourse weighted least squares on period dummies, comparing each property against itself so composition cancels out. Pairs are weighted by the inverse of their holding period.",
    caveat: "Only published across a connected set of periods. Where two chains of periods share no repeat sale, their relative level is not identified by the data and is not invented.",
  },
  {
    id: "forecast_v1",
    title: "Forecast",
    body: "A damped local trend on log median price per square metre, scored against a seasonal naive benchmark on a held-out final year.",
    caveat: "Damped deliberately: an undamped trend extrapolated twelve months turns one good year into an absurd one.",
  },
  {
    id: "risk_v1",
    title: "Risk score",
    body: "A weighted blend of off-plan exposure, developer concentration, price volatility, illiquidity and anomaly density, each scaled to a bounded range and clipped rather than extrapolated.",
    caveat: "A judgement, not a measurement. The weights are published and the components are always shown beside the total.",
  },
  {
    id: "dcf_v1",
    title: "Holding-period cash flows",
    body: "Deposit and fees at entry, net rent less debt service each year, and sale proceeds after costs and after repaying the loan. Reduced to an internal rate of return.",
    caveat: "Reported levered and unlevered, because a levered return quoted alone describes the loan as much as the property.",
  },
  {
    id: "building_premium_v1",
    title: "Premium to the area",
    body: "A building's median price per square metre against the median for its own community, so location is held constant.",
  },
  {
    id: "developers_v1",
    title: "Developer premium",
    body: "A project's median price per square metre against the median for the same community in the same month, so both location and timing are held constant.",
    caveat: "The registry carries a project name but no developer identifier, so projects stand in for developers.",
  },
];

export default function MethodologyPage() {
  const { t } = useShell();
  return (
    <>
      <PageHeader
        title={t("nav.methodology")}
        lede="Every measure this application shows, what it means, and what it does not. Each KPI tile links here by its method id."
      />

      <Card className="mb-6">
        <h2 className="mb-2 text-lg text-ink">Sample size and confidence</h2>
        <p className="text-sm text-ink-secondary">
          Every figure carries the number of observations behind it. Confidence combines that count
          with how spread out the underlying values are, and a cell below the floor is not published
          as a number at all — it renders as &ldquo;insufficient data&rdquo;. A yield built from two
          hundred sales and three tenancies is a three-observation figure and is treated as one.
        </p>
        <p className="mt-2 text-sm text-ink-secondary">
          The thresholds live in a single file read by both the API and this interface, so the two
          can never disagree about whether a cell has enough data to show.
        </p>
      </Card>

      {METHODS.map((method) => (
        <Section key={method.id} id={method.id} title={method.title}>
          <Card>
            <p className="text-sm text-ink-secondary">{method.body}</p>
            {method.caveat ? (
              <p className="mt-2 text-xs" style={{ color: "var(--sand)" }}>
                {method.caveat}
              </p>
            ) : null}
            <p className="mt-2 font-mono text-[11px] text-ink-muted">{method.id}</p>
          </Card>
        </Section>
      ))}
    </>
  );
}
