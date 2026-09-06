"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useEffect, useState } from "react";

import { SCATTER_SERIES_CAP, scatterColor, seriesColor } from "@/lib/theme";

/**
 * The chart system.
 *
 * A few rules are enforced here rather than left to each caller, because they are the ones that go
 * wrong: one y-axis only, colour assigned by fixed slot and never cycled, a legend whenever there
 * is more than one series, recessive grid lines, and a tooltip on everything that has marks.
 *
 * Scatter forms use a separate, smaller palette and refuse a fourth series. Every pair of points
 * is on screen at once in a scatter, and the eight-slot categorical set does not survive that test
 * — two of its hues are indistinguishable to a deuteranope on a dark ground.
 */

const AXIS = {
  stroke: "var(--line-strong)",
  tick: { fill: "var(--ink-muted)", fontSize: 11 },
  tickLine: false,
};

function useMode(): "light" | "dark" {
  const [mode, setMode] = useState<"light" | "dark">("light");
  useEffect(() => {
    const read = () => {
      const stamped = document.documentElement.dataset.theme;
      if (stamped === "dark" || stamped === "light") return stamped;
      return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    };
    setMode(read());
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const observer = new MutationObserver(() => setMode(read()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const onMedia = () => setMode(read());
    media.addEventListener("change", onMedia);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", onMedia);
    };
  }, []);
  return mode;
}

function TooltipBox({
  active,
  payload,
  label,
  formatter,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number | string; color?: string }[];
  label?: string | number;
  formatter?: (value: number, name: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-raised px-3 py-2 text-xs shadow-card">
      {label !== undefined ? <p className="mb-1 font-medium text-ink">{label}</p> : null}
      {payload.map((entry, i) => (
        <p key={i} className="flex items-center gap-2 text-ink-secondary">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ background: entry.color }}
            aria-hidden="true"
          />
          <span>{entry.name}</span>
          <span className="ml-auto font-medium text-ink">
            {formatter && typeof entry.value === "number"
              ? formatter(entry.value, entry.name ?? "")
              : String(entry.value)}
          </span>
        </p>
      ))}
    </div>
  );
}

export interface SeriesSpec {
  key: string;
  label: string;
}

