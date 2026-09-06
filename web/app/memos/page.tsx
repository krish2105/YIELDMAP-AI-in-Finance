"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AdviceNotice, ProvenanceNotice } from "@/components/Notices";
import { Card, Empty, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { API_BASE, type MemoSummary, api } from "@/lib/api";
import { useAreas } from "@/lib/hooks";
import { dateLabel } from "@/lib/format";

interface MemoDetail {
  id: string;
  run_id: string;
  area_key: string;
  memo_md: string | null;
  citations: { n: number; title: string; source: string; agent: string; n_records: number | null }[];
  disagreements: { between: string[]; summary: string }[];
  findings: { agent: string; label: string; value: number | null; n: number | null; note: string | null }[];
  audit: { blocked: boolean; worst_severity: string; findings: { rule: string; severity: string; detail: string }[] };
  budget: Record<string, unknown>;
  status: string;
  provenance: "REAL" | "SYNTHETIC";
  citation_coverage: number;
}

/** Minimal Markdown rendering: the memo is generated, so only its own shapes need handling. */
function Memo({ markdown }: { markdown: string }) {
  return (
    <div className="space-y-2">
      {markdown.split("\n").map((line, i) => {
        if (!line.trim() || line.trim() === "---") return null;
        if (line.startsWith("### ")) return <h4 key={i} className="mt-3 text-sm font-semibold text-ink">{line.slice(4)}</h4>;
        if (line.startsWith("## ")) return <h3 key={i} className="mt-4 text-base text-ink">{line.slice(3)}</h3>;
        if (line.startsWith("# ")) return <h2 key={i} className="text-lg text-ink">{line.slice(2)}</h2>;
        if (line.startsWith("- ")) return <li key={i} className="ml-4 list-disc text-sm text-ink-secondary">{line.slice(2)}</li>;
        if (line.startsWith("*") && line.endsWith("*")) {
          return <p key={i} className="text-xs italic text-ink-muted">{line.replace(/^\*|\*$/g, "")}</p>;
        }
        return <p key={i} className="text-sm text-ink-secondary">{line}</p>;
      })}
    </div>
  );
}

export default function MemosPage() {
  const { t, role } = useShell();
  const client = useQueryClient();
  const areas = useAreas();
  const [area, setArea] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["memos"],
    queryFn: () => api.get<{ memos: MemoSummary[]; count: number }>("/memos"),
  });

  const detail = useQuery({
    queryKey: ["memo", openId],
    queryFn: () => api.get<MemoDetail>(`/memos/${openId}`),
    enabled: Boolean(openId),
  });

  const create = useMutation({
    mutationFn: (areaKey: string) => api.post<MemoDetail>("/memos", { area_key: areaKey }),
    onSuccess: (memo) => {
      setOpenId(memo.id);
      client.invalidateQueries({ queryKey: ["memos"] });
    },
  });

  const canWrite = role === "analyst" || role === "admin";

  return (
    <>
      <PageHeader
        title={t("nav.memos")}
        lede="An investment memo written by the crew, where every figure is one an analyst agent established with a query behind it."
      />
      <div className="mb-4 space-y-3">
        <ProvenanceNotice provenance={detail.data?.provenance} />
        <AdviceNotice />
      </div>

      <Section title="Write a new one">
        <Card>
          {!canWrite ? (
            <p className="text-sm text-ink-secondary">
              Writing a memo needs the analyst role. It is the only endpoint in the application
              that writes anything, and the only one that spends a model budget, so it is the only
              one behind a sign-in. Sign in from the sidebar to try it.
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
                disabled={!area || create.isPending}
                onClick={() => create.mutate(area)}
                className="rounded-lg border border-teal bg-sunken px-3 py-1.5 text-sm font-medium text-ink disabled:opacity-40"
              >
                {create.isPending ? "Running the crew…" : "Run the crew"}
              </button>
            </div>
          )}
          {create.isError ? (
            <div className="mt-3">
              <ErrorState message={(create.error as Error).message} />
            </div>
          ) : null}
        </Card>
      </Section>

      <Section title="Memos">
        {list.isLoading ? <Loading label={t("common.loading")} /> : null}
        {list.data?.memos.length === 0 ? <Empty message="No memos yet." /> : null}
        <ul className="space-y-2">
          {(list.data?.memos ?? []).map((memo) => (
            <li key={memo.id}>
              <button
                type="button"
                onClick={() => setOpenId(openId === memo.id ? null : memo.id)}
                aria-expanded={openId === memo.id}
                className="w-full rounded-xl border border-line bg-raised px-4 py-3 text-left hover:border-teal"
              >
                <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="font-medium text-ink">{memo.area_key}</span>
                  <span className="text-xs text-ink-muted">{dateLabel(memo.created_at)}</span>
                  <span className="text-xs text-ink-muted">{memo.citations} citations</span>
                  <span
                    className="text-xs"
                    style={{
                      color: memo.citation_coverage === 1 ? "var(--teal-ink)" : "var(--sand)",
                    }}
                  >
                    {Math.round(memo.citation_coverage * 100)}% cited
                  </span>
                  {memo.blocked ? (
                    <span className="text-xs" style={{ color: "var(--sand)" }}>
                      withheld by the audit
                    </span>
                  ) : null}
                  <span className="ml-auto text-xs text-ink-muted">{memo.status}</span>
                </span>
              </button>

              {openId === memo.id && detail.data ? (
                <Card className="mt-2">
                  {detail.data.memo_md ? (
                    <Memo markdown={detail.data.memo_md} />
                  ) : (
                    <Empty message="This memo was withheld because the audit blocked it." />
                  )}

                  {detail.data.disagreements.length ? (
                    <div className="mt-4 rounded-lg border border-line bg-sunken p-3">
                      <h4 className="mb-1 text-sm font-medium text-ink">
                        Where the analysts disagree
                      </h4>
                      {detail.data.disagreements.map((item, i) => (
                        <p key={i} className="text-xs text-ink-secondary">
                          <span className="text-ink-muted">{item.between.join(" vs ")}: </span>
                          {item.summary}
                        </p>
                      ))}
                    </div>
                  ) : null}

                  <div className="mt-4 border-t border-line pt-3">
                    <h4 className="mb-1 text-sm font-medium text-ink">Audit</h4>
                    <ul className="space-y-0.5 text-xs">
                      {detail.data.audit.findings.map((finding, i) => (
                        <li key={i} className="text-ink-secondary">
                          <span
                            style={{
                              color:
                                finding.severity === "block"
                                  ? "var(--sand)"
                                  : finding.severity === "warn"
                                    ? "var(--sand)"
                                    : "var(--ink-muted)",
                            }}
                          >
                            [{finding.severity}]
                          </span>{" "}
                          {finding.rule}: {finding.detail}
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    {(["md", "html", "docx"] as const).map((format) => (
                      <a
                        key={format}
                        href={`${API_BASE}/memos/${memo.id}/export?fmt=${format}`}
                        className="rounded-lg border border-line px-3 py-1.5 text-xs text-ink-secondary hover:border-teal hover:text-teal-ink"
                      >
                        Export .{format}
                      </a>
                    ))}
                  </div>
                </Card>
              ) : null}
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}
