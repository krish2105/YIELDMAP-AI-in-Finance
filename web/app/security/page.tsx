"use client";

import { DataTable } from "@/components/Charts";
import { Card, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useResult } from "@/lib/hooks";

interface RedTeam {
  provenance: "REAL" | "SYNTHETIC";
  generated_at: string;
  summary: { attempts: number; blocked: number; passed: boolean };
  attacks: {
    id: string;
    risk: string;
    name: string;
    description: string;
    blocked: boolean;
    defence: string;
  }[];
}

/** The mapping is static: it describes the design, not a run. */
const RISKS = [
  {
    id: "ASI01",
    name: "Agent goal manipulation",
    treatment:
      "Retrieved text is fenced in explicit delimiters and the system prompt states that anything inside them is a document making a claim, never an instruction. A poisoned document is quoted, not obeyed.",
  },
  {
    id: "ASI02",
    name: "Tool misuse",
    treatment:
      "Tools are granted per agent by a registry that refuses ungranted calls and records the denial. The Advisor is granted nothing at all, so it cannot be prompted into a capability it does not have.",
  },
  {
    id: "ASI03",
    name: "Identity and privilege abuse",
    treatment:
      "Three roles. Only the analyst role can create a memo, which is the single write in the application, and the API enforces it rather than trusting the interface to hide the button.",
  },
  {
    id: "ASI04",
    name: "Unexpected code execution",
    treatment:
      "There is no code-execution tool. Queries must be plain selects, are checked for statements that would change data, and run on a connection opened read-only.",
  },
  {
    id: "ASI05",
    name: "Memory poisoning",
    treatment:
      "Memory is screened on the way in, fenced as data on the way out, and a suspicious entry is quarantined rather than deleted so a poisoning attempt stays inspectable.",
  },
  {
    id: "ASI06",
    name: "Cascading failure",
    treatment:
      "Every run is bounded on requests, wall time and steps, and has a kill switch. Hitting a limit is a recorded outcome, and the Auditor runs on failed runs too.",
  },
  {
    id: "ASI07",
    name: "Misaligned behaviour",
    treatment:
      "The Auditor blocks a memo that uses advice language or cites nothing, and the memo is withheld rather than shown with a warning.",
  },
  {
    id: "ASI08",
    name: "Traceability gaps",
    treatment:
      "Every message on the bus is signed, ordered and append-only, so an altered transcript stops verifying and blocks the run.",
  },
];

export default function SecurityPage() {
  const { t } = useShell();
  const redteam = useResult<RedTeam>("/security");

  return (
    <>
      <PageHeader
        title={t("nav.security")}
        lede="What an agent in this system is allowed to do, and what stops it doing anything else."
      />

      <Section title="The boundary" hint="Architectural, not a matter of policy.">
        <Card>
          <ul className="space-y-1.5 text-sm text-ink-secondary">
            <li>· No endpoint buys, sells, lists or finances anything. A test reads the API schema and fails if one appears.</li>
            <li>· No tool in the agent registry has side effects, and the Auditor blocks any run where one is registered.</li>
            <li>· The only write in the application stores a document.</li>
            <li>· Queries run on a read-only connection, and are refused before that if they are not plain selects.</li>
          </ul>
        </Card>
      </Section>

      <Section title="Risk treatment" hint="Mapped against the OWASP Agentic Security Initiative list.">
        <DataTable
          columns={[
            { key: "id", label: "Risk" },
            { key: "name", label: "Name" },
            { key: "treatment", label: "How it is treated" },
          ]}
          rows={RISKS}
        />
      </Section>

      <Section title="Red-team results">
        {redteam.data ? (
          <>
            <div className="mb-3 grid grid-cols-3 gap-3">
              <Card>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Attempts</p>
                <p className="mt-1 font-display text-2xl text-ink">
                  {redteam.data.summary.attempts}
                </p>
              </Card>
              <Card>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Blocked</p>
                <p
                  className="mt-1 font-display text-2xl"
                  style={{
                    color: redteam.data.summary.passed ? "var(--teal-ink)" : "var(--sand)",
                  }}
                >
                  {redteam.data.summary.blocked}
                </p>
              </Card>
              <Card>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Gate</p>
                <p
                  className="mt-1 font-display text-2xl"
                  style={{
                    color: redteam.data.summary.passed ? "var(--teal-ink)" : "var(--sand)",
                  }}
                >
                  {redteam.data.summary.passed ? "pass" : "fail"}
                </p>
              </Card>
            </div>
            <DataTable
              columns={[
                { key: "risk", label: "Risk" },
                { key: "name", label: "Attack" },
                { key: "blocked", label: "Blocked" },
                { key: "defence", label: "What stopped it" },
              ]}
              rows={redteam.data.attacks.map((attack) => ({
                risk: attack.risk,
                name: attack.name,
                blocked: attack.blocked ? "yes" : "NO",
                defence: attack.defence,
              }))}
            />
          </>
        ) : (
          <Card>
            <p className="text-sm text-ink-secondary">
              The red-team suite has not published results yet. It runs in CI on every push and
              writes its report alongside the other measured outputs.
            </p>
          </Card>
        )}
      </Section>
    </>
  );
}