export function TimeSeries({
  data,
  series,
  xKey = "x",
  height = 260,
  yFormatter,
  valueFormatter,
  reference,
}: {
  data: Record<string, unknown>[];
  series: SeriesSpec[];
  xKey?: string;
  height?: number;
  yFormatter?: (value: number) => string;
  valueFormatter?: (value: number, name: string) => string;
  reference?: { y: number; label: string };
}) {
  const mode = useMode();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
        <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey={xKey} {...AXIS} minTickGap={28} />
        <YAxis {...AXIS} width={56} tickFormatter={yFormatter} />
        <Tooltip content={<TooltipBox formatter={valueFormatter} />} />
        {series.length > 1 ? (
          <Legend wrapperStyle={{ fontSize: 11, color: "var(--ink-secondary)" }} />
        ) : null}
        {reference ? (
          <ReferenceLine
            y={reference.y}
            stroke="var(--ink-muted)"
            strokeDasharray="4 4"
            label={{ value: reference.label, fill: "var(--ink-muted)", fontSize: 10 }}
          />
        ) : null}
        {series.map((spec, i) => (
          <Line
            key={spec.key}
            type="monotone"
            dataKey={spec.key}
            name={spec.label}
            stroke={seriesColor(i, mode)}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function Band({
  data,
  xKey = "x",
  height = 260,
  yFormatter,
  valueFormatter,
}: {
  data: Record<string, unknown>[];
  xKey?: string;
  height?: number;
  yFormatter?: (value: number) => string;
  valueFormatter?: (value: number, name: string) => string;
}) {
  const mode = useMode();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
        <defs>
          <linearGradient id="bandFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={seriesColor(0, mode)} stopOpacity={0.22} />
            <stop offset="100%" stopColor={seriesColor(0, mode)} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey={xKey} {...AXIS} minTickGap={28} />
        <YAxis {...AXIS} width={56} tickFormatter={yFormatter} />
        <Tooltip content={<TooltipBox formatter={valueFormatter} />} />
        <Area
          type="monotone"
          dataKey="upper"
          name="Upper"
          stroke="none"
          fill="url(#bandFill)"
          isAnimationActive={false}
        />
        <Area
          type="monotone"
          dataKey="lower"
          name="Lower"
          stroke="none"
          fill="var(--bg-raised)"
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="value"
          name="Forecast"
          stroke={seriesColor(0, mode)}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function Bars({
  data,
  series,
  xKey = "x",
  height = 260,
  stacked = false,
  horizontal = false,
  yFormatter,
  valueFormatter,
  colorBy,
}: {
  data: Record<string, unknown>[];
  series: SeriesSpec[];
  xKey?: string;
  height?: number;
  stacked?: boolean;
  horizontal?: boolean;
  yFormatter?: (value: number) => string;
  valueFormatter?: (value: number, name: string) => string;
  colorBy?: (row: Record<string, unknown>, index: number) => string;
}) {
  const mode = useMode();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout={horizontal ? "vertical" : "horizontal"}
        margin={{ top: 8, right: 12, bottom: 4, left: horizontal ? 8 : 4 }}
      >
        <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={horizontal} horizontal={!horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" {...AXIS} tickFormatter={yFormatter} />
            <YAxis type="category" dataKey={xKey} {...AXIS} width={140} />
          </>
        ) : (
          <>
            <XAxis dataKey={xKey} {...AXIS} minTickGap={16} />
            <YAxis {...AXIS} width={56} tickFormatter={yFormatter} />
          </>
        )}
        <Tooltip
          content={<TooltipBox formatter={valueFormatter} />}
          cursor={{ fill: "var(--bg-sunken)" }}
        />
        {series.length > 1 ? (
          <Legend wrapperStyle={{ fontSize: 11, color: "var(--ink-secondary)" }} />
        ) : null}
        {series.map((spec, i) => (
          <Bar
            key={spec.key}
            dataKey={spec.key}
            name={spec.label}
            stackId={stacked ? "a" : undefined}
            fill={seriesColor(i, mode)}
            radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
            isAnimationActive={false}
          >
            {colorBy
              ? data.map((row, index) => (
                  <Cell key={index} fill={colorBy(row, index)} />
                ))
              : null}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Dots({
  data,
  xKey,
  yKey,
  groups,
  height = 320,
  xLabel,
  yLabel,
  xFormatter,
  yFormatter,
  diagonal = false,
}: {
  data: Record<string, unknown>[];
  xKey: string;
  yKey: string;
  groups?: { key: string; label: string }[];
  height?: number;
  xLabel?: string;
  yLabel?: string;
  xFormatter?: (value: number) => string;
  yFormatter?: (value: number) => string;
  diagonal?: boolean;
}) {
  const mode = useMode();
  // Three is the documented cap for all-pairs forms; a fourth is folded away upstream.
  const shown = (groups ?? [{ key: "all", label: "All" }]).slice(0, SCATTER_SERIES_CAP);
  const extent = data.flatMap((row) => [Number(row[xKey]), Number(row[yKey])]).filter(Number.isFinite);
  const max = extent.length ? Math.max(...extent) : 1;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
        <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" />
        <XAxis
          type="number"
          dataKey={xKey}
          {...AXIS}
          tickFormatter={xFormatter}
          label={
            xLabel
              ? { value: xLabel, position: "insideBottom", offset: -12, fill: "var(--ink-muted)", fontSize: 11 }
              : undefined
          }
        />
        <YAxis
          type="number"
          dataKey={yKey}
          {...AXIS}
          width={56}
          tickFormatter={yFormatter}
          label={
            yLabel
              ? { value: yLabel, angle: -90, position: "insideLeft", fill: "var(--ink-muted)", fontSize: 11 }
              : undefined
          }
        />
        <Tooltip content={<TooltipBox />} cursor={{ strokeDasharray: "3 3" }} />
        {shown.length > 1 ? (
          <Legend wrapperStyle={{ fontSize: 11, color: "var(--ink-secondary)" }} />
        ) : null}
        {diagonal ? (
          <ReferenceLine
            segment={[
              { x: 0, y: 0 },
              { x: max, y: max },
            ]}
            stroke="var(--ink-muted)"
            strokeDasharray="4 4"
          />
        ) : null}
        {shown.map((group, i) => (
          <Scatter
            key={group.key}
            name={group.label}
            data={group.key === "all" ? data : data.filter((row) => row.group === group.key)}
            fill={scatterColor(i, mode)}
            isAnimationActive={false}
          />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  );
}

/**
 * The table view every chart owes its reader.
 *
 * Three colours in the light palette sit below 3:1 against the surface, which the palette
 * validator flags as needing relief. This is that relief, and it is also simply the right thing
 * for a screen reader.
 */

// Re-exported so existing imports keep working. Importing it from here pulls the charting library
// in with it, which is the cost this split exists to avoid — the five table-only pages import it
// from "@/components/DataTable" directly.
export { DataTable } from "./DataTable";
