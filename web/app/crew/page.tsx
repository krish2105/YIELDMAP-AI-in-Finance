"use client";

import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { AdviceNotice } from "@/components/Notices";
import { Card, Empty, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { API_BASE, api } from "@/lib/api";
import { useAreas } from "@/lib/hooks";

interface Event {
  kind: string;
  payload: Record<string, unknown>;
  at: number;
}

const AGENTS = [
  { name: "Valuer", tools: "query_sql, area_summary, hedonic_predict, index_lookup", job: "What is it worth, and against what comparison" },
  { name: "YieldAnalyst", tools: "query_sql, yield_lookup, yield_for, dcf, mortgage", job: "What does it return, and under which assumptions" },
  { name: "RiskAuditor", tools: "query_sql, risk_score, anomaly_lookup, forecast_lookup", job: "What could go wrong, and how much of it is measurable" },
  { name: "Advisor", tools: "none", job: "Writes the memo from what the others found" },
  { name: "Auditor", tools: "none", job: "Checks the run against policy, whatever the outcome" },
];

export default function CrewPage() {
  const { t, role } = useShell();
  const areas = useAreas();
  const [area, setArea] = useState("");
  const [events, setEvents] = useState<Event[]>([]);
  const [running, setRunning] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const providers = useQuery({
    queryKey: ["providers"],
    queryFn: () =>
      api.get<{
        chain: string[];
        backends: { backend: string; available: boolean; reason: string; requests_today: number }[];
        usage: { daily_limit: number; spend_aed: number; note: string };
      }>("/ask/providers"),
  });

  const run = async () => {
    if (!area) return;
    setEvents([]);
    setRunning(true);
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;

    try {
      const response = await fetch(`${API_BASE}/runs/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Yieldmap-Role": "analyst" },
        body: JSON.stringify({ area_key: area }),
        signal: controller.signal,
      });
      if (!response.body) throw new Error("no stream");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const kind = /^event: (.+)$/m.exec(block)?.[1] ?? "message";
          const raw = /^data: (.+)$/m.exec(block)?.[1];
          if (!raw) continue;
          setEvents((current) => [...current, { kind, payload: JSON.parse(raw), at: Date.now() }]);
        }
      }
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        setEvents((current) => [
          ...current,
          { kind: "error", payload: { detail: (error as Error).message }, at: Date.now() },
        ]);
      }
    } finally {
      setRunning(false);
    }
  };

  const canRun = role === "analyst" || role === "admin";

  return (
    <>
      <PageHeader
        title={t("nav.crew")}
        lede="Five agents, bounded and audited. Watch one run and see exactly what each contributed."
      />
      <div className="mb-4">
        <AdviceNotice compact />
      </div>

      <Section title="Who does what" hint="The Advisor has no tools at all, which is the point.">
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {AGENTS.map((agent) => (
            <Card key={agent.name}>
              <p className="font-medium text-ink">{agent.name}</p>
              <p className="mt-0.5 text-xs text-ink-secondary">{agent.job}</p>
              <p className="mt-1.5 font-mono text-[11px] text-ink-muted">
                tools: {agent.tools}
              </p>
            </Card>
          ))}
        </div>
        <p className="mt-2 text-xs text-ink-secondary">
          The Advisor is granted nothing — not told to avoid tools, not given them. It reasons only
          over what the analysts established and over the cited corpus, which is why every number in
          its memo is one another agent produced with a query behind it. No tool in the registry has
          side effects, and the Auditor blocks any run where one appears.
        </p>
      </Section>

      <Section title="Run one">
        <Card>
          {!canRun ? (
            <p className="text-sm text-ink-secondary">
              Running the crew needs the analyst role. Change it in the sidebar.
            </p>
          ) : (
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-xs">
                <span className="mb-1 block text-ink-muted">Community</span>
                <select
                  value={area}
                  onChange={(event) => setArea(event.target.value)}
                  className="rounded border border-line bg-bg px-2 py-1.5 text-sm text-ink"
                >
                  <option value="">Choose…</option>
                  {(areas.data?.areas ?? []).map((row) => (
                    <option key={row.area_key} value={row.area_key}>
                      {row.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                onClick={run}
                disabled={!area || running}
                className="rounded-lg border border-teal bg-sunken px-3 py-1.5 text-sm font-medium text-ink disabled:opacity-40"
              >
                {running ? "Running…" : "Run the crew"}
              </button>
            </div>
          )}
        </Card>
      </Section>

      <Section title="The run" hint="Each agent reports as it finishes.">
        {events.length === 0 ? (
          <Empty message="Nothing has run yet." />
        ) : (
          <ol className="space-y-1.5" data-testid="crew-events">
            {events.map((event, i) => (
              <li
                key={i}
                className="rounded-lg border border-line bg-raised px-3 py-2 text-xs"
              >
                <span
                  className="mr-2 font-mono"
                  style={{
                    color:
                      event.kind === "error"
                        ? "var(--warn-ink)"
                        : event.kind === "done"
                          ? "var(--teal-ink)"
                          : "var(--ink-muted)",
                  }}
                >
                  {event.kind}
                </span>
                <span className="text-ink-secondary">
                  {event.kind === "finding"
                    ? `${event.payload.agent}: ${event.payload.label} = ${event.payload.value ?? "not established"}`
                    : event.kind === "audit"
                      ? `[${event.payload.severity}] ${event.payload.rule}: ${event.payload.detail}`
                      : event.kind === "disagreement"
                        ? String(event.payload.summary)
                        : JSON.stringify(event.payload)}
                </span>
              </li>
            ))}
          </ol>
        )}
      </Section>

      <Section title="What it costs" hint="Zero, by construction.">
        <Card>
          {providers.data ? (
            <>
              <p className="mb-2 text-sm text-ink-secondary">
                Provider chain: {providers.data.chain.join(" → ")}
              </p>
              <ul className="space-y-1 text-xs">
                {providers.data.backends.map((backend) => (
                  <li key={backend.backend} className="flex items-baseline gap-2">
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ background: backend.available ? "var(--teal)" : "var(--ink-muted)" }}
                      aria-hidden="true"
                    />
                    <span className="w-20 text-ink">{backend.backend}</span>
                    <span className="text-ink-muted">{backend.reason}</span>
                    <span className="ml-auto text-ink-muted">
                      {backend.requests_today} today
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-ink-muted">{providers.data.usage.note}</p>
            </>
          ) : null}
        </Card>
      </Section>
    </>
  );
}
