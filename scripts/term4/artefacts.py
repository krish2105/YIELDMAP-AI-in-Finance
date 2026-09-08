"""Read `docs/results/` and turn it into the rows the report and the deck render.

One loader for both documents, so a figure cannot say one thing in the report and another on a
slide: they are the same dictionary, formatted twice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS = ROOT / "docs" / "results"
SYNTHETIC = RESULTS / "synthetic"

MISSING = "not measured"


def short_path(path: Path) -> str:
    """A repository-relative path when it is one, and the whole path when it is not.

    Both generators accept --out, so the path they are asked to write is not always inside the
    repository — a bare relative_to() raises on a temporary directory, which is how the tests
    found this.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load(name: str) -> dict[str, Any] | None:
    """A results file, or None when the model behind it has not been run.

    None rather than an exception: a missing artefact is a fact the documents report, not a
    failure that stops them being written. It becomes "not measured" in the table.
    """
    for base in (RESULTS, SYNTHETIC):
        path = base / name
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                return None
    return None


def pct(value: float | None, places: int = 1) -> str:
    return MISSING if value is None else f"{value * 100:.{places}f}%"


def num(value: float | None, places: int = 0) -> str:
    return MISSING if value is None else f"{value:,.{places}f}"


@dataclass
class Row:
    """One measured line. `provenance` is carried, never inferred at render time."""

    label: str
    measured: str
    target: str = "—"
    provenance: str = "REAL"
    source: str = ""


@dataclass
class Bundle:
    """Everything both documents need, with provenance attached to each figure."""

    rows_models: list[Row] = field(default_factory=list)
    rows_retrieval: list[Row] = field(default_factory=list)
    rows_engineering: list[Row] = field(default_factory=list)
    rows_governance: list[Row] = field(default_factory=list)
    synthetic_params: dict[str, Any] | None = None
    unit_economics: dict[str, Any] | None = None
    redteam: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None
    probe: dict[str, Any] | None = None
    relevance: dict[str, Any] | None = None
    any_synthetic: bool = False


