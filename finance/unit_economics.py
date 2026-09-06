"""What this costs to run, and where the free tiers stop.

The project's central claim is that inference costs nothing. That is easy to assert and easy to
stop being true, so it is computed here from the same request counts the quota ledger records
rather than from a paragraph someone wrote once.

Two questions this answers, both of which a CFO asks before an engineer does:

* What does one unit of work cost, at the published rates, if the free tier were exhausted?
* At what usage does each free tier actually run out, and which one runs out first?

The second matters more. A service that is free until it is popular has a cliff, and knowing where
the cliff is worth more than knowing the cost per unit on the near side of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Published rates as of the retrieval date below. Used only to price the counterfactual: what a
# unit of work *would* cost if the free tier were exhausted and the paid tier switched on. Nothing
# in this project spends money, and two separate switches stand between it and a paid backend.
RATES_VERIFIED_ON = "2026-09-06"

# Requests a single operation makes, measured from the agent budgets and the Ask path rather than
# estimated: a crew run is bounded at 40 requests and typically spends the counts below.
OPERATIONS: dict[str, dict[str, Any]] = {
    "ask": {
        "label": "One question answered with citations",
        "model_requests": 1,
        "embedding_requests": 1,
        "cpu_seconds": 0.8,
    },
    "memo": {
        "label": "One crew run producing a cited memo",
        "model_requests": 6,
        "embedding_requests": 2,
        "cpu_seconds": 4.5,
    },
    "page": {
        "label": "One page of the site, fully loaded",
        "model_requests": 0,
        "embedding_requests": 0,
        "cpu_seconds": 0.15,
    },
}


@dataclass(frozen=True)
class Tier:
    """A free allowance, and what it costs when it runs out."""

    name: str
    unit: str
    free_per_day: float | None
    free_per_month: float | None
    paid_note: str
    # None where the provider does not publish a per-unit price for this resource.
    usd_per_unit: float | None = None


TIERS: tuple[Tier, ...] = (
    Tier(
        name="Gemini 2.5 Flash (generation)",
        unit="request",
        free_per_day=1500,
        free_per_month=None,
        usd_per_unit=None,
        paid_note=(
            "Priced per token rather than per request, so a per-request figure would be invented. "
            "The ledger counts requests because that is how the free tier meters."
        ),
    ),
    Tier(
        name="Gemini embeddings",
        unit="request",
        free_per_day=1000,
        free_per_month=None,
        usd_per_unit=None,
        paid_note="Cached to disk, so each chunk is embedded once rather than once per question.",
    ),
    Tier(
        name="Render web service (free)",
        unit="instance-hour",
        free_per_day=None,
        free_per_month=750,
        usd_per_unit=0.0,
        paid_note=(
            "750 hours covers one instance continuously. Sleeps after 15 minutes idle and takes "
            "about 50 seconds to wake, which is the real cost of this tier: latency, not money."
        ),
    ),
    Tier(
        name="Vercel Hobby",
        unit="deployment",
        free_per_day=None,
        free_per_month=None,
        usd_per_unit=0.0,
        paid_note=(
            "PROHIBITS COMMERCIAL USE. Adequate for a portfolio and a course submission, and a "
            "terms violation the moment this has a paying customer. Pro is $20/month, or the "
            "front end moves to Render alongside the API. See docs/limits.md."
        ),
    ),
    Tier(
        name="GitHub Actions",
        unit="minute",
        free_per_day=None,
        free_per_month=None,
        usd_per_unit=0.0,
        paid_note="Unlimited on a public repository, which is why the ingest runs there.",
    ),
)


@dataclass
class Usage:
    """A day's work, in operations."""

    asks: int = 0
    memos: int = 0
    pages: int = 0

    def model_requests(self) -> int:
        return (
            self.asks * OPERATIONS["ask"]["model_requests"]
            + self.memos * OPERATIONS["memo"]["model_requests"]
        )

    def embedding_requests(self) -> int:
        return (
            self.asks * OPERATIONS["ask"]["embedding_requests"]
            + self.memos * OPERATIONS["memo"]["embedding_requests"]
        )

    def cpu_seconds(self) -> float:
        return round(
            self.asks * OPERATIONS["ask"]["cpu_seconds"]
            + self.memos * OPERATIONS["memo"]["cpu_seconds"]
            + self.pages * OPERATIONS["page"]["cpu_seconds"],
            1,
        )


