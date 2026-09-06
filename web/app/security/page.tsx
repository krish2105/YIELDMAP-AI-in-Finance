"use client";

import { DataTable } from "@/components/DataTable";
import { Card, PageHeader, Section } from "@/components/Page";
import { useShell } from "@/components/Providers";
import { useResult } from "@/lib/hooks";

/**
 * Everything on this page comes from docs/results/redteam.json, which `security/redteam.py`
 * writes when it runs the attacks.
 *
 * The threat table used to be typed out here as prose. That is the failure mode this whole
 * project is built against, one level up: a page describing controls it has not checked, drifting
 * from the code the moment either changes. The register now lives in `security/asi.py`, the
 * harness emits it beside the verdicts it measured, and this page renders what it is given.
 */
interface Outcome {
  id: string;
  threat: string;
  attack: string;
  held: boolean;
  detail: string;
}

interface Threat {
  id: string;
  name: string;
  surface: string;
  control: string;
  attack_id: string | null;
  status: "tested" | "structural" | "accepted";
}

interface RedTeam {
  provenance: "REAL" | "SYNTHETIC";
  generated_at: string;
  attacks_run: number;
  controls_held: number;
  controls_failed: number;
  outcomes: Outcome[];
  threat_register: Threat[];
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <Card>
      <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
      <p
        className="mt-1 font-display text-2xl tabular-nums text-ink"
        style={
          tone ? { color: tone === "good" ? "var(--teal-ink)" : "var(--warn-ink)" } : undefined
        }
      >
        {value}
      </p>
    </Card>
  );
}

export default function SecurityPage() {
  const { t } = useShell();
  const redteam = useResult<RedTeam>("/security");
  const data = redteam.data;
  const clean = data ? data.controls_failed === 0 : false;

  return (
    <>
      <PageHeader
        title={t("nav.security")}
        lede="What an agent in this system is allowed to do, what stops it doing anything else, and the measurement behind that claim."
      />

      <Section title="The boundary" hint="Architectural, not a matter of policy.">
        <Card>
          <ul className="space-y-1.5 text-sm text-ink-secondary">
            <li>
              · No endpoint buys, sells, lists or finances anything. A test reads the API schema
              and fails if one appears.
            </li>
            <li>
              · No tool in the agent registry has side effects, and the Auditor blocks any run
              where one is registered.
            </li>
            <li>· The only write in the application stores a document.</li>
            <li>
              · Queries run on a read-only connection, and are refused before that if they are not
              plain selects.
            </li>
            <li>
              · A memo whose every factual sentence is not cited is withheld, not shown with a
              caveat.
            </li>
          </ul>
        </Card>
      </Section>

      {data ? (
        <>
          <Section
            title="Red-team results"
            hint={`Measured ${data.generated_at.slice(0, 10)} · re-run and gated in CI on every push.`}
          >
            <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Stat label="Attacks run" value={String(data.attacks_run)} />
              <Stat
                label="Controls held"
                value={`${data.controls_held}/${data.attacks_run}`}
                tone={clean ? "good" : "bad"}
              />
              <Stat label="Gate" value={clean ? "pass" : "FAIL"} tone={clean ? "good" : "bad"} />
            </div>
            <DataTable
              columns={[
                { key: "threat", label: "Threat" },
                { key: "attack", label: "What was attempted" },
                { key: "held", label: "Held" },
                { key: "detail", label: "What happened" },
              ]}
              rows={data.outcomes.map((outcome) => ({
                threat: outcome.threat,
                attack: outcome.attack,
                held: outcome.held ? "yes" : "NO",
                detail: outcome.detail,
              }))}
            />
          </Section>

          <Section
            title="Risk treatment"
            hint="The OWASP Agentic Security Initiative list, mapped onto this system. Each row names the attack that tests it."
          >
            <DataTable
              columns={[
                { key: "id", label: "Threat" },
                { key: "name", label: "Name" },
                { key: "surface", label: "Where it lands here" },
                { key: "control", label: "What stops it" },
                { key: "tested", label: "Tested by" },
              ]}
              rows={data.threat_register.map((threat) => ({
                id: threat.id,
                name: threat.name,
                surface: threat.surface,
                control: threat.control,
                tested:
                  threat.attack_id ??
                  (threat.status === "structural" ? "absent by design" : "not attacked"),
              }))}
            />
          </Section>
        </>
      ) : (
        <Section title="Red-team results">
          <Card>
            <p className="text-sm text-ink-secondary">
              {redteam.isLoading
                ? "Loading the last measured run…"
                : "No red-team report has been published. It is written by security/redteam.py and runs in CI on every push."}
            </p>
          </Card>
        </Section>
      )}
    </>
  );
}
