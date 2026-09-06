"""The crew, and the one runtime they all run inside.

Five agents with different jobs and different tools, plus an Auditor that checks the result.

    Valuer        what is it worth, and against what comparison
    YieldAnalyst  what does it return, and under which assumptions
    RiskAuditor   what could go wrong, and how much of it is measurable
    Advisor       writes the memo from what the others found — and has no tools at all
    Auditor       checks the run against policy, whatever the outcome

The shape matters more than the agent count. The three analysts gather evidence with read-only
tools; the Advisor can only reason over what they wrote and over the cited corpus. It cannot query
the database, cannot recompute a number, and cannot reach anything outside the run. That is why
its memo can only restate figures the analysts already established, each with a source.

A run is bounded, its transcript is signed, and the Auditor sees every run including the ones that
failed.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.auditor import AuditReport, audit
from agents.budget import Budget, BudgetExceeded, KillSwitched
from agents.bus import MessageBus
from agents.memory import GuardedMemory
from agents.tools import ToolDenied, ToolRegistry, build_registry
from finance.base import DEFAULT_DB, Warehouse
from rag.ask import ask as run_ask
from rag.provider import LLMProvider, ProviderUnavailable
from rag.retriever import Retriever


@dataclass
class Finding:
    """One agent's contribution: a claim, its number, and where it came from."""

    agent: str
    label: str
    value: Any
    unit: str | None = None
    source: str | None = None
    sql: str | None = None
    n: int | None = None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "n": self.n,
            "note": self.note,
            "has_sql": bool(self.sql),
        }

    def sentence(self, index: int) -> str:
        """The finding as a citable sentence for the memo."""
        rendered = self.value
        if isinstance(rendered, float):
            # A count of 160 should read as 160, not 160.00; a percentage keeps its decimals.
            if rendered.is_integer() and (self.unit or "") not in {"%", "AED/sqm"}:
                rendered = f"{int(rendered):,}"
            elif abs(rendered) < 1000:
                rendered = f"{rendered:,.2f}"
            else:
                rendered = f"{rendered:,.0f}"
        unit = f" {self.unit}" if self.unit else ""
        sample = f", from {self.n:,} records" if self.n else ""
        return f"{self.label} is {rendered}{unit}{sample} [{index}]."


@dataclass
class RunResult:
    run_id: str
    goal: str
    status: str
    findings: list[Finding]
    memo: str | None
    citations: list[dict[str, Any]]
    disagreements: list[dict[str, Any]]
    audit: AuditReport
    budget: dict[str, Any]
    transcript: list[dict[str, Any]]
    provenance: str
    started_at: str
    finished_at: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "status": self.status,
            "provenance": self.provenance,
            "findings": [f.as_dict() for f in self.findings],
            "memo": self.memo,
            "citations": self.citations,
            "disagreements": self.disagreements,
            "audit": self.audit.as_dict(),
            "budget": self.budget,
            "transcript": self.transcript,
            "notes": self.notes,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "notice": (
                "Produced by an automated crew from published Dubai Land Department data. "
                "Information, not advice, and no transaction can be carried out."
            ),
        }


