"""Generate a schema-faithful stand-in for the DLD drop.

This is rung three of the data ladder, used only when the publisher cannot be reached from either
the sandbox or a GitHub Actions runner. It exists so the models, the API and the interface can be
built and tested; it is not evidence about Dubai and must never be presented as such.

Three things keep it honest:

* every row carries ``provenance = 'SYNTHETIC'``, which the API surfaces and the interface banners;
* the generator is seeded, so any figure computed from it is reproducible from the seed plus the
  query, which is what the traceability rule actually asks for;
* ``scripts/guard_synthetic.py`` fails the build if a synthetic row can reach a Term 4 artefact.

The structure is plausible rather than arbitrary — area price levels differ, prices trend and have
seasonality, off-plan share varies, yields sit in a believable band, and a known number of
anomalies are planted. Plausible structure matters because a model tested on structureless noise
is not tested at all. The *levels* are invented and are not claims about the real market.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from etl.results import result_path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEED = 217  # the course code, so the seed is memorable and stated in the report

# Shape parameters. Every one of these is an invented assumption and is written to
# docs/results/synthetic_params.json alongside the data so nothing here is a hidden constant.
PARAMS: dict[str, Any] = {
    "start_year": 2014,
    "end_year": 2025,
    "base_ppsqm_range": [7_500, 34_000],
    "annual_drift_by_year": {
        "2014": 0.04,
        "2015": -0.03,
        "2016": -0.05,
        "2017": -0.04,
        "2018": -0.06,
        "2019": -0.05,
        "2020": -0.09,
        "2021": 0.10,
        "2022": 0.16,
        "2023": 0.18,
        "2024": 0.20,
        "2025": 0.12,
    },
    "seasonality_amplitude": 0.03,
    "lognormal_sigma": 0.22,
    "offplan_share_range": [0.15, 0.62],
    "gross_yield_range": [0.045, 0.095],
    "property_type_mix": {"unit": 0.78, "villa": 0.13, "land": 0.05, "building": 0.04},
    "rooms_mix": {"0": 0.16, "1": 0.34, "2": 0.28, "3": 0.15, "4": 0.05, "5": 0.02},
    "anomaly_rate": 0.004,
    "rapid_flip_rate": 0.003,
}

ROOM_LABEL = {0: "Studio", 1: "1 B/R", 2: "2 B/R", 3: "3 B/R", 4: "4 B/R", 5: "5 B/R"}
TYPE_LABEL = {"unit": "Unit", "villa": "Villa", "land": "Land", "building": "Building"}
SUBTYPE = {"unit": "Flat", "villa": "Villa", "land": "Land", "building": "Building"}


def _stable_unit(name: str, salt: str) -> float:
    """A deterministic value in [0, 1) from a name, so an area keeps its character across runs."""
    digest = hashlib.sha256(f"{salt}:{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def load_areas(areas_csv: Path) -> list[dict[str, str]]:
    with areas_csv.open() as fh:
        return list(csv.DictReader(fh))


def _price_index(d: date) -> float:
    """Cumulative price level, with a yearly drift and a mild seasonal wobble."""
    level = 1.0
    for year in range(PARAMS["start_year"], d.year):
        level *= 1 + PARAMS["annual_drift_by_year"].get(str(year), 0.0)
    part = (d.month - 1) / 12
    level *= 1 + PARAMS["annual_drift_by_year"].get(str(d.year), 0.0) * part
    level *= 1 + PARAMS["seasonality_amplitude"] * math.sin(2 * math.pi * (d.month - 3) / 12)
    return level


def _pick(rng: random.Random, mix: dict[str, float]) -> str:
    roll = rng.random()
    cumulative = 0.0
    for key, weight in mix.items():
        cumulative += weight
        if roll <= cumulative:
            return key
    return next(reversed(mix))


def generate(
    areas: list[dict[str, str]],
    *,
    n_transactions: int = 120_000,
    n_rent: int = 90_000,
    seed: int = DEFAULT_SEED,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    """Generate transaction and rent-contract frames in the publisher's column shape."""
    rng = random.Random(seed)
    lo, hi = PARAMS["base_ppsqm_range"]
    off_lo, off_hi = PARAMS["offplan_share_range"]
    y_lo, y_hi = PARAMS["gross_yield_range"]

    # Each area gets a stable character: a price level, an off-plan propensity and a yield level.
    profile = {
        a["dld_name"]: {
            "base_ppsqm": lo + (hi - lo) * _stable_unit(a["dld_name"], "price"),
            "offplan": off_lo + (off_hi - off_lo) * _stable_unit(a["dld_name"], "offplan"),
            "yield": y_lo + (y_hi - y_lo) * _stable_unit(a["dld_name"], "yield"),
            "weight": 0.2 + _stable_unit(a["dld_name"], "weight"),
        }
        for a in areas
    }
    names = [a["dld_name"] for a in areas]
    weights = [profile[n]["weight"] for n in names]

    start = date(PARAMS["start_year"], 1, 1)
    span_days = (date(PARAMS["end_year"], 12, 31) - start).days

    planted = {"price_outliers": 0, "rapid_flips": 0}
    rows: list[dict[str, Any]] = []
    for i in range(n_transactions):
        area = rng.choices(names, weights=weights, k=1)[0]
        prof = profile[area]
        when = start + timedelta(days=rng.randrange(span_days))
        ptype = _pick(rng, PARAMS["property_type_mix"])
        rooms = int(_pick(rng, PARAMS["rooms_mix"])) if ptype == "unit" else None

        if ptype == "land":
            sqm = round(rng.uniform(250, 2_000), 2)
        elif ptype == "villa":
            sqm = round(rng.uniform(180, 900), 2)
        elif ptype == "building":
            sqm = round(rng.uniform(800, 8_000), 2)
        else:
            sqm = round(rng.uniform(32, 60) + (rooms or 0) * rng.uniform(45, 70), 2)

        ppsqm = (
            prof["base_ppsqm"]
            * _price_index(when)
            * math.exp(rng.gauss(0, PARAMS["lognormal_sigma"]))
        )
        if ptype == "land":
            ppsqm *= 0.35
        elif ptype == "building":
            ppsqm *= 0.8

        # A small, counted population of price outliers, so the anomaly model has a known target.
        if rng.random() < PARAMS["anomaly_rate"]:
            ppsqm *= rng.choice([0.25, 4.0])
            planted["price_outliers"] += 1

        offplan = rng.random() < prof["offplan"]
        rows.append(
            {
                "transaction_id": f"S{i:08d}",
                "instance_date": when.isoformat(),
                "trans_group_en": "Sales",
                "procedure_name_en": "Sell Pre-Registration" if offplan else "Sell",
                "reg_type_en": "Off-Plan Properties" if offplan else "Existing Properties",
                "area_name_en": area,
                "building_name_en": f"{area.split()[0]} Tower {rng.randrange(1, 60)}",
                "project_name_en": f"Project {rng.randrange(1, 220)}",
                "property_type_en": TYPE_LABEL[ptype],
                "property_sub_type_en": SUBTYPE[ptype],
                "rooms_en": ROOM_LABEL.get(rooms) if rooms is not None else None,
                "has_parking": int(rng.random() < 0.7),
                "procedure_area": sqm,
                "actual_worth": round(ppsqm * sqm, 2),
                "meter_sale_price": round(ppsqm, 2),
            }
        )

    # Rapid resales: the same building and size sold again inside 90 days at a higher price.
    flips: list[dict[str, Any]] = []
    for row in rows:
        if rng.random() >= PARAMS["rapid_flip_rate"]:
            continue
        first = date.fromisoformat(row["instance_date"])
        again = first + timedelta(days=rng.randrange(7, 90))
        if again.year > PARAMS["end_year"]:
            continue
        flip = dict(row)
        flip["transaction_id"] = f"F{len(flips):08d}"
        flip["instance_date"] = again.isoformat()
        flip["actual_worth"] = round(row["actual_worth"] * rng.uniform(1.12, 1.45), 2)
        flip["meter_sale_price"] = round(flip["actual_worth"] / row["procedure_area"], 2)
        flips.append(flip)
        planted["rapid_flips"] += 1
    rows.extend(flips)

    transactions = pl.DataFrame(rows)

    # Rent contracts, priced off the same area profile so gross yield lands in the stated band.
    rent_rows: list[dict[str, Any]] = []
    for i in range(n_rent):
        area = rng.choices(names, weights=weights, k=1)[0]
        prof = profile[area]
        when = start + timedelta(days=rng.randrange(span_days))
        rooms = int(_pick(rng, PARAMS["rooms_mix"]))
        sqm = round(rng.uniform(32, 60) + rooms * rng.uniform(45, 70), 2)
        value = prof["base_ppsqm"] * _price_index(when) * sqm
        rent = value * prof["yield"] * math.exp(rng.gauss(0, 0.12))
        rent_rows.append(
            {
                "contract_id": f"R{i:08d}",
                "contract_start_date": when.isoformat(),
                "contract_end_date": (when + timedelta(days=365)).isoformat(),
                "area_name_en": area,
                "building_name_en": f"{area.split()[0]} Tower {rng.randrange(1, 60)}",
                "project_name_en": f"Project {rng.randrange(1, 220)}",
                "ejari_property_type_en": "Unit",
                "ejari_property_sub_type_en": "Flat",
                "rooms_en": ROOM_LABEL[rooms],
                "actual_area": sqm,
                "annual_amount": round(rent, 2),
                "version_en": "New" if rng.random() < 0.45 else "Renewed",
            }
        )
    rent_contracts = pl.DataFrame(rent_rows)

    meta = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provenance": "SYNTHETIC",
        "warning": (
            "Generated data. Structure is plausible so the models can be exercised; the levels are "
            "invented and are not claims about the Dubai market. Never cite a number derived from "
            "this as a fact about Dubai."
        ),
        "seed": seed,
        "params": PARAMS,
        "n_transactions": transactions.height,
        "n_rent_contracts": rent_contracts.height,
        "n_areas": len(names),
        "planted": planted,
    }
    return transactions, rent_contracts, meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--areas", type=Path, default=ROOT / "data" / "areas.csv")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--transactions", type=int, default=120_000)
    parser.add_argument("--rent", type=int, default=90_000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    areas = load_areas(args.areas)
    tx, rent, meta = generate(
        areas, n_transactions=args.transactions, n_rent=args.rent, seed=args.seed
    )
    args.out.mkdir(parents=True, exist_ok=True)
    tx.write_csv(args.out / "transactions.csv")
    rent.write_csv(args.out / "rent_contracts.csv")
    (args.out / "SYNTHETIC").write_text(meta["warning"] + "\n")

    results = result_path("synthetic_params.json", "SYNTHETIC")
    results.write_text(json.dumps(meta, indent=2))
    print(f"generated {tx.height:,} transactions and {rent.height:,} rent contracts (SYNTHETIC)")
    print(f"planted: {meta['planted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
