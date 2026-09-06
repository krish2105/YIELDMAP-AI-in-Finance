"use client";

import type { Provenance } from "@/lib/api";
import { useShell } from "./Providers";

/**
 * The two notices that must never be optional.
 *
 * The advice banner appears on every page that shows a recommendation or a projection. The
 * provenance banner appears whenever the figures on screen come from the generated stand-in, and
 * it is deliberately loud: a reader who takes a synthetic number for a real one has been misled by
 * this application, not by the data.
 */

export function AdviceNotice({ compact = false }: { compact?: boolean }) {
  const { t } = useShell();
  return (
    <aside
      data-testid="advice-notice"
      className={`rounded-lg border border-line bg-sunken px-3 ${compact ? "py-2" : "py-3"} text-xs text-ink-secondary`}
      role="note"
    >
      <strong className="font-medium text-ink">{t("notice.title")}.</strong>{" "}
      {compact ? null : t("notice.body")}
    </aside>
  );
}

export function ProvenanceNotice({ provenance }: { provenance: Provenance | undefined }) {
  const { t } = useShell();
  if (provenance !== "SYNTHETIC") return null;
  return (
    <aside
      data-testid="provenance-notice"
      role="alert"
      className="rounded-lg border-2 px-3 py-3 text-xs"
      style={{
        borderColor: "var(--sand)",
        background: "color-mix(in oklab, var(--sand) 12%, transparent)",
      }}
    >
      <strong className="block font-medium text-ink">{t("provenance.synthetic.title")}</strong>
      <span className="text-ink-secondary">{t("provenance.synthetic.body")}</span>
    </aside>
  );
}