class Agent:
    """Base class. Every agent works through the runtime, never around it."""

    name = "Agent"

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    def tool(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return self.runtime.call_tool(self.name, name, *args, **kwargs)

    def say(self, kind: str, body: dict[str, Any]) -> None:
        self.runtime.bus.publish(self.name, kind, body)

    def run(self, area_key: str) -> list[Finding]:  # pragma: no cover - overridden
        raise NotImplementedError


class Valuer(Agent):
    name = "Valuer"

    def run(self, area_key: str) -> list[Finding]:
        findings: list[Finding] = []
        summary = self.tool("area_summary", area_key)
        for kpi in summary["kpis"]:
            if kpi["value"] is None:
                continue
            findings.append(
                Finding(
                    agent=self.name,
                    label=kpi["label"],
                    value=kpi["value"],
                    unit=kpi["unit"],
                    source=f"registry query {kpi['sql_hash']}",
                    sql=kpi["sql"],
                    n=kpi["n"],
                    note=f"confidence {kpi['confidence']}",
                )
            )

        card = self.tool("hedonic_predict")
        if card.get("test"):
            findings.append(
                Finding(
                    agent=self.name,
                    label="Valuation model error on unseen data",
                    value=round(card["test"]["mape"] * 100, 1),
                    unit="%",
                    source="hedonic model card",
                    n=card.get("n_test"),
                    note=(
                        f"against a {card['baseline']['mape'] * 100:.1f}% baseline"
                        if card.get("baseline")
                        else None
                    ),
                )
            )

        index = self.tool("index_lookup")
        recent = [row for row in index.get("annual", []) if row.get("growth") is not None]
        if recent:
            last = recent[-1]
            findings.append(
                Finding(
                    agent=self.name,
                    label=f"Repeat-sales index change in {last['year']}",
                    value=round(last["growth"] * 100, 1),
                    unit="%",
                    source="repeat-sales index",
                    n=last.get("n_pairs"),
                )
            )

        self.say("findings", {"count": len(findings), "labels": [f.label for f in findings]})
        return findings


class YieldAnalyst(Agent):
    name = "YieldAnalyst"

    def run(self, area_key: str) -> list[Finding]:
        findings: list[Finding] = []
        published = self.tool("yield_lookup", area_key)
        cells = [c for c in published["cells"] if c.get("sufficient")]

        if cells:
            best = max(cells, key=lambda c: c["net_yield"])
            findings.append(
                Finding(
                    agent=self.name,
                    label="Gross yield for the strongest cell",
                    value=round(best["gross_yield"] * 100, 2),
                    unit="%",
                    source="Ejari rents over registry sale prices",
                    n=best["n"],
                    note=f"{best['property_type']}, {best['rooms']} bedrooms",
                )
            )
            findings.append(
                Finding(
                    agent=self.name,
                    label="Net yield for the same cell",
                    value=round(best["net_yield"] * 100, 2),
                    unit="%",
                    source="net of vacancy, service charge, management and amortised fees",
                    n=best["n"],
                )
            )
            projection = self.tool(
                "dcf",
                float(best["median_price"]),
                float(best["median_rent"]),
                float(best["median_sqm"] or 90),
                5,
                float(best["median_price"]) * 0.6,
            )
            if projection.get("irr") is not None:
                findings.append(
                    Finding(
                        agent=self.name,
                        label="Five-year IRR at 60% loan-to-value",
                        value=round(projection["irr"] * 100, 2),
                        unit="%",
                        source="holding-period cash-flow projection",
                        note="a projection under stated assumptions, not a forecast",
                    )
                )
        else:
            findings.append(
                Finding(
                    agent=self.name,
                    label="Yield",
                    value=None,
                    source="Ejari and registry",
                    note="no cell in this area has enough sales and contracts to publish a yield",
                )
            )

        self.say("findings", {"count": len(findings), "cells_considered": len(cells)})
        return findings


class RiskAuditor(Agent):
    name = "RiskAuditor"

    def run(self, area_key: str) -> list[Finding]:
        findings: list[Finding] = []
        risk = self.tool("risk_score", area_key)
        row = risk.get("risk")

        if row and row.get("score") is not None:
            findings.append(
                Finding(
                    agent=self.name,
                    label="Risk score out of 100",
                    value=row["score"],
                    source="weighted risk model",
                    n=row.get("n"),
                    note="; ".join(
                        f"{k} {v:.0f}"
                        for k, v in (row.get("components") or {}).items()
                        if v is not None
                    ),
                )
            )
        elif row:
            findings.append(
                Finding(
                    agent=self.name,
                    label="Risk score",
                    value=None,
                    source="weighted risk model",
                    n=row.get("n"),
                    note=row.get("reason"),
                )
            )

        anomalies = self.tool("anomaly_lookup", area_key)
        if anomalies.get("rate") is not None:
            findings.append(
                Finding(
                    agent=self.name,
                    label="Share of transactions flagged as unusual",
                    value=round(anomalies["rate"] * 100, 2),
                    unit="%",
                    source="anomaly detection across three rules",
                )
            )

        forecast = self.tool("forecast_lookup", area_key)
        row = forecast.get("forecast")
        if row and row.get("beats_naive") is not None:
            findings.append(
                Finding(
                    agent=self.name,
                    label="Forecast error against the naive benchmark",
                    value=round(row["backtest_mape"] * 100, 1),
                    unit="%",
                    source="backtest on a held-out year",
                    note=(
                        f"the benchmark scored {row['naive_mape'] * 100:.1f}%; the model "
                        f"{'beat' if row['beats_naive'] else 'did not beat'} it"
                    ),
                )
            )

        self.say("findings", {"count": len(findings)})
        return findings


class Advisor(Agent):
    """Writes the memo. Has no tools, by construction.

    It works from what the analysts wrote and from the cited corpus, so every number in its memo is
    one another agent already established with a query behind it.
    """

    name = "Advisor"

    def compose(
        self, area_key: str, findings: list[Finding], disagreements: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        citations: list[dict[str, Any]] = []
        lines: list[str] = [f"# Investment memo — {area_key}", ""]

        lines.append("## What the registry shows")
        lines.append("")
        usable = [f for f in findings if f.value is not None]
        for finding in usable:
            citations.append(
                {
                    "n": len(citations) + 1,
                    "title": finding.label,
                    "source": finding.source or finding.agent,
                    "agent": finding.agent,
                    "kind": "sql" if finding.sql else "model",
                    "n_records": finding.n,
                }
            )
            lines.append(finding.sentence(len(citations)))
        if not usable:
            lines.append(
                "No figure in this area met the minimum sample size, so nothing is reported here."
            )

        missing = [f for f in findings if f.value is None]
        if missing:
            lines += ["", "## What could not be established", ""]
            for finding in missing:
                lines.append(f"- {finding.label}: {finding.note or 'not available'}")

        if disagreements:
            lines += ["", "## Where the analysts disagree", ""]
            for item in disagreements:
                lines.append(f"- {item['summary']}")

        lines += [
            "",
            "## What would change this view",
            "",
            "- Loading per-building service charges, which are currently an estimate and are the "
            "largest single input to the net figure.",
            "- A larger sample in the thinner cells, several of which are suppressed rather than "
            "published.",
            "- Verifying the lending caps against the Central Bank's own published rules, which "
            "are presently carried as assumptions.",
            "",
            "---",
            "",
            "*Information, not advice. Every figure above comes from published Dubai Land "
            "Department data by way of a recorded query. YIELDMAP cannot carry out any "
            "transaction.*",
        ]
        self.say("memo", {"citations": len(citations), "length": sum(len(x) for x in lines)})
        return "\n".join(lines), citations


class Runtime:
    """One place where budgets, the bus, memory and the tools all meet."""

    def __init__(
        self,
        *,
        db_path: Path = DEFAULT_DB,
        budget: Budget | None = None,
        memory: GuardedMemory | None = None,
        provider: LLMProvider | None = None,
        retriever: Retriever | None = None,
    ) -> None:
        self.run_id = uuid.uuid4().hex[:12]
        self.budget = budget or Budget()
        self.bus = MessageBus(self.run_id)
        self.memory = memory or GuardedMemory()
        self.provider = provider or LLMProvider.from_env()
        self.retriever = retriever
        self.warehouse = Warehouse(db_path)
        self.registry: ToolRegistry = build_registry(self.warehouse)
        self.notes: list[str] = []

    def close(self) -> None:
        self.warehouse.close()

    def call_tool(self, agent: str, name: str, *args: Any, **kwargs: Any) -> Any:
        self.budget.check()
        self.budget.spend_step()
        result = self.registry.call(agent, name, *args, **kwargs)
        self.bus.publish(agent, "tool_call", {"tool": name})
        return result

    def ask_corpus(self, question: str) -> dict[str, Any] | None:
        """The Advisor's only route outside the run, and it is read-only and cited."""
        if self.retriever is None:
            return None
        try:
            self.budget.check()
            self.budget.spend_request()
            answer = run_ask(question, retriever=self.retriever, provider=self.provider)
            return answer.as_dict()
        except (ProviderUnavailable, BudgetExceeded, KillSwitched) as exc:
            self.notes.append(f"corpus lookup skipped: {exc}")
            return None


def find_disagreements(findings: list[Finding]) -> list[dict[str, Any]]:
    """Where the Valuer's read and the RiskAuditor's read point different ways.

    Surfacing a disagreement is more useful than averaging it away: a strong yield alongside a high
    risk score is the interesting case, and a memo that reported only one of them would be worse
    than one that reports both and says they conflict.
    """
    by_agent: dict[str, dict[str, Finding]] = {}
    for finding in findings:
        by_agent.setdefault(finding.agent, {})[finding.label] = finding

    out: list[dict[str, Any]] = []
    risk = by_agent.get("RiskAuditor", {}).get("Risk score out of 100")
    net = by_agent.get("YieldAnalyst", {}).get("Net yield for the same cell")

    if risk and net and risk.value is not None and net.value is not None:
        if risk.value >= 50 and net.value >= 6:
            out.append(
                {
                    "between": ["RiskAuditor", "YieldAnalyst"],
                    "summary": (
                        f"The yield is high at {net.value:.2f}% while the risk score is also high "
                        f"at {risk.value:.0f} out of 100. A yield of that size is usually "
                        f"compensation for the risk rather than a free gain."
                    ),
                }
            )
        elif risk.value <= 25 and net.value <= 3:
            out.append(
                {
                    "between": ["RiskAuditor", "YieldAnalyst"],
                    "summary": (
                        f"Risk is low at {risk.value:.0f} out of 100 but so is the net yield at "
                        f"{net.value:.2f}%. The area looks stable and unrewarding on income alone."
                    ),
                }
            )

    forecast = by_agent.get("RiskAuditor", {}).get("Forecast error against the naive benchmark")
    if forecast and forecast.note and "did not beat" in forecast.note:
        out.append(
            {
                "between": ["RiskAuditor", "Valuer"],
                "summary": (
                    "The forecast for this area failed to beat a naive benchmark, so any "
                    "projection of its direction should carry less weight than the recorded "
                    "figures above."
                ),
            }
        )
    return out


def run_crew(
    area_key: str,
    *,
    db_path: Path = DEFAULT_DB,
    budget: Budget | None = None,
    memory: GuardedMemory | None = None,
    provider: LLMProvider | None = None,
    retriever: Retriever | None = None,
) -> RunResult:
    """Run the crew over one area and return the memo, the evidence and the audit."""
    started = datetime.now(UTC).isoformat(timespec="seconds")
    runtime = Runtime(
        db_path=db_path, budget=budget, memory=memory, provider=provider, retriever=retriever
    )
    findings: list[Finding] = []
    memo: str | None = None
    citations: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    status = "succeeded"

    try:
        runtime.bus.publish("Runtime", "start", {"area_key": area_key})
        for agent_class in (Valuer, YieldAnalyst, RiskAuditor):
            runtime.budget.check()
            findings.extend(agent_class(runtime).run(area_key))

        disagreements = find_disagreements(findings)
        memo, citations = Advisor(runtime).compose(area_key, findings, disagreements)

    except BudgetExceeded as exc:
        status = "over_budget"
        runtime.notes.append(str(exc))
        runtime.bus.publish("Runtime", "over_budget", {"reason": str(exc)})
    except KillSwitched as exc:
        status = "killed"
        runtime.notes.append(str(exc))
        runtime.bus.publish("Runtime", "killed", {"reason": str(exc)})
    except ToolDenied as exc:
        status = "failed"
        runtime.notes.append(f"tool denied: {exc}")
        runtime.bus.publish("Runtime", "denied", {"reason": str(exc)})
    except Exception as exc:  # noqa: BLE001 - an audited failure is better than a lost run
        status = "failed"
        runtime.notes.append(f"{type(exc).__name__}: {exc}")
        runtime.bus.publish("Runtime", "failed", {"reason": str(exc)})

    # The Auditor runs whatever happened. The runs worth inspecting are the ones that went wrong.
    report = audit(
        bus=runtime.bus,
        registry=runtime.registry,
        memo=memo,
        citations=citations,
        budget=runtime.budget.as_dict(),
        memory_quarantined=[e.as_dict() for e in runtime.memory.quarantined()],
    )
    if report.blocked:
        memo = None
        status = "blocked" if status == "succeeded" else status
        runtime.notes.append("the memo was withheld because the audit blocked it")

    provenance = runtime.warehouse.provenance()
    result = RunResult(
        run_id=runtime.run_id,
        goal=f"assess {area_key}",
        status=status,
        findings=findings,
        memo=memo,
        citations=citations,
        disagreements=disagreements,
        audit=report,
        budget=runtime.budget.as_dict(),
        transcript=runtime.bus.transcript(),
        provenance=provenance,
        started_at=started,
        finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
        notes=runtime.notes,
    )
    runtime.close()
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("area", nargs="?", default="marsa dubai")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    result = run_crew(args.area, db_path=args.db)
    print(f"run {result.run_id}: {result.status} ({result.provenance})")
    print(f"  findings   {len(result.findings)}")
    print(f"  citations  {len(result.citations)}")
    print(
        f"  budget     {result.budget['requests_used']}/{result.budget['requests_limit']} requests, "
        f"{result.budget['steps_used']}/{result.budget['steps_limit']} steps"
    )
    print(f"  audit      {result.audit.worst} ({result.audit.as_dict()['n_findings']} findings)")
    for finding in result.audit.findings:
        print(f"    [{finding.severity}] {finding.rule}: {finding.detail}")
    if result.memo:
        print("\n" + result.memo[:900])
    print(json.dumps({"disagreements": result.disagreements}, indent=2)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