def _model_rows() -> list[Row]:
    rows: list[Row] = []

    h = load("hedonic.json")
    if h:
        m = h["metrics"]
        rows.append(
            Row(
                "Hedonic valuation — MAPE on a time-split holdout",
                f"{pct(m['test']['mape'])} against a {pct(m['baseline']['mape'])} baseline "
                f"({pct(m['skill_vs_baseline'])} skill), at an estimated "
                f"{pct(m['estimated_noise_floor_mape'])} noise floor",
                "12% on real data",
                h.get("provenance", "?"),
                "hedonic.json",
            )
        )
        rows.append(
            Row(
                "Hedonic — training and holdout size",
                f"{num(m['n_train'])} train / {num(m['n_test'])} holdout, split by time",
                "—",
                h.get("provenance", "?"),
                "hedonic.json",
            )
        )

    i = load("index.json")
    if i:
        d = i["diagnostics"]
        rows.append(
            Row(
                "Repeat-sales index — matched pairs",
                f"{num(d['n_pairs'])} pairs over {d['n_periods']} months; "
                f"{d['periods_dropped_as_disconnected']} periods dropped as disconnected",
                "reproduces direction of travel",
                i.get("provenance", "?"),
                "index.json",
            )
        )

    y = load("yield.json")
    if y:
        s = y["summary"]
        rows.append(
            Row(
                "Yield — median gross and net",
                f"gross {pct(s['median_gross_yield'], 2)}, net {pct(s['median_net_yield'], 2)}, "
                f"spread {pct(s['median_spread'], 2)}",
                "net below gross always",
                y.get("provenance", "?"),
                "yield.json",
            )
        )
        rows.append(
            Row(
                "Yield — cells suppressed as too thin",
                f"{s['cells_suppressed_for_thin_data']} of {s['cells']} suppressed; "
                f"{s['cells_published']} published",
                "small n never shown as a number",
                y.get("provenance", "?"),
                "yield.json",
            )
        )

    f = load("forecast.json")
    if f:
        s = f["summary"]
        rows.append(
            Row(
                "Forecast versus seasonal naive",
                f"beats the benchmark on {s['areas_beating_naive']}/{s['areas_compared']} areas "
                f"({pct(s['win_rate'])}); {pct(s['median_model_mape'])} against "
                f"{pct(s['median_naive_mape'])} error",
                "60% of areas",
                f.get("provenance", "?"),
                "forecast.json",
            )
        )

    r = load("risk.json")
    if r:
        a, s = r["anomalies"], r["summary"]
        rows.append(
            Row(
                "Risk and anomalies",
                f"{num(a['flagged'])} of {num(a['total_transactions'])} flagged "
                f"({pct(a['rate'], 2)}); {s['areas_scored']} areas scored",
                "score in [0, 100], monotone",
                r.get("provenance", "?"),
                "risk.json",
            )
        )

    p = load("portfolio.json")
    if p:
        b, dv = p["blended_yield"], p["diversification"]
        rows.append(
            Row(
                "Portfolio — blended yield and independent positions",
                f"gross {pct(b['gross'], 2)}, net {pct(b['net'], 2)}; "
                f"{dv['naive_effective_holdings']} effective holdings fall to "
                f"{dv['correlation_adjusted']} once correlation is taken out",
                "correlation never ignored",
                p.get("provenance", "?"),
                "portfolio.json",
            )
        )

    d = load("dcf.json")
    if d:
        levered = next(
            (s for s in d["scenarios"] if "lever" in str(s.get("label", "")).lower()), None
        )
        rows.append(
            Row(
                "Mortgage and DCF",
                f"{len(d['scenarios'])} scenarios from an anchor of "
                f"AED {num(d['anchor']['price'])} over {d['anchor']['years']} years"
                + (f"; {levered['label']}" if levered else ""),
                "IRR matches a hand-computed case",
                d.get("provenance", "?"),
                "dcf.json",
            )
        )

    dev = load("developers.json")
    if dev:
        s = dev["summary"]
        rows.append(
            Row(
                "Developer league table",
                f"{s['developers']} projects ranked on price premium against their own area "
                "and month",
                "location and timing held constant",
                dev.get("provenance", "?"),
                "developers.json",
            )
        )
    return rows


def _retrieval_rows() -> list[Row]:
    rows: list[Row] = []
    e = load("rag_eval.json")
    if e:
        prov = e.get("provenance", "?")
        rows.append(
            Row(
                "Retrieval — recall@5 / recall@1 / MRR",
                f"{e['recall_at_k']:.2f} / {e['recall_at_1']:.2f} / {e['mrr']:.2f} over "
                f"{e['n_answerable']} answerable cases in three languages",
                f"gated at {e['recall_target']} / {e['recall_at_1_target']}",
                prov,
                "rag_eval.json",
            )
        )
        rows.append(
            Row(
                "Faithfulness — every sentence traceable to a retrieved source",
                f"{e['faithfulness']:.2f}",
                f"gated at {e['faithfulness_target']}",
                prov,
                "rag_eval.json",
            )
        )
        rows.append(
            Row(
                "Corpus size",
                f"{e['corpus']['chunks']} chunks from {e['corpus']['documents']} documents and "
                f"{e['corpus']['facts']} area facts",
                "small enough that recall@5 is easy",
                prov,
                "rag_eval.json",
            )
        )
        rows.append(
            Row(
                "Out-of-scope questions answered rather than declined",
                f"{len(e.get('answered_out_of_scope', []))} of {e['n_out_of_scope']}",
                "not gated — see limitations",
                prov,
                "rag_eval.json",
            )
        )
        rows.append(
            Row(
                "Retrieval backend actually scored",
                f"{e['retrieval_backend']}"
                + (" (degraded: no embedding provider reachable)" if e.get("degraded") else ""),
                "hybrid BM25 + embeddings",
                prov,
                "rag_eval.json",
            )
        )
    return rows


