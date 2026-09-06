"""The tools agents may call, and the registry that decides who may call what.

The important property is negative: the Advisor has no side-effect tools at all. Not "it is told
not to use them" — it is not given them, and the registry refuses the call if it tries. A model
cannot be prompted out of a capability it does not have.

Every tool is read-only in this build. There is no write tool, no transaction tool, no messaging
tool, and the tests assert that the set stays empty.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from finance.base import Warehouse


class ToolDenied(RuntimeError):
    """An agent asked for a tool it is not permitted to use."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    # A side-effecting tool changes something outside the run. None exist yet, and the flag is here
    # so that adding one is a visible, reviewable act rather than an accident.
    side_effects: bool = False

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.fn(*args, **kwargs)


@dataclass
class ToolRegistry:
    """Which agent may call which tool."""

    tools: dict[str, Tool] = field(default_factory=dict)
    grants: dict[str, set[str]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    denials: list[dict[str, Any]] = field(default_factory=list)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def grant(self, agent: str, names: list[str]) -> None:
        unknown = [n for n in names if n not in self.tools]
        if unknown:
            raise KeyError(f"cannot grant unregistered tools: {unknown}")
        self.grants[agent] = set(names)

    def granted(self, agent: str) -> set[str]:
        return set(self.grants.get(agent, set()))

    def side_effect_tools(self) -> list[str]:
        return sorted(name for name, tool in self.tools.items() if tool.side_effects)

    def call(self, agent: str, name: str, *args: Any, **kwargs: Any) -> Any:
        """Call a tool as an agent, refusing anything not granted."""
        if name not in self.tools:
            self.denials.append({"agent": agent, "tool": name, "reason": "no such tool"})
            raise ToolDenied(f"{agent} asked for '{name}', which does not exist")
        if name not in self.granted(agent):
            self.denials.append({"agent": agent, "tool": name, "reason": "not granted"})
            raise ToolDenied(
                f"{agent} is not permitted to call '{name}'. Its tools are: "
                f"{sorted(self.granted(agent)) or 'none'}"
            )
        result = self.tools[name](*args, **kwargs)
        self.calls.append({"agent": agent, "tool": name, "args": _describe(args, kwargs)})
        return result


def _describe(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    parts = [repr(a)[:60] for a in args] + [f"{k}={v!r}"[:60] for k, v in kwargs.items()]
    return ", ".join(parts)


def build_registry(wh: Warehouse) -> ToolRegistry:
    """The tool set for a run. Read-only, all of it."""
    from api import queries
    from api.deps import result
    from finance.dcf import project
    from finance.mortgage import affordability
    from finance.yields import Assumptions, net_yield

    provenance = wh.provenance()
    registry = ToolRegistry()

    def query_sql(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Run a read-only query.

        Statements that are not plain selects are refused. The connection is already read-only, so
        this is belt and braces rather than the only defence — but a clear refusal is more useful
        than a driver error.
        """
        lowered = " ".join(sql.lower().split())
        if not lowered.startswith(("select", "with")):
            raise ToolDenied("only select statements may be run")
        forbidden = (
            "insert ",
            "update ",
            "delete ",
            "drop ",
            "create ",
            "alter ",
            "attach ",
            "copy ",
        )
        if any(word in lowered for word in forbidden):
            raise ToolDenied("the query contains a statement that could change data")
        return wh.query(sql, params).frame.head(200).to_dicts()

    def area_summary(area_key: str) -> dict[str, Any]:
        """Headline figures for an area, as Kpi objects."""
        return {
            "area_key": area_key,
            "kpis": [k.model_dump(mode="json") for k in queries.area_kpis(wh, area_key)],
        }

    def yield_lookup(area_key: str) -> dict[str, Any]:
        """Published gross and net yields for an area's cells."""
        body = result("yield.json", provenance)
        rows = [r for r in body.get("table", []) if r["area_key"] == area_key]
        return {"area_key": area_key, "cells": rows, "assumptions": body.get("assumptions", [])}

    def index_lookup() -> dict[str, Any]:
        body = result("index.json", provenance)
        return {"annual": body.get("annual", []), "diagnostics": body.get("diagnostics", {})}

    def risk_score(area_key: str) -> dict[str, Any]:
        body = result("risk.json", provenance)
        row = next((r for r in body.get("areas", []) if r["area_key"] == area_key), None)
        return {"area_key": area_key, "risk": row, "weights": body.get("weights", {})}

    def anomaly_lookup(area_key: str | None = None) -> dict[str, Any]:
        body = result("risk.json", provenance)["anomalies"]
        examples = body.get("examples", [])
        if area_key:
            examples = [e for e in examples if e.get("area_key") == area_key]
        return {"rate": body.get("rate"), "by_rule": body.get("by_rule"), "examples": examples[:10]}

    def forecast_lookup(area_key: str) -> dict[str, Any]:
        body = result("forecast.json", provenance)
        row = next((r for r in body.get("areas", []) if r["area_key"] == area_key), None)
        return {"area_key": area_key, "forecast": row, "benchmark": body.get("benchmark")}

    def hedonic_card() -> dict[str, Any]:
        return result("hedonic.json", provenance).get("metrics", {})

    def dcf(
        price: float, annual_rent: float, sqm: float, years: int = 5, loan: float = 0.0
    ) -> dict[str, Any]:
        return project(
            price=price, annual_rent=annual_rent, sqm=sqm, years=years, loan_amount=loan
        ).as_dict()

    def mortgage(price: float, monthly_income: float) -> dict[str, Any]:
        out = affordability(price=price, monthly_income=monthly_income)
        return {
            "max_loan": out.max_loan,
            "deposit_required": out.deposit_required,
            "monthly_payment": out.monthly_payment,
            "binding_constraint": out.binding_constraint,
            "caveat": out.caveat,
        }

    def yield_for(price: float, annual_rent: float, sqm: float) -> dict[str, Any]:
        working = net_yield(annual_rent, price, sqm, Assumptions.load())
        return working or {"error": "a yield needs a positive price and rent"}

    for tool in (
        Tool("query_sql", "Run a read-only SQL query against the registry", query_sql),
        Tool("area_summary", "Headline KPIs for an area", area_summary),
        Tool("yield_lookup", "Published gross and net yields for an area", yield_lookup),
        Tool("index_lookup", "The repeat-sales index and its diagnostics", index_lookup),
        Tool("risk_score", "Risk score and component breakdown for an area", risk_score),
        Tool("anomaly_lookup", "Flagged transactions and why they were flagged", anomaly_lookup),
        Tool(
            "forecast_lookup",
            "Forecast for an area and how it scored against the naive",
            forecast_lookup,
        ),
        Tool("hedonic_predict", "The valuation model's accuracy card", hedonic_card),
        Tool("dcf", "Holding-period cash flows and IRR", dcf),
        Tool("mortgage", "Affordability under UAE lending caps", mortgage),
        Tool("yield_for", "Net yield for a specific price, rent and size", yield_for),
    ):
        registry.register(tool)

    registry.grant("Valuer", ["query_sql", "area_summary", "hedonic_predict", "index_lookup"])
    registry.grant("YieldAnalyst", ["query_sql", "yield_lookup", "yield_for", "dcf", "mortgage"])
    registry.grant("RiskAuditor", ["query_sql", "risk_score", "anomaly_lookup", "forecast_lookup"])
    # The Advisor writes the memo and gets nothing. It reasons over what the others found and over
    # the cited corpus, and it cannot reach past that.
    registry.grant("Advisor", [])
    registry.grant("Auditor", [])
    return registry
