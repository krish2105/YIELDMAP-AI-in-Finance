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
| **Web app** | https://yieldmap-git-claude-yiel-5130d2-krishnamathur008-1499s-projects.vercel.app | twenty tabs, live. Open it on a phone — the layout is built for one |
| **Analytics API** | https://yieldmap-api.onrender.com | free tier: sleeps after 15 minutes idle, so the first request takes about 50 seconds |
| API health | https://yieldmap-api.onrender.com/health | says which database is loaded and whether it is real or generated |
| Ingest job | [Actions → Ingest DLD open data](https://github.com/krish2105/YIELDMAP-AI-in-Finance/actions/workflows/ingest.yml) | nightly; probe and discovery reports land in `docs/results/` |
| Continuous integration | [Actions → CI](https://github.com/krish2105/YIELDMAP-AI-in-Finance/actions/workflows/ci.yml) | four jobs: tests, web, docs, security |
| Notebook | [`docs/term4_yieldmap.ipynb`](docs/term4_yieldmap.ipynb) | GitHub renders it with its charts |

**The figures are currently generated, not real, and the site says so on every page.** The Dubai
Land Department's open-data portal refuses automated clients from every network this project can
reach; `docs/datasets.md` records exactly what was attempted and what each host returned. The
stand-in is stamped `SYNTHETIC` in the database, in a banner on every page, and in every results
file, and a check in CI blocks it from reaching any submitted artefact. Point the ingest job at a
real drop and every number on the site changes; nothing else has to.

Answers on `/ask` and memos on `/crew` run on an offline fixture backend and are marked degraded
in the interface. That is the zero-cost default: setting `GEMINI_API_KEY` on the Render service
switches the free model tier on with no code change.

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
| Retrieval | recall@5 1.00, **recall@1 0.87, MRR 0.91**, faithfulness 1.00 over 30 cases in three languages — on a 117-chunk corpus, where recall@5 is easy and the rank measures are the informative ones | gated at 0.80 / 0.70 / 0.90 |
| Red team | 11/11 controls held against the OWASP ASI threat list | every attack fails to land |
| Cost | $0.00/month; the free tier binds at ~100 daily users, on embeddings before generation | stays free at course scale |
| Journey | 34 Playwright tests green on a desktop viewport and a Pixel 7 | the full journey, on a phone |
| Python | 703 tests | — |
| Access control | writes need a token the API signed; the role is never something a caller sends | no credential, no write |
| Frame rate | 60fps desktop, 61fps on a Pixel 7 — measured in software rasterisation, so a floor | 60 / 30 |
| Accessibility | 0 violations across 7 pages, WCAG 2.1 AA, both viewports — was 7 serious | none serious |

## Running it

Reads are public. Writing a memo — the only endpoint that writes, and the only one that spends a
model budget — needs an account:

```bash
uv run python -m api.auth hash 'a-password'      # -> $argon2id$...
export AUTH_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
export YIELDMAP_USERS='you@example.com:analyst:$argon2id$...'
```

Set `YIELDMAP_ENV=production` and the service refuses to start without those, rather than running
in a state where tokens silently stop working on restart. `GET /health` reports whether
authentication is configured and whether memo storage is durable, so a deployment can be checked
from outside without reading its environment.

Optional: `DATABASE_URL` for durable memos (without it they go to a file store that a container
loses on restart), and `SENTRY_DSN` for error tracking. Neither is required to run.

## For the viva

| Document | What it is |
|---|---|
| [`docs/viva_qa.md`](docs/viva_qa.md) | Fifteen likely questions, answered from what the code says, each naming the file that backs it |
| [`docs/demo_script.md`](docs/demo_script.md) | A timed three-minute run-through, with what to click and what to say |
| [`docs/pitch.md`](docs/pitch.md) | The one-page version |
| [`docs/loading_real_data.md`](docs/loading_real_data.md) | How to replace the stand-in with the published files — one command, ten minutes |
| [`docs/limits.md`](docs/limits.md) | What it costs, where the free tier stops, and what breaks first |
| [`docs/runbook.md`](docs/runbook.md) | What to do when something is wrong, written for whoever gets the alert |
| [`docs/security.md`](docs/security.md) | The OWASP ASI mapping and the red-team results, generated from the register and the last measured run |
| [`docs/term4_yieldmap.ipynb`](docs/term4_yieldmap.ipynb) | Every model, with its plots and the tables the report cites |

The report and the slide deck are **deliberately not generated yet**:
`scripts/guard_synthetic.py` blocks generated figures from reaching a submitted artefact, and it
currently blocks. That is the guard working, not a gap — the documents above describe method rather
than figures, which is why they are here.

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
