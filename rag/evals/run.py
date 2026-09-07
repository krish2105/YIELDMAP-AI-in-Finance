"""Score retrieval and answering against the thirty-case set.

Two measures, chosen because they fail in different ways.

**Recall@5** asks whether the right source was retrieved at all. A system can write a fluent answer
from the wrong document, and this is the measure that catches it.

**Faithfulness** asks whether every factual sentence in the answer carries a citation to a source
that was actually retrieved. It catches the opposite failure: the right documents retrieved and the
answer asserting something none of them says.

The eval runs offline. With no model provider reachable it scores the retrieval half fully and
reports the answering half against whatever backend answered, labelling the result. Supplying a key
turns the same harness into the real comparison without any code change.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from etl.results import result_path
from rag.ask import CITATION, is_factual, is_refusal, split_sentences
from rag.ask import ask as run_ask
from rag.indexer import build_index, load_index
from rag.provider import LLMProvider
from rag.retriever import Retriever

ROOT = Path(__file__).resolve().parent.parent.parent
CASES_PATH = Path(__file__).resolve().parent / "cases.yaml"

# The gates from the plan. Recall is the harder one and the one that matters more.
RECALL_TARGET = 0.80
RECALL_AT_1_TARGET = 0.70
FAITHFULNESS_TARGET = 0.90


@dataclass
class CaseResult:
    id: str
    lang: str
    question: str
    expected: str | None
    expected_kind: str | None
    retrieved: list[str]
    hit_rank: int | None
    recalled: bool
    faithful: bool
    answered: bool
    n_factual: int
    n_cited: int
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "lang": self.lang,
            "question": self.question,
            "expected": self.expected,
            "expected_kind": self.expected_kind,
            "hit_rank": self.hit_rank,
            "recalled": self.recalled,
            "faithful": self.faithful,
            "answered": self.answered,
            "factual_sentences": self.n_factual,
            "cited_sentences": self.n_cited,
            "retrieved": self.retrieved[:5],
            "notes": self.notes,
        }


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text())["cases"]


def _identifier(chunk) -> str:
    """What a case's expectation is matched against."""
    if chunk.kind == "doc":
        return chunk.doc_id or chunk.title
    return str(chunk.meta.get("area_key") or chunk.title)


def score_case(
    case: dict[str, Any], retriever: Retriever, provider: LLMProvider, *, k: int = 5
) -> CaseResult:
    expected = case.get("expect_doc") or case.get("expect_area")
    expected_kind = "doc" if "expect_doc" in case else ("area" if "expect_area" in case else None)

    answer = run_ask(case["question"], retriever=retriever, provider=provider, k=k)
    retrieval = retriever.retrieve(case["question"], k=k)
    retrieved = [_identifier(h.chunk) for h in retrieval.hits]

    hit_rank = None
    if expected is not None and expected in retrieved:
        hit_rank = retrieved.index(expected) + 1

    # A case with no expectation is a refusal case: retrieving nothing relevant is correct.
    recalled = hit_rank is not None if expected is not None else not answer.found_material

    # A refusal is not an answer, and it is not a false one either. Separating the two is the
    # point: faithfulness asks whether what was asserted was cited, and answer rate asks whether
    # anything was asserted at all. Conflating them scored an honest refusal as a lie, which is
    # how the Arabic cases read 0.0 while the system was behaving correctly.
    refused = is_refusal(answer.text) or not answer.found_material
    sentences = split_sentences(answer.text)
    factual = [] if refused else [s for s in sentences if is_factual(s)]
    cited = [s for s in factual if CITATION.search(s)]
    faithful = (len(cited) == len(factual)) if factual else True

    return CaseResult(
        id=case["id"],
        lang=case["lang"],
        question=case["question"],
        expected=expected,
        expected_kind=expected_kind,
        retrieved=retrieved,
        hit_rank=hit_rank,
        recalled=recalled,
        faithful=faithful,
        answered=not refused,
        n_factual=len(factual),
        n_cited=len(cited),
        notes=answer.notes,
    )


