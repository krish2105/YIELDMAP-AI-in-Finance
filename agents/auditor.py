"""The Auditor: policy checks on every run, whatever else happened.

It runs after the crew regardless of outcome — including on a run that failed or was killed —
because the runs worth inspecting are precisely the ones that went wrong. Its findings are severity
graded: `block` means the output must not be shown, `warn` means show it with the caveat, `info` is
a note for the record.

The checks are deliberately mechanical. An auditor that asks a model whether the run was acceptable
inherits every weakness of the thing it is auditing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agents.bus import MessageBus
from agents.tools import ToolRegistry

# Language a memo must not use, because it crosses from information into advice.
ADVICE_LANGUAGE = re.compile(
    r"\b(you should (buy|sell|invest)"
    r"|i recommend (buying|selling|investing)"
    r"|guaranteed returns?"
    r"|risk[- ]free"
    r"|cannot lose"
    r"|will definitely"
    r"|sure thing)\b",
    re.IGNORECASE,
)

SEVERITY_ORDER = {"info": 0, "warn": 1, "block": 2}


@dataclass
class Finding:
    rule: str
    severity: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "severity": self.severity, "detail": self.detail}


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity == "block" for f in self.findings)

    @property
    def worst(self) -> str:
        return max(
            (f.severity for f in self.findings), key=lambda s: SEVERITY_ORDER[s], default="info"
        )

    def add(self, rule: str, severity: str, detail: str) -> None:
        self.findings.append(Finding(rule=rule, severity=severity, detail=detail))

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "worst_severity": self.worst,
            "n_findings": len(self.findings),
            "findings": [f.as_dict() for f in self.findings],
        }


def audit(
    *,
    bus: MessageBus,
    registry: ToolRegistry,
    memo: str | None,
    citations: list[dict[str, Any]],
    budget: dict[str, Any],
    memory_quarantined: list[dict[str, Any]] | None = None,
) -> AuditReport:
    """Check a completed run against policy."""
    report = AuditReport()

    # --- the transcript is intact -------------------------------------------
    intact, broken = bus.verify_all()
    if not intact:
        report.add(
            "transcript_integrity",
            "block",
            f"messages {broken} do not verify; the transcript has been altered",
        )

    # --- the Advisor stayed inside its box ----------------------------------
    advisor_calls = [c for c in registry.calls if c["agent"] == "Advisor"]
    if advisor_calls:
        report.add(
            "advisor_tool_use",
            "block",
            f"the Advisor called {[c['tool'] for c in advisor_calls]}; it is granted no tools",
        )
    if registry.granted("Advisor"):
        report.add(
            "advisor_grants",
            "block",
            f"the Advisor has been granted tools: {sorted(registry.granted('Advisor'))}",
        )

    # --- nothing with side effects exists at all ----------------------------
    if side_effects := registry.side_effect_tools():
        report.add(
            "side_effect_tools",
            "block",
            f"tools with side effects are registered: {side_effects}",
        )

    # --- denied calls are worth knowing about -------------------------------
    for denial in registry.denials:
        report.add(
            "tool_denied",
            "warn",
            f"{denial['agent']} was refused '{denial['tool']}' ({denial['reason']})",
        )

    # --- the memo says only what it can support -----------------------------
    if memo:
        if match := ADVICE_LANGUAGE.search(memo):
            report.add(
                "advice_language",
                "block",
                f"the memo uses advice language: {match.group(0)!r}",
            )
        if not citations:
            report.add("citations", "block", "the memo cites nothing")
        if "not advice" not in memo.lower() and "information, not advice" not in memo.lower():
            report.add("advice_notice", "warn", "the memo does not carry the advice notice")

    # --- budget ---------------------------------------------------------------
    if budget.get("killed"):
        report.add("killed", "info", f"the run was stopped: {budget.get('kill_reason')}")
    if budget.get("requests_used", 0) >= budget.get("requests_limit", 1):
        report.add("budget_requests", "warn", "the run spent its whole request allowance")
    if budget.get("steps_used", 0) >= budget.get("steps_limit", 1):
        report.add("budget_steps", "warn", "the run used every step it was allowed")

    # --- memory ---------------------------------------------------------------
    for entry in memory_quarantined or []:
        report.add(
            "memory_quarantined",
            "warn",
            f"memory {entry['id']} was set aside: {entry.get('quarantine_reason')}",
        )

    if not report.findings:
        report.add("clean", "info", "no policy findings")
    return report
