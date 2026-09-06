"use client";

import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";

import { type Kpi, formatKpi, isSuppressed } from "@/lib/kpi";
import { CONFIDENCE } from "@/lib/theme";
import { useShell } from "./Providers";

/**
 * The tile that makes traceability a feature rather than a promise.
 *
 * Every number shows the size of the sample behind it and how confident that makes it, and the
 * query that produced it is one click away. A cell with too few records renders "insufficient
 * data" rather than a figure — showing a median of three sales as though it were a market rate is
 * the specific failure this component exists to prevent.
 */

function Sparkline({ points, suppressed }: { points: number[]; suppressed: boolean }) {
  if (points.length < 2) return null;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const d = points
    .map((value, i) => {
      const x = (i / (points.length - 1)) * 100;
      const y = 24 - ((value - min) / span) * 22 - 1;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <svg
      viewBox="0 0 100 24"
      preserveAspectRatio="none"
      className="h-6 w-full"
      aria-hidden="true"
      role="presentation"
    >
      <path
        d={d}
        fill="none"
        stroke={suppressed ? "var(--ink-muted)" : "var(--teal)"}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        opacity={suppressed ? 0.4 : 1}
      />
    </svg>
  );
}

export default function KpiTile({
  kpi,
  spark,
  compact = false,
}: {
  kpi: Kpi;
  spark?: number[];
  compact?: boolean;
}) {
  const { t } = useShell();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const reduce = useReducedMotion();

  const suppressed = isSuppressed(kpi);
  const mode =
    typeof document !== "undefined" && document.documentElement.dataset.theme === "dark"
      ? "dark"
      : "light";
  const dot = CONFIDENCE[kpi.confidence][mode];

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(kpi.sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard permission refused: the query is on screen and can be selected */
    }
  };

  return (
    <div
      className="relative flex flex-col gap-2 rounded-xl border border-line bg-raised p-4 shadow-card"
      data-testid="kpi-tile"
      data-kpi-id={kpi.id}
      data-confidence={kpi.confidence}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{kpi.label}</p>
        <span
          className="mt-1 h-2 w-2 shrink-0 rounded-full"
          style={{ background: dot }}
          title={t(`kpi.confidence.${kpi.confidence}`)}
          aria-label={t(`kpi.confidence.${kpi.confidence}`)}
          role="img"
        />
      </div>

      {suppressed ? (
        <p className="font-display text-lg text-ink-muted" data-testid="kpi-suppressed">
          {t("kpi.insufficient")}
        </p>
      ) : (
        <motion.p
          className="font-display text-2xl leading-none text-ink"
          data-testid="kpi-value"
          initial={reduce ? false : { opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
        >
          {formatKpi(kpi)}
        </motion.p>
      )}

      {kpi.delta && !suppressed ? (
        <p
          className="text-xs"
          style={{
            color:
              kpi.delta.direction === "up"
                ? "var(--teal-ink)"
                : kpi.delta.direction === "down"
                  ? "var(--warn-ink)"
                  : "var(--ink-muted)",
          }}
        >
          {kpi.delta.value >= 0 ? "+" : ""}
          {kpi.delta.value.toFixed(1)}% {kpi.delta.window}
        </p>
      ) : null}

      {spark ? <Sparkline points={spark} suppressed={suppressed} /> : null}

      {!compact ? (
        <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-xs text-ink-muted">
          <span data-testid="kpi-n">
            {t("kpi.sample")} {kpi.n.toLocaleString()}
          </span>
          <span>
            {t("kpi.asof")} {kpi.asof}
          </span>
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="ml-auto rounded border border-line px-2 py-0.5 text-ink-secondary transition-colors hover:border-teal hover:text-teal-ink"
            aria-expanded={open}
            data-testid="kpi-trace"
          >
            {t("kpi.how")}
          </button>
        </div>
      ) : null}

      {open ? (
        <motion.div
          initial={reduce ? false : { opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="overflow-hidden border-t border-line pt-3 text-xs"
          data-testid="kpi-drawer"
        >
          <p className="mb-2 text-ink-secondary">
            <span className="font-medium text-ink">{t("kpi.method")}:</span>{" "}
            <a
              className="underline decoration-line underline-offset-2 hover:text-teal-ink"
              href={`/methodology#${kpi.method_id}`}
            >
              {kpi.method_id}
            </a>
          </p>
          <p className="mb-1 font-medium text-ink">{t("kpi.sql")}</p>
          <pre className="max-h-52 overflow-auto rounded-lg bg-sunken p-3 font-mono text-[11px] leading-relaxed text-ink-secondary">
            <code>{kpi.sql.trim()}</code>
          </pre>
          <div className="mt-2 flex items-center gap-3">
            <button
              type="button"
              onClick={copy}
              className="rounded border border-line px-2 py-0.5 text-ink-secondary hover:border-teal hover:text-teal-ink"
            >
              {copied ? t("kpi.copied") : t("kpi.copy")}
            </button>
            <span className="font-mono text-[11px] text-ink-muted">{kpi.sql_hash}</span>
          </div>
          {kpi.sources.length ? (
            <ul className="mt-2 space-y-0.5 text-ink-muted">
              {kpi.sources.map((source, i) => (
                <li key={i}>
                  {source.kind}: {source.ref}
                </li>
              ))}
            </ul>
          ) : null}
        </motion.div>
      ) : null}
    </div>
  );
}
