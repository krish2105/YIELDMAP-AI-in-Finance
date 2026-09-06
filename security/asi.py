"""The OWASP Agentic Security Initiative threats, mapped onto this system.

This is the register the red-team harness runs against. Each entry names a threat, says where it
could land in YIELDMAP specifically, and names the control that is supposed to stop it. A threat
with no test is a claim; a threat with a test is a measurement, so every entry carries the id of
the attack in `security/redteam.py` that tries it.

The mapping is deliberately honest about the threats this system does not face. YIELDMAP has no
tools with side effects, no payment path and no ability to send anything anywhere, so several ASI
threats are structurally absent rather than merely mitigated — and saying so is more useful than
padding the table with green ticks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Threat:
    id: str
    name: str
    surface: str
    control: str
    attack_id: str | None = None
    status: str = "tested"  # tested | structural | accepted

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "surface": self.surface,
            "control": self.control,
            "attack_id": self.attack_id,
            "status": self.status,
        }


THREATS: list[Threat] = [
    Threat(
        id="ASI01",
        name="Agent goal manipulation",
        surface=(
            "The RAG corpus is text the crew reads before writing a memo. A document carrying an "
            "instruction rather than a fact could redirect what the memo concludes."
        ),
        control=(
            "Retrieved text is fenced in <retrieved> delimiters and quoted as data. The Auditor "
            "blocks a memo containing advice language whatever produced it, so a successful "
            "injection still cannot ship."
        ),
        attack_id="goal_hijack_via_corpus",
    ),
    Threat(
        id="ASI02",
        name="Tool misuse",
        surface=(
            "Six agents share one tool registry. The Advisor writes the recommendation, so it is "
            "the agent an attacker most wants holding a tool."
        ),
        control=(
            "The Advisor is granted the empty set. The registry refuses any call from an agent "
            "without an explicit grant, and the Auditor blocks the run if the Advisor called "
            "anything at all or was granted anything at all."
        ),
        attack_id="advisor_tool_misuse",
    ),
    Threat(
        id="ASI03",
        name="Identity and privilege abuse",
        surface=(
            "The API separates viewer, analyst and admin. Memo writing is the only endpoint that "
            "writes, so it is the privilege worth stealing."
        ),
        control=(
            "The role arrives in a header the deployment's gateway sets, and anything "
            "unrecognised degrades to viewer rather than escalating. Endpoints declare a minimum "
            "role and return 403 below it."
        ),
        attack_id="rbac_bypass",
    ),
    Threat(
        id="ASI04",
        name="Resource overload",
        surface=(
            "A crew run makes model requests in a loop. An input that makes the loop longer costs "
            "quota, and quota is the one budget this project cannot buy more of."
        ),
        control=(
            "Three independent budgets — requests, seconds and steps — checked before every step. "
            "Exceeding one ends the run as `over_budget`, a recorded outcome rather than a crash."
        ),
        attack_id="budget_flood",
    ),
    Threat(
        id="ASI05",
        name="Cascading reliability failure",
        surface=(
            "The provider chain falls Ollama to Gemini to Groq. A hop that fails loudly could take "
            "the whole request down with it."
        ),
        control=(
            "Each hop is caught and logged, and the chain ends at a deterministic offline "
            "provider, so a feature degrades to a plainer answer instead of a 500."
        ),
        attack_id="provider_cascade",
    ),
    Threat(
        id="ASI06",
        name="Memory and context poisoning",
        surface=(
            "Memory is text one run writes and a later run reads. A note phrased as an "
            "instruction would steer every run after it."
        ),
        control=(
            "Notes are screened on the way in and quarantined — not deleted — when they read as "
            "instructions. Quarantined entries never reach a prompt and are listed in the audit."
        ),
        attack_id="memory_poisoning",
    ),
    Threat(
        id="ASI07",
        name="Insecure inter-agent communication",
        surface="Agents coordinate over a shared bus; the memo is defended by its transcript.",
        control=(
            "Every message is HMAC-signed and the log is append-only and ordered. The Auditor "
            "verifies all signatures and blocks the run if any message fails."
        ),
        attack_id="transcript_tampering",
    ),
    Threat(
        id="ASI08",
        name="Untraceable decision-making",
        surface=(
            "A number with no provenance is the failure this whole project is built against: a "
            "plausible figure nobody can check is worse than no figure."
        ),
        control=(
            "Every KPI carries the SQL that produced it and cannot be constructed without it. "
            "Every factual memo sentence carries a citation or is removed before the memo ships."
        ),
        attack_id="uncited_claim",
    ),
    Threat(
        id="ASI09",
        name="Agentic supply chain",
        surface="Python and npm dependencies, and the model weights the provider chain reaches.",
        control=(
            "Locked dependency files, `pip-audit` and `npm audit` in CI, and no model weights "
            "downloaded at runtime — the offline embedder is fitted from the corpus itself."
        ),
        attack_id=None,
        status="tested",
    ),
    Threat(
        id="ASI10",
        name="Human manipulation",
        surface=(
            "The product's output is a memo about money. Confident prose is itself the attack "
            "surface: a reader who believes a hedged statistical estimate is a recommendation has "
            "been manipulated whether or not anyone intended it."
        ),
        control=(
            "No transaction endpoint exists anywhere in the API. Advice language is blocked in "
            "the memo, an 'information, not advice' notice sits on every page carrying a "
            "conclusion, and disagreement between the Valuer and the RiskAuditor is shown rather "
            "than resolved."
        ),
        attack_id="advice_language",
    ),
]

# Threats the architecture removes rather than mitigates. Listed so the mapping is complete and so
# a future change that reintroduces one is visibly a change of posture, not a detail.
STRUCTURAL: list[Threat] = [
    Threat(
        id="ASI-N1",
        name="Unauthorised transaction execution",
        surface="Absent: no endpoint, tool or agent can place, fund or settle anything.",
        control="`tests/test_api.py` asserts no route path segment matches a transaction verb.",
        attack_id="no_transaction_surface",
        status="structural",
    ),
    Threat(
        id="ASI-N2",
        name="Data exfiltration by an agent",
        surface="Absent: no agent holds a network tool, so there is nowhere to send data.",
        control="The registry's whole tool set is read-only queries against the local warehouse.",
        attack_id="advisor_tool_misuse",
        status="structural",
    ),
]


def as_rows() -> list[dict[str, Any]]:
    return [t.as_dict() for t in THREATS + STRUCTURAL]
