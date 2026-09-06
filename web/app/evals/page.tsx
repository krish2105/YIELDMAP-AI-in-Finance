"use client";

import { DataTable } from "@/components/Charts";
import { Card, ErrorState, Loading, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useResult } from "@/lib/hooks";
import { percent } from "@/lib/format";

interface EvalReport {
  provenance: "REAL" | "SYNTHETIC";
  n_cases: number;
  k: number;
  recall_at_k: number;
  faithfulness: number;
  recall_target: number;
  faithfulness_target: number;
  recall_met: boolean;
  faithfulness_met: boolean;
  passed: boolean;
  by_language: Record<string, { cases: number; recall: number; faithfulness: number }>;
  retrieval_backend: string | null;
  degraded: boolean;
  caveat: string | null;
  failures: { id: string; lang: string; question: string; expected: string; retrieved: string[] }[];
  cases: { id: string; lang: string; question: string; recalled: boolean; faithful: boolean; hit_rank: number | null }[];
}

export default function EvalsPage() {
  const { t } = useShell();
  // Served from the published results the eval harness writes.
  const report = useResult<EvalReport>("/evals");

  if (report.isLoading) return <Loading label={t("common.loading")} />;
  if (report.isError) {
    return (
      <>
        <PageHeader title={t("nav.evals")} />
        <ErrorState
          message={(report.error as Error).message}
          onRetry={() => report.refetch()}
        />
      </>
    );
  }
  if (!report.data) return null;

  const data = report.data;
  const gate = (met: boolean) => (met ? "var(--teal-ink)" : "var(--warn-ink)");

  return (
    <>
      <PageHeader
        title={t("nav.evals")}
        lede="Thirty questions in three languages, scored on whether the right source was retrieved and whether every factual sentence cited one. Both are gated in CI."
      />

      <Section title="The gates">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Card>
            <p className="text-xs uppercase tracking-wide text-ink-muted">Recall@{data.k}</p>
            <p className="mt-1 font-display text-3xl" style={{ color: gate(data.recall_met) }}>
              {percent(data.recall_at_k * 100, 0)}
            </p>
            <p className="text-xs text-ink-muted">target {percent(data.recall_target * 100, 0)}</p>
          </Card>
          <Card>
            <p className="text-xs uppercase tracking-wide text-ink-muted">Faithfulness</p>
            <p className="mt-1 font-display text-3xl" style={{ color: gate(data.faithfulness_met) }}>
              {percent(data.faithfulness * 100, 0)}
            </p>
            <p className="text-xs text-ink-muted">
              target {percent(data.faithfulness_target * 100, 0)}
            </p>
          </Card>
          <Card>
            <p className="text-xs uppercase tracking-wide text-ink-muted">Cases</p>
            <p className="mt-1 font-display text-3xl text-ink">{data.n_cases}</p>
          </Card>
          <Card>
            <p className="text-xs uppercase tracking-wide text-ink-muted">Retrieval</p>
            <p className="mt-1 font-display text-lg text-ink">{data.retrieval_backend ?? "—"}</p>
            {data.degraded ? (
              <p className="text-xs" style={{ color: "var(--warn-ink)" }}>
                degraded
              </p>
            ) : null}
          </Card>
        </div>
        {data.caveat ? (
          <p className="mt-2 text-xs" style={{ color: "var(--warn-ink)" }}>
            {data.caveat}
          </p>
        ) : null}
      </Section>

      <Section
        title="By language"
        hint="Scored separately, because an aggregate can hide one language failing completely."
      >
        <DataTable
          columns={[
            { key: "lang", label: "Language" },
            { key: "cases", label: "Cases", align: "right" },
            { key: "recall", label: "Recall", align: "right" },
            { key: "faithfulness", label: "Faithfulness", align: "right" },
          ]}
          rows={Object.entries(data.by_language).map(([lang, row]) => ({
            lang: { en: "English", hi: "हिन्दी", ar: "العربية" }[lang] ?? lang,
            cases: row.cases,
            recall: percent(row.recall * 100, 0),
            faithfulness: percent(row.faithfulness * 100, 0),
          }))}
        />
        <p className="mt-2 text-xs text-ink-secondary">
          This breakdown earned its place. On its first run Arabic scored 25% and Hindi 33% against
          English&rsquo;s 100%, and the overall figure still cleared the gate. The cause was two real
          bugs: the lexical index tokenised Latin characters only, so a question asked in Arabic
          became an empty query; and the reference corpus was English-only, so a Hindi question had
          nothing to match. Both are fixed, and a regression test pins the old tokeniser back in
          place to prove the failure returns without it.
        </p>
      </Section>

      {data.failures.length ? (
        <Section title="Cases that failed">
          <DataTable
            columns={[
              { key: "id", label: "Case" },
              { key: "lang", label: "Lang" },
              { key: "question", label: "Question" },
              { key: "expected", label: "Expected" },
            ]}
            rows={data.failures.map((row) => ({
              id: row.id,
              lang: row.lang,
              question: row.question,
              expected: row.expected,
            }))}
          />
        </Section>
      ) : (
        <Section title="Cases">
          <DataTable
            columns={[
              { key: "id", label: "Case" },
              { key: "lang", label: "Lang" },
              { key: "question", label: "Question" },
              { key: "hit_rank", label: "Rank", align: "right" },
            ]}
            rows={data.cases.map((row) => ({
              id: row.id,
              lang: row.lang,
              question: row.question,
              hit_rank: row.hit_rank ?? "—",
            }))}
            caption="Every case passed. Rank is where the expected source appeared in the results."
          />
        </Section>
      )}
    </>
  );
}
