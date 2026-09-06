# YIELDMAP — one page

**Dubai property investment intelligence where every number shows its working.**

---

## The problem

The Dubai Land Department publishes every property transaction and every registered tenancy. The
data is public, and for a person deciding where to buy it is effectively unusable: it is records,
not yields. The portals that do compute yields will not show you how, so a buyer comparing two
communities is choosing between two numbers they cannot check.

## What it does

Turns the published record into valuations, yields, risk scores and a cited investment memo, across
twenty views — a 3D city map, per-community pages, a screener, a rent-versus-buy simulator, a
portfolio view, forecasts, developer league tables, and a multilingual question-answering interface
in English, Hindi and Arabic.

## What makes it different

**Every number is a query, not a figure.** Anything crossing the API is a typed object that carries
the SQL that produced it, its sample size, its as-of date and a confidence grade — and it *cannot
be constructed without them*: the validator rejects it. Click any tile and the drawer shows the
actual query with a copy button. Copy it, run it, get the same number.

**It refuses to answer when it should not.** Below a threshold of sample size and dispersion, a cell
prints "insufficient data" rather than a number with a caveat beside it, because a caveated number
is still read as a number.

**It is information, not advice, structurally rather than as a disclaimer.** No endpoint, tool or
agent can place, fund or settle anything. The agent that writes the memo is granted zero tools — not
restricted, zero — so there is no prompt that makes it do something else. Every factual sentence in
a memo carries a citation or the memo is withheld.

**The security claims are measured, not asserted.** Ten attacks from the OWASP Agentic Security
Initiative threat list run against the real system on every push: a poisoned document instructing
the model to recommend buying, a forged message on the agent bus, a memory-poisoning attempt, a
budget flood, a privilege escalation. The results page renders what they measured. One of them found
a control that was claimed and not enforced, which is what a red team is for.

**It costs nothing to run.** The model chain is a local model, then two free tiers, then a
deterministic offline backend; the paid backend is present in the code and refuses to run behind
two separate switches. Quotas are counted in requests, because that is how free tiers meter.

## Where the data stands

The Land Department's open-data portal refuses automated clients from every network this project can
reach — probed from a runner with open egress, not a restricted sandbox, and the logs are in the
repository. So it currently runs on a generated stand-in with the real schema, labelled `SYNTHETIC`
in the database, in a banner on every page, and in every results file, with a check that blocks it
from reaching any submitted artefact.

**Loading a real drop changes every number and requires no code change.** Everything downstream is
built, tested and gated.

## Built with

Python, DuckDB, Polars, scikit-learn, FastAPI · Next.js 16, React 19, React Three Fiber, TanStack
Query · GitHub Actions, Render, Vercel, Supabase.

Hedonic valuation with Duan's smearing correction · Bailey–Muth–Nourse repeat-sales index with
connected-component checking · hybrid BM25-plus-embedding retrieval fused by reciprocal rank ·
a bounded, audited, signed-bus agent crew.

## Honest limits

The figures describe generated data, so a good MAPE means the pipeline runs, not that the valuation
is accurate. Community shapes are curated centroid hexes, not true polygons — no GeoJSON source was
reachable — and are never used in a financial calculation. Service charges are estimates and are the
largest single input to the net yield. Yields use area-level rent medians, not the specific unit's
rent. Forecasts are statistical, not advice.

---

*SP Jain MAIB · AI 217, AI in Finance · Term 4*
