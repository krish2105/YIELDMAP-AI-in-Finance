"""Can a relevance floor tell "we have no information on this" from "this is nearby"?

The Ask path refuses only when retrieval returns literally nothing, and over 117 chunks BM25
always returns something — so the "no matching data" path was effectively unreachable. The obvious
fix is a score threshold: refuse when the best hit is not good enough.

This measures whether such a threshold exists before one is written. Three candidate signals, each
computed over the eval's own answerable questions and its out-of-scope ones:

* **lexical** — the top BM25 score. Zero means no term overlap at all.
* **semantic** — the top cosine similarity, which is a genuine bounded relevance measure.
* **coverage** — the share of the question's distinctive terms that appear anywhere in the corpus,
  where "distinctive" excludes terms common to a quarter of all chunks.

A signal is usable only if the out-of-scope distribution sits below the in-scope one with a gap to
put a threshold in. The verdict is computed here rather than asserted: for each signal the report
records the best achievable separation and what it would cost in false refusals.

    uv run python -m scripts.calibrate_relevance
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "rag" / "evals" / "cases.yaml"

# A term in this share of chunks or more says nothing about whether the corpus covers a question.
COMMON_TERM_SHARE = 0.25
# Below this a question's terms are too few to judge; treated as covered rather than guessed at.
MIN_DISTINCTIVE_TERMS = 1


def signals(chunks: list, retriever, question: str, common: set[str], vocab: set[str]) -> dict:
    from rag.retriever import tokenize

    lexical = retriever.lexical.search(question, 20)
    semantic = retriever.semantic.search(question, 20)

    terms = [t for t in tokenize(question) if len(t) > 2]
    distinctive = [t for t in terms if t not in common]
    if len(distinctive) < MIN_DISTINCTIVE_TERMS:
        coverage, missing = 1.0, []
    else:
        missing = [t for t in distinctive if t not in vocab]
        coverage = 1 - len(missing) / len(distinctive)

    return {
        "lexical": lexical[0][1] if lexical else 0.0,
        "semantic": semantic[0][1] if semantic else 0.0,
        "coverage": coverage,
        "missing_terms": missing,
    }


def separation(in_scope: list[float], out_scope: list[float]) -> dict[str, Any]:
    """The best threshold on this signal, and what it costs.

    A threshold refuses everything below it. The useful one refuses the most out-of-scope
    questions while wrongly refusing the fewest real ones, so both counts are reported: a signal
    that catches every out-of-scope question by also refusing half the real ones is not a signal.
    """
    best: dict[str, Any] | None = None
    for threshold in sorted(set(in_scope + out_scope)):
        caught = sum(1 for v in out_scope if v < threshold) / len(out_scope)
        lost = sum(1 for v in in_scope if v < threshold) / len(in_scope)
        score = caught - lost
        if best is None or score > best["margin"]:
            best = {
                "threshold": round(threshold, 4),
                "out_of_scope_refused": round(caught, 4),
                "in_scope_wrongly_refused": round(lost, 4),
                "margin": round(score, 4),
            }
    assert best is not None
    # Overlap: the in-scope floor sits below the out-of-scope ceiling, so no threshold separates
    # the two cleanly whatever it is set to.
    best["in_scope_min"] = round(min(in_scope), 4)
    best["out_of_scope_max"] = round(max(out_scope), 4)
    best["separates_cleanly"] = min(in_scope) > max(out_scope)
    return best


def run() -> dict[str, Any]:
    from rag.indexer import build_index, load_index
    from rag.provider import LLMProvider
    from rag.retriever import Retriever, tokenize

    chunks = load_index()
    if not chunks:
        build_index()
        chunks = load_index()

    provider = LLMProvider.from_env()
    retriever = Retriever(chunks, provider=provider)

    counts: Counter[str] = Counter()
    for chunk in chunks:
        counts.update(set(tokenize(chunk.text)))
    common = {t for t, n in counts.items() if n >= len(chunks) * COMMON_TERM_SHARE}
    vocab = set(counts)

    cases = yaml.safe_load(CASES.read_text())["cases"]
    answerable = [c for c in cases if c.get("expect_doc") or c.get("expect_area")]
    out_of_scope = [c for c in cases if c not in answerable]

    measured = {
        "answerable": [
            {"id": c["id"], **signals(chunks, retriever, c["question"], common, vocab)}
            for c in answerable
        ],
        "out_of_scope": [
            {"id": c["id"], **signals(chunks, retriever, c["question"], common, vocab)}
            for c in out_of_scope
        ],
    }

    verdicts = {
        name: separation(
            [m[name] for m in measured["answerable"]],
            [m[name] for m in measured["out_of_scope"]],
        )
        for name in ("lexical", "semantic", "coverage")
    }
    usable = [name for name, v in verdicts.items() if v["separates_cleanly"]]

    return {
        "provenance": "REAL",
        "question": (
            "Is there a retrieval score below which the corpus can be said not to cover a "
            "question, so that Ask refuses structurally rather than relying on the model to "
            "decline?"
        ),
        "verdict": (
            "No, not on this corpus. Every signal's out-of-scope range overlaps its in-scope "
            "range, so any threshold either admits out-of-scope questions or refuses real ones. "
            "The distinguishing word is a single token in a sentence of otherwise on-topic "
            "vocabulary — 'London' against 'Dubai' — and every one of these signals aggregates "
            "over the whole question, which dilutes exactly the term that carries the answer. "
            "So the refusal guarantee is left where it can be enforced: the answering stage, "
            "where a sentence without a citation to retrieved material is dropped."
        )
        if not usable
        else f"Usable signals: {', '.join(usable)}.",
        "usable_signals": usable,
        "corpus": {"chunks": len(chunks), "vocabulary": len(counts), "common_terms": len(common)},
        "cases": {"answerable": len(answerable), "out_of_scope": len(out_of_scope)},
        "signals": verdicts,
        "measurements": measured,
        "retrieval_backend": retriever.semantic.backend,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    from etl.results import result_path

    report = run()
    out = args.out or result_path("relevance_floor.json", "REAL")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")

    print(f"corpus: {report['corpus']['chunks']} chunks, {report['corpus']['vocabulary']} terms")
    for name, v in report["signals"].items():
        mark = "separates" if v["separates_cleanly"] else "OVERLAPS"
        print(
            f"  {name:9} {mark:10} in-scope min {v['in_scope_min']:.3f} vs "
            f"out-of-scope max {v['out_of_scope_max']:.3f}  "
            f"(best threshold catches {v['out_of_scope_refused']:.0%} of out-of-scope, "
            f"wrongly refuses {v['in_scope_wrongly_refused']:.0%})"
        )
    print(f"\nusable signals: {report['usable_signals'] or 'none'}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
