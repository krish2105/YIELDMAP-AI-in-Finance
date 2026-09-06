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

| What | Where | Status |
|---|---|---|
| Ingest job | [Actions → Ingest DLD open data](https://github.com/krish2105/YIELDMAP-AI-in-Finance/actions/workflows/ingest.yml) | running; probe and discovery reports land in `docs/results/` |
| Continuous integration | [Actions → CI](https://github.com/krish2105/YIELDMAP-AI-in-Finance/actions/workflows/ci.yml) | green |
| Work in progress | [pull request #1](https://github.com/krish2105/YIELDMAP-AI-in-Finance/pull/1) | draft |
| API | Render | from Phase C |
| Web | Vercel | from Phase D |

There is no site to visit yet — the web layer is Phase D. What is checkable now is the ingest
run's job summary, which prints the reachability table for every candidate source, and
[`docs/term4_yieldmap.ipynb`](docs/term4_yieldmap.ipynb), which GitHub renders with its charts.

## Measured so far

Every figure below is read from `docs/results/`, produced by the models in `finance/`.
**They currently describe the labelled stand-in, not the Dubai registry** — see
[`docs/datasets.md`](docs/datasets.md) for why, and for how to load the real files.

| Model | Measured | Target |
|---|---|---|
| Hedonic valuation | 18.9% MAPE on a time-split holdout, against a 36.4% baseline — +48% skill, at the 19.4% noise floor | 12% MAPE, on real data |
| Repeat-sales index | 5,079 pairs over 144 months, 0 periods dropped as disconnected | reproduces direction of travel |
| Yield | median gross 7.12%, net 3.43%, gap 3.59%; 115 of 463 cells suppressed as too thin | net below gross always |
| Mortgage and DCF | 20% deposit case exact; levered 8.61% vs unlevered 5.75% at 3% growth | IRR matches a hand-computed case |
| Forecast | beats seasonal naive on 77/86 areas (90%), 10.1% vs 15.2% error | 60% of areas |
| Risk and anomalies | 1,737 of 120,346 flagged (1.44%); 86 areas scored | score in [0,100], monotone |

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