def _engineering_rows() -> list[Row]:
    rows: list[Row] = []

    c = load("coverage.json")
    if c:
        rows.append(
            Row(
                "Python line coverage",
                f"{c['overall_percent']:.2f}% of {num(c['statements'])} statements; "
                f"{len(c['critical_modules'])} rule-enforcing modules held to "
                f"{c['critical_floor']:.0f}%",
                f"{c['overall_floor']:.0f}% overall",
                c.get("provenance", "?"),
                "coverage.json",
            )
        )

    for project, target in (("desktop", "60"), ("phone", "30")):
        f = load(f"fps_{project}.json")
        if f:
            rows.append(
                Row(
                    f"Frame rate — {project} ({f['renderer']})",
                    f"{f['fps']} fps while orbiting the 3D city",
                    f"{target} fps",
                    f.get("provenance", "?"),
                    f"fps_{project}.json",
                )
            )
        a = load(f"accessibility_{project}.json")
        if a:
            rows.append(
                Row(
                    f"Accessibility — {project}",
                    f"{a['violations']} violations across {a['pages']} pages, {a['standard']}",
                    "no serious violations",
                    a.get("provenance", "?"),
                    f"accessibility_{project}.json",
                )
            )

    b = load("bundle.json")
    if b:
        rows.append(
            Row(
                "Page weight",
                f"heaviest route {b['heaviest_page']} at {b['heaviest_brotli_kb']} KB brotli; "
                "three.js on none of them",
                "gated at 340 KB",
                b.get("provenance", "?"),
                "bundle.json",
            )
        )

    p = load("palette.json")
    if p:
        rows.append(
            Row(
                "Colour — computed, not eyeballed",
                f"{p['palettes']} palettes checked for colourblind separation and contrast; "
                f"{p['failed']} failed",
                "0 failures",
                p.get("provenance", "?"),
                "palette.json",
            )
        )

    u = load("unit_economics.json")
    if u:
        binding = u["scenarios"].get("a hundred daily users", {}).get("binding_constraint", "—")
        rows.append(
            Row(
                "Running cost",
                f"US${u['monthly_cost_usd']:.2f}/month; at a hundred daily users the free tier "
                f"binds first on {binding}",
                "stays free at course scale",
                u.get("provenance", "?"),
                "unit_economics.json",
            )
        )
    return rows


def _governance_rows() -> list[Row]:
    rows: list[Row] = []
    r = load("redteam.json")
    if r:
        rows.append(
            Row(
                "Red team — OWASP Agentic Security Initiative",
                f"{r['controls_held']}/{r['attacks_run']} controls held across "
                f"{len(r['threat_register'])} registered threats",
                "every attack fails to land",
                r.get("provenance", "?"),
                "redteam.json",
            )
        )
    rel = load("relevance_floor.json")
    if rel:
        rows.append(
            Row(
                "Structural refusal threshold",
                "measured and rejected: no signal separates out-of-scope from in-scope on this "
                "corpus, so refusal is enforced at the answering stage instead",
                "a threshold, if one exists",
                rel.get("provenance", "?"),
                "relevance_floor.json",
            )
        )
    a = load("source_archive.json")
    if a:
        rows.append(
            Row(
                "Cited pages archived with a hash",
                f"{a['archived']} of {a['attempted']} fetched and stored with a SHA-256",
                "a citation points at a fixed thing",
                a.get("provenance", "?"),
                "source_archive.json",
            )
        )
    return rows


def collect() -> Bundle:
    b = Bundle(
        rows_models=_model_rows(),
        rows_retrieval=_retrieval_rows(),
        rows_engineering=_engineering_rows(),
        rows_governance=_governance_rows(),
        synthetic_params=load("synthetic_params.json"),
        unit_economics=load("unit_economics.json"),
        redteam=load("redteam.json"),
        coverage=load("coverage.json"),
        probe=load("source_probe.json"),
        relevance=load("relevance_floor.json"),
    )
    every = b.rows_models + b.rows_retrieval + b.rows_engineering + b.rows_governance
    b.any_synthetic = any(r.provenance != "REAL" for r in every)
    return b