def run(*, k: int = 5, out: Path | None = None) -> dict[str, Any]:
    chunks = load_index()
    if not chunks:
        build_index()
        chunks = load_index()

    provider = LLMProvider.from_env()
    retriever = Retriever(chunks, provider=provider)
    cases = load_cases()

    results = [score_case(c, retriever, provider, k=k) for c in cases]

    # Recall is a retrieval measure and is undefined for a question with no correct document, so
    # it is computed over the answerable cases only. Averaging the out-of-scope cases into it
    # would mix two different questions — "did it find the right source" and "did it know there
    # was none" — into one number that answers neither.
    answerable = [r for r in results if r.expected is not None]
    refusal_cases = [r for r in results if r.expected is None]

    recall = sum(1 for r in answerable if r.recalled) / len(answerable) if answerable else 0.0
    faithfulness = sum(1 for r in results if r.faithful) / len(results)

    # What the out-of-scope cases measure: given a question this corpus cannot answer, did the
    # system decline rather than write something from the nearest five chunks? Reported and not
    # gated while the backend is the offline fixture, which answers everything by construction —
    # gating it there would fail the build for a property of the stand-in rather than the system.
    refusal_rate = (
        sum(1 for r in refusal_cases if not r.answered) / len(refusal_cases)
        if refusal_cases
        else None
    )

    # Recall@5 over a corpus this size is close to free: with 117 chunks and five slots, a
    # retriever that is merely not broken scores well. Rank-sensitive measures are what separate
    # "the answer was somewhere in the list" from "the answer was first", and they are the ones
    # worth watching as the corpus grows. Ranked cases only — a refusal case has no rank.
    # Cases that expected an answer and got one. Reported rather than gated: on the offline
    # fixture backend a non-English question legitimately cannot be answered well, and hiding that
    # behind a passing faithfulness score would be the dishonest reading of these numbers.
    answer_rate = sum(1 for r in answerable if r.answered) / len(answerable) if answerable else 0.0

    precision_at_1 = (
        sum(1 for r in answerable if r.hit_rank == 1) / len(answerable) if answerable else 0.0
    )
    mrr = (
        sum(1 / r.hit_rank for r in answerable if r.hit_rank) / len(answerable)
        if answerable
        else 0.0
    )

    # Split the same way the headline is: recall over the answerable cases, refusal over the
    # out-of-scope ones. Mixing them here while separating them above would have the breakdown
    # disagree with the total, which is how a table stops being read.
    by_lang: dict[str, dict[str, Any]] = {}
    for lang in sorted({r.lang for r in results}):
        subset = [r for r in results if r.lang == lang]
        can_answer = [r for r in subset if r.expected is not None]
        cannot = [r for r in subset if r.expected is None]
        by_lang[lang] = {
            "cases": len(subset),
            "answerable": len(can_answer),
            "out_of_scope": len(cannot),
            "recall": round(sum(1 for r in can_answer if r.recalled) / len(can_answer), 4)
            if can_answer
            else None,
            "faithfulness": round(sum(1 for r in subset if r.faithful) / len(subset), 4),
            "answer_rate": round(sum(1 for r in can_answer if r.answered) / len(can_answer), 4)
            if can_answer
            else None,
            "refusal_rate": round(sum(1 for r in cannot if not r.answered) / len(cannot), 4)
            if cannot
            else None,
        }

    semantic_backend = retriever.semantic.backend
    # The corpus mixes documents with facts derived from the warehouse, so the report inherits the
    # weaker provenance: a recall figure measured over generated facts is not a claim about a
    # real corpus.
    provenance = "SYNTHETIC" if any(c.provenance == "SYNTHETIC" for c in chunks) else "REAL"
    report = {
        "provenance": provenance,
        "n_cases": len(results),
        "n_answerable": len(answerable),
        "n_out_of_scope": len(refusal_cases),
        "k": k,
        "recall_at_k": round(recall, 4),
        "recall_at_1": round(precision_at_1, 4),
        "mrr": round(mrr, 4),
        "answer_rate": round(answer_rate, 4),
        "refusal_rate": round(refusal_rate, 4) if refusal_rate is not None else None,
        "refusal_gated": not retriever.semantic.degraded,
        "refusal_note": (
            "Out-of-scope questions the corpus cannot answer. Declining is correct; answering is "
            "a fabrication. Not gated against the offline fixture backend, which answers every "
            "prompt by construction. scripts/calibrate_relevance.py records why there is no "
            "retrieval-score threshold behind this: on a corpus this size no signal separates an "
            "unanswerable question from a topically adjacent one."
        ),
        "faithfulness": round(faithfulness, 4),
        "recall_target": RECALL_TARGET,
        "faithfulness_target": FAITHFULNESS_TARGET,
        "recall_at_1_target": RECALL_AT_1_TARGET,
        "recall_met": recall >= RECALL_TARGET,
        "recall_at_1_met": precision_at_1 >= RECALL_AT_1_TARGET,
        "faithfulness_met": faithfulness >= FAITHFULNESS_TARGET,
        "passed": (
            recall >= RECALL_TARGET
            and precision_at_1 >= RECALL_AT_1_TARGET
            and faithfulness >= FAITHFULNESS_TARGET
        ),
        # Stated with the scores, because a recall figure means nothing without knowing how many
        # chunks it was chosen from. Five slots out of a hundred is a different claim from five
        # out of a hundred thousand, and only the second is evidence of a good retriever.
        "corpus": {
            "chunks": len(chunks),
            "documents": len({c.doc_id for c in chunks if c.doc_id}),
            "facts": sum(1 for c in chunks if c.kind == "fact"),
            "note": (
                "A small corpus makes recall@5 easy and rank-sensitive measures the informative "
                "ones. These figures describe retrieval over this corpus, not retrieval in general."
            ),
        },
        "by_language": by_lang,
        "retrieval_backend": semantic_backend,
        "degraded": retriever.semantic.degraded,
        "caveat": (
            "Scored against the offline TF-IDF fallback because no embedding provider was "
            "reachable. Supplying GEMINI_API_KEY reruns the same harness against real embeddings."
            if retriever.semantic.degraded
            else None
        ),
        "failures": [r.as_dict() for r in answerable if not (r.recalled and r.faithful)],
        "refusals": [r.as_dict() for r in answerable if not r.answered],
        "answered_out_of_scope": [r.as_dict() for r in refusal_cases if r.answered],
        "cases": [r.as_dict() for r in results],
    }

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="defaults to docs/results/rag_eval.json, routed by provenance",
    )
    parser.add_argument("--gate", action="store_true", help="exit non-zero when a target is missed")
    args = parser.parse_args(argv)

    report = run(k=args.k, out=None)
    out = args.out or result_path("rag_eval.json", report["provenance"])
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(
        f"{report['n_cases']} cases "
        f"({report['n_answerable']} answerable, {report['n_out_of_scope']} out of scope), "
        f"k={report['k']}, backend {report['retrieval_backend']}"
    )
    print(
        f"  recall@{report['k']}   {report['recall_at_k']:.1%}  "
        f"(target {report['recall_target']:.0%})  {'met' if report['recall_met'] else 'MISSED'}"
    )
    print(
        f"  faithfulness  {report['faithfulness']:.1%}  "
        f"(target {report['faithfulness_target']:.0%})  "
        f"{'met' if report['faithfulness_met'] else 'MISSED'}"
    )
    if report["refusal_rate"] is not None:
        gated = "gated" if report["refusal_gated"] else "reported, not gated"
        print(f"  refusal       {report['refusal_rate']:.1%}  of out-of-scope questions  ({gated})")
    print()
    for lang, row in report["by_language"].items():
        recall = f"{row['recall']:.0%}" if row["recall"] is not None else "  —"
        refusal = f"   refusal {row['refusal_rate']:.0%}" if row["refusal_rate"] is not None else ""
        print(
            f"  {lang}  {row['answerable']:>2} answerable   recall {recall}   "
            f"faithfulness {row['faithfulness']:.0%}{refusal}"
        )

    if report["answered_out_of_scope"]:
        print(
            f"\n  {len(report['answered_out_of_scope'])} out-of-scope question(s) answered "
            f"rather than declined:"
        )
        for f in report["answered_out_of_scope"]:
            print(f"    {f['id']:<24} {f['question'][:52]}")

    if report["failures"]:
        print(f"\n  {len(report['failures'])} case(s) missed:")
        for f in report["failures"][:10]:
            reason = "not recalled" if not f["recalled"] else "unfaithful"
            print(f"    {f['id']:<24} {reason:<14} expected {f['expected']}")
            print(f"      retrieved: {', '.join(f['retrieved'][:3])}")

    if report["caveat"]:
        print(f"\n  {report['caveat']}")
    print(f"\nwrote {out}")

    return 0 if (report["passed"] or not args.gate) else 1


if __name__ == "__main__":
    raise SystemExit(main())
