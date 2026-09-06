"""Where a measured result is allowed to be written.

Results computed from real publisher data live in ``docs/results/``. Results computed from the
synthetic stand-in live in ``docs/results/synthetic/``. Keeping them in separate directories rather
than in one directory with a flag means the separation survives a careless read: anything that
globs ``docs/results/*.json`` gets real numbers only, and the provenance guard can enforce the
boundary instead of trusting a field.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "docs" / "results"
SYNTHETIC_SUBDIR = "synthetic"

Provenance = Literal["REAL", "SYNTHETIC"]


def results_dir(provenance: Provenance, base: Path | None = None) -> Path:
    """The directory a result of this provenance belongs in."""
    root = base or RESULTS_DIR
    return root / SYNTHETIC_SUBDIR if provenance == "SYNTHETIC" else root


def result_path(name: str, provenance: Provenance, base: Path | None = None) -> Path:
    """Full path for a named result file, routed by provenance."""
    path = results_dir(provenance, base) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
