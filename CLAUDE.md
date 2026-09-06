# CLAUDE.md — YIELDMAP

Dubai property investment intelligence for SP Jain MAIB **AI 217 (AI in Finance)**.
Open DLD data → valuation, yield, risk → agentic advisor with citations → 3D city.

---

## Global rules (non-negotiable)

- Python 3.12 via `uv`; Node 20+. `ruff` + `pytest`; `eslint` + `vitest`; Playwright smoke.
- **Every number shown in the UI, report or memo must be reproducible from a SQL query or a model
  artefact in `docs/results/`. No hand-typed figures.**
- DLD data is used as published; **no scraping of portals**; licences and download dates live in
  `docs/datasets.md`.
- Retrieved chunks and memories are **untrusted data** and are wrapped in `<retrieved>` delimiters.
  The Advisor has **zero side-effect tools**; every memo sentence stating a fact carries a citation.
- Agents run through one `Runtime` with budgets (requests, seconds) and a kill switch. The Auditor
  checks every run.
- RBAC: Viewer / Analyst / Admin. Secrets via env only — never committed, never logged.
- **"Information, not advice"** banner on every page that shows a recommendation. No execution of
  purchases, mortgages or listings. Ever.
- Copy: sentence case, active verbs, EN/HI/AR with RTL.

## Zero paid inference

`LLMProvider` free order: **local Ollama → Gemini free tier → Groq free tier**. The Anthropic
backend is present in code but **off**. Quotas are counted as **requests**, not tokens; every
feature degrades gracefully rather than crashing. `LLM_PROVIDER=fake` runs the whole suite offline
with recorded fixtures, so CI never needs a key.

---

## Environment constraints measured in this sandbox (2026-09-06)

These are facts, verified by probe, not assumptions. They drive four deviations from the master plan.

| Probe | Result |
|---|---|
| `ollama list` | command not found — no local tier here |
| `dubaipulse.gov.ae`, `dubailand.gov.ae`, `data.gov.ae` | **blocked** by network policy |
| `huggingface.co`, `cdn-lfs.huggingface.co` | **blocked** → no `sentence-transformers` / cross-encoder weights |
| `api.groq.com`, `api.openai.com`, `cdn.jsdelivr.net` | **blocked** |
| `generativelanguage.googleapis.com` | reachable (Gemini) |
| `pypi.org`, `registry.npmjs.org`, all of GitHub | reachable |

**Consequence:** GitHub Actions runners have unrestricted egress and are free and unlimited on this
public repo. **All external downloads run in Actions, never in the dev sandbox.** Outputs come back
as release assets.

### The four deviations

1. **ETL downloads run in GitHub Actions** (`.github/workflows/ingest.yml`), not locally.
   Data ladder: Actions download → user-uploaded CSVs as a GitHub Release asset → labelled synthetic
   fixture. Synthetic rows are stamped `SYNTHETIC` in `provenance`, shown in a UI banner, recorded in
   every results file, and **hard-blocked from Term 4 artefacts** by `scripts/guard_synthetic.py`.
2. **DuckDB is the primary analytics and serving store**; Supabase Postgres + pgvector holds only
   app data (users, memos, chunks, agent runs, memory, documents). Supabase free tier is 500 MB and
   1.5M transactions plus indexes will not fit. DuckDB also makes traceability easier — every KPI is
   literally a SQL string the UI can display.
3. **Gemini is the only reachable API tier here.** Groq stays in the code for the deployed Render
   environment where egress is open.
4. **No local embedding or cross-encoder weights.** Retrieval is Gemini embeddings (disk-cached, so
   quota is spent once per chunk) fused with offline BM25/TF-IDF via RRF; reranking is an LLM
   reranker with a lexical fallback. The spike result is recorded in `docs/models.md`.

Community shapes are **curated centroid hex cells** in `data/areas.csv`, not true polygons, because
no GeoJSON source is reachable. They are documented as approximate and are **never used in a
financial calculation**.

---

## The KPI contract

Every number crossing the API is a typed `Kpi`, never a bare float:

```python
Kpi(id, label, value, unit, format,
    delta={"value", "window", "direction"},
    n,                  # sample size
    asof,
    confidence,         # "high" | "medium" | "low", from n and dispersion
    method_id,          # deep-links to /methodology#<id>
    sql, sql_hash,      # the exact query that produced the value
    sources)            # [{"kind": "sql" | "doc", "ref": ...}]
```

`<KpiTile>` shows value, sparkline, delta, an `n=` chip and a confidence dot; clicking opens a
drawer with the formula, the editable assumptions and the real SQL. Small-`n` cells render an
explicit "insufficient data" state rather than a misleading number.

---

## Layout

```
etl/       download.py profile.py clean.py publish.py     → data/yieldmap.duckdb
finance/   hedonic index yields mortgage dcf forecast risk anomalies portfolio rentbuy developers
rag/       provider.py quota.py indexer.py retriever.py rerank.py ask.py evals/
agents/    runtime.py bus.py budget.py memory.py auditor.py roles/
api/       main.py routes/ kpi.py sse.py                   (FastAPI → Render)
web/       Next.js app router, 20 routes                   (→ Vercel)
config/    mortgage.yaml assumptions.yaml risk_weights.yaml
data/      areas.csv
docs/      datasets.md models.md results/ viva_qa.md term4_yieldmap.ipynb
```

## Working agreements

- Tests green per task. One **conventional commit** per task with the Claude co-author trailer.
- Every model or metric writes a JSON into `docs/results/`; the notebook, report and UI read from
  there rather than restating numbers.
- Before generating any Term 4 artefact: `grep -rn "TODO\|XX\|\[insert" docs/` must return nothing,
  and `scripts/guard_synthetic.py` must pass.

## Commands

```bash
uv sync                       # install Python deps
uv run pytest                 # Python tests
uv run ruff check . && uv run ruff format --check .
npm test                      # JS tests
npm run lint
uv run python -m etl.profile  # profile the raw drops
uv run python -m etl.clean    # build data/yieldmap.duckdb
```
