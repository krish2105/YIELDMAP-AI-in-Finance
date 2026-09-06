# YIELDMAP

**Dubai property investment intelligence from open Dubai Land Department data.**
Valuation, yield, risk and a cited, agent-written investment memo — on a 3D Dubai.

Built for SP Jain MAIB **AI 217 (AI in Finance)**. Solo project by Krishna Mathur.

> **Information, not advice.** YIELDMAP explains, compares and simulates. It does not recommend
> that you buy, sell or finance anything, and it cannot execute a transaction of any kind.

---

## What it does

Dubai recorded roughly 147,500 unit sales in 2025 and about 1.38 million tenancy contracts. The
registry behind all of it is public, unit-level and daily — yet buyers and small investors still
decide from broker claims and portal listings. YIELDMAP turns that registry into numbers you can
check.

- **Ingests** DLD transactions, rent contracts, valuations, projects and buildings nightly.
- **Models** price per sqm (hedonic + repeat-sales index), gross and net yield, mortgage
  affordability, DCF/IRR, off-plan and concentration risk, and anomaly flags.
- **Answers** cited questions over the registry and over RERA/DLD rules.
- **Advises** through a bounded crew — Valuer, Yield Analyst, Risk Auditor, Advisor, Auditor —
  that writes a memo with every number traced to a query or a document.
- **Shows** it on a 3D Dubai with a 20-year time scrubber.

## Every number is checkable

Nothing in this project is a hand-typed figure. Every value crossing the API is a `Kpi` object
carrying its sample size, as-of date, confidence, method id and **the exact SQL that produced it**.
Click any KPI tile and the query is right there. Cells with too few transactions say
"insufficient data" instead of showing a misleading number.

## Live

Deployment links are published here at the end of each phase.

## Development

```bash
uv sync                 # Python deps (3.12)
uv run pytest           # Python tests
uv run ruff check .     # lint
npm install && npm test # JS tests
```

External data is downloaded by GitHub Actions (`.github/workflows/ingest.yml`), not locally — see
`CLAUDE.md` for why. Data licences and retrieval dates are in `docs/datasets.md`; model choices and
their measured trade-offs are in `docs/models.md`; all measured numbers are in `docs/results/`.

## Cost

Zero paid inference. The provider chain is local Ollama → Gemini free tier → Groq free tier, with
request-count budgets and graceful degradation at every step. The Anthropic backend exists in the
code and is switched off.
