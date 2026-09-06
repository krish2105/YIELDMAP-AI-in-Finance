"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { AdviceNotice, ProvenanceNotice } from "@/components/Notices";
import { Card, Empty, ErrorState, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { type AskAnswer, api } from "@/lib/api";

const EXAMPLES = [
  "What is the net yield for a 1-bed in JVC?",
  "Can my landlord raise my rent by 15 percent this year?",
  "Why do service charges differ so much between buildings?",
  "ما هي رسوم نقل الملكية في دبي؟",
  "सर्विस चार्ज क्या होता है?",
];

/** Renders the answer with its bracketed citations turned into links to the source list. */
function Answer({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="whitespace-pre-wrap leading-relaxed text-ink">
      {parts.map((part, i) => {
        const match = /^\[(\d+)\]$/.exec(part);
        if (!match) return <span key={i}>{part}</span>;
        return (
          <a
            key={i}
            href={`#source-${match[1]}`}
            className="mx-0.5 rounded bg-sunken px-1 text-xs font-medium text-teal-ink no-underline"
          >
            {match[1]}
          </a>
        );
      })}
    </p>
  );
}

export default function AskPage() {
  const { t } = useShell();
  const [question, setQuestion] = useState("");

  const sources = useQuery({
    queryKey: ["ask-sources"],
    queryFn: () =>
      api.get<{
        n_chunks: number;
        by_kind: Record<string, number>;
        documents: { title: string; source: string; status: string; chunks: number }[];
        unverified_documents: string[];
      }>("/ask/sources"),
  });

  const ask = useMutation({
    mutationFn: (q: string) => api.post<AskAnswer>("/ask", { question: q }),
  });

  const submit = (q: string) => {
    const trimmed = q.trim();
    if (trimmed.length < 3) return;
    setQuestion(trimmed);
    ask.mutate(trimmed);
  };

  return (
    <>
      <PageHeader
        title={t("nav.ask")}
        lede="Ask about the registry or about Dubai's property rules. Every factual sentence in the answer carries a source, and a sentence that cannot cite one is removed before you see it."
      />
      <div className="mb-4 space-y-3">
        <ProvenanceNotice provenance={ask.data?.provenance} />
        <AdviceNotice compact />
      </div>

      <Card className="mb-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submit(question);
          }}
        >
          <label htmlFor="question" className="sr-only">
            Question
          </label>
          <textarea
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit(question);
            }}
            rows={2}
            placeholder="Ask in English, Hindi or Arabic…"
            className="w-full resize-y rounded-lg border border-line bg-bg px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-muted focus:border-teal"
          />
          <div className="mt-2 flex items-center gap-2">
            <button
              type="submit"
              disabled={ask.isPending || question.trim().length < 3}
              className="rounded-lg border border-teal bg-sunken px-3 py-1.5 text-sm font-medium text-ink disabled:opacity-50"
            >
              {ask.isPending ? "Thinking…" : "Ask"}
            </button>
            <span className="text-xs text-ink-muted">⌘↵ to send</span>
          </div>
        </form>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => submit(example)}
              className="rounded-full border border-line px-2.5 py-1 text-xs text-ink-secondary hover:border-teal hover:text-teal-ink"
            >
              {example}
            </button>
          ))}
        </div>
      </Card>

      {ask.isError ? <ErrorState message={(ask.error as Error).message} /> : null}

      {ask.data ? (
        <Section title="Answer">
          <Card>
            {ask.data.found_material ? (
              <Answer text={ask.data.answer} />
            ) : (
              <Empty message={ask.data.answer} />
            )}

            <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-3 text-xs text-ink-muted">
              <span>
                citations on {Math.round(ask.data.citation_coverage * 100)}% of factual sentences
              </span>
              <span>language: {ask.data.language}</span>
              {ask.data.backend ? <span>answered by: {ask.data.backend}</span> : null}
              {ask.data.degraded ? (
                <span style={{ color: "var(--warn-ink)" }}>running degraded</span>
              ) : null}
            </div>

            {ask.data.notes.length ? (
              <ul className="mt-2 space-y-0.5 text-xs text-ink-muted">
                {ask.data.notes.map((note, i) => (
                  <li key={i}>· {note}</li>
                ))}
              </ul>
            ) : null}

            {ask.data.dropped_sentences.length ? (
              <details className="mt-3">
                <summary
                  className="cursor-pointer text-xs"
                  style={{ color: "var(--warn-ink)" }}
                >
                  {ask.data.dropped_sentences.length} sentence(s) were removed for citing nothing
                </summary>
                <ul className="mt-1 space-y-1 text-xs text-ink-muted">
                  {ask.data.dropped_sentences.map((sentence, i) => (
                    <li key={i} className="line-through">
                      {sentence}
                    </li>
                  ))}
                </ul>
                <p className="mt-1 text-xs text-ink-muted">
                  These stated a fact without naming a source, so they were stripped rather than
                  shown. That is the mechanism behind the citation guarantee.
                </p>
              </details>
            ) : null}
          </Card>

          {ask.data.citations.length ? (
            <div className="mt-4">
              <h3 className="mb-2 text-sm font-medium text-ink">Sources</h3>
              <ol className="space-y-1.5">
                {ask.data.citations.map((citation) => (
                  <li
                    key={citation.n}
                    id={`source-${citation.n}`}
                    className="scroll-mt-20 rounded-lg border border-line bg-raised px-3 py-2 text-xs"
                  >
                    <span className="mr-2 font-medium text-teal-ink">[{citation.n}]</span>
                    <span className="text-ink">{citation.title}</span>
                    {citation.section ? (
                      <span className="text-ink-muted"> — {citation.section}</span>
                    ) : null}
                    <span className="block text-ink-muted">
                      {citation.source}
                      {citation.status && citation.status !== "verified" ? (
                        <span style={{ color: "var(--warn-ink)" }}> · {citation.status}</span>
                      ) : null}
                      {ask.data!.used_sources.includes(citation.n) ? null : (
                        <span> · retrieved but not used</span>
                      )}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}
        </Section>
      ) : null}

      <Section title="What Ask can see" hint="The whole evidence base, so nothing is hidden.">
        <Card>
          {sources.data ? (
            <>
              <p className="mb-2 text-sm text-ink-secondary">
                {sources.data.n_chunks} passages: {sources.data.by_kind.doc ?? 0} from reference
                documents and {sources.data.by_kind.fact ?? 0} from the registry itself.
              </p>
              <ul className="space-y-1 text-xs">
                {sources.data.documents.map((document) => (
                  <li key={document.title} className="flex items-baseline justify-between gap-2">
                    <span className="text-ink-secondary">{document.title}</span>
                    <span className="text-ink-muted">
                      {document.chunks} passages
                      {document.status !== "verified" ? (
                        <span style={{ color: "var(--warn-ink)" }}> · {document.status}</span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
              {sources.data.unverified_documents.length ? (
                <p className="mt-3 text-xs text-ink-muted">
                  Documents marked unverified could not be retrieved from their publisher, so they
                  state the position in general terms and mark specific figures as unverified
                  rather than asserting numbers nobody checked.
                </p>
              ) : null}
            </>
          ) : null}
        </Card>
      </Section>
    </>
  );
}