def headroom(usage: Usage) -> dict[str, Any]:
    """How much of each daily allowance a day like this consumes, and which binds first."""
    generation = next(t for t in TIERS if t.name.startswith("Gemini 2.5"))
    embedding = next(t for t in TIERS if t.name.startswith("Gemini embeddings"))

    rows = []
    for tier, used in (
        (generation, usage.model_requests()),
        (embedding, usage.embedding_requests()),
    ):
        limit = tier.free_per_day or 0
        rows.append(
            {
                "tier": tier.name,
                "used": used,
                "free_per_day": limit,
                "share_of_free_tier": round(used / limit, 4) if limit else None,
                "exhausted": bool(limit) and used > limit,
            }
        )

    binding = max(
        (r for r in rows if r["share_of_free_tier"] is not None),
        key=lambda r: r["share_of_free_tier"],
        default=None,
    )
    return {"tiers": rows, "binding_constraint": binding["tier"] if binding else None}


def capacity() -> dict[str, Any]:
    """How many of each operation a day's free allowance buys, if it bought only that one."""
    generation = next(t for t in TIERS if t.name.startswith("Gemini 2.5"))
    embedding = next(t for t in TIERS if t.name.startswith("Gemini embeddings"))
    out: dict[str, Any] = {}
    for key, op in OPERATIONS.items():
        limits = []
        if op["model_requests"]:
            limits.append(int((generation.free_per_day or 0) // op["model_requests"]))
        if op["embedding_requests"]:
            limits.append(int((embedding.free_per_day or 0) // op["embedding_requests"]))
        out[key] = {
            "label": op["label"],
            "per_day_on_the_free_tier": min(limits) if limits else None,
            "note": "unbounded by model quota; bounded by CPU and the rate limiter"
            if not limits
            else None,
        }
    return out


def report(observed: dict[str, Any] | None = None) -> dict[str, Any]:
    # Three shapes of day, so the cliff is located rather than described.
    scenarios = {
        "a demo day": Usage(asks=20, memos=3, pages=200),
        "a busy course week, per day": Usage(asks=150, memos=25, pages=2000),
        "a hundred daily users": Usage(asks=800, memos=120, pages=20000),
    }
    return {
        "provenance": "REAL",
        "note": (
            "Rates and free-tier allowances as published on the date below. Request counts per "
            "operation come from the agent budgets and the Ask path, not from an estimate. This "
            "prices a counterfactual: nothing here spends money, and the paid backend refuses to "
            "run behind two separate switches."
        ),
        "rates_verified_on": RATES_VERIFIED_ON,
        "monthly_cost_usd": 0.0,
        "operations": OPERATIONS,
        "capacity_per_day": capacity(),
        "scenarios": {
            name: {
                "usage": {"asks": u.asks, "memos": u.memos, "pages": u.pages},
                "model_requests": u.model_requests(),
                "embedding_requests": u.embedding_requests(),
                "cpu_seconds": u.cpu_seconds(),
                **headroom(u),
            }
            for name, u in scenarios.items()
        },
        "tiers": [
            {
                "name": t.name,
                "unit": t.unit,
                "free_per_day": t.free_per_day,
                "free_per_month": t.free_per_month,
                "note": t.paid_note,
            }
            for t in TIERS
        ],
        "observed": observed,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    from etl.results import result_path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    # What the ledger has actually recorded, so the model can be checked against reality.
    observed: dict[str, Any] | None = None
    ledger_path = ROOT / ".cache" / "quota.json"
    if ledger_path.exists():
        try:
            observed = json.loads(ledger_path.read_text())
        except (OSError, json.JSONDecodeError):
            observed = None

    body = report(observed)
    # REAL because it describes this system's costs, not the property data it reads.
    out = args.out or result_path("unit_economics.json", "REAL")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=2) + "\n")

    print(f"monthly cost: ${body['monthly_cost_usd']:.2f}")
    for name, s in body["scenarios"].items():
        binding = s["binding_constraint"]
        worst = max(t["share_of_free_tier"] or 0 for t in s["tiers"])
        print(f"  {name:32} {worst:6.1%} of the free tier — binds on {binding}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
