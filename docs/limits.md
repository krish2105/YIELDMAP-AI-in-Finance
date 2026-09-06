# Operating limits

What this costs, where it stops working, and what breaks first. Figures come from
`docs/results/unit_economics.json`, computed by `finance/unit_economics.py` from the same request
counts the quota ledger records.

## Cost

**$0.00 per month, and structurally rather than by restraint.** The provider chain is a local
model, then two free tiers, then a deterministic offline backend. The paid backend exists in the
code and refuses to run behind two separate switches, because a zero-cost claim should not be one
stray environment variable away from being false.

Quotas count **requests**, not tokens, because that is how the free tiers meter. The ledger is
durable across processes, so a nightly job and an interactive session share one daily allowance
rather than each spending it.

## Where the free tier stops

| A day like this | Model requests | Share of the free tier | Binds on |
|---|---|---|---|
| A demo day — 20 questions, 3 memos, 200 page loads | 38 | 2.6% | embeddings |
| A busy course week, per day — 150 questions, 25 memos | 300 | 20.0% | generation |
| **A hundred daily users** — 800 questions, 120 memos | 1,520 | **104%** | **embeddings** |

**The cliff is at roughly a hundred daily active users**, and the first thing to break is the
embedding allowance, not generation — which is the opposite of the intuitive answer and the reason
embeddings are cached to disk per chunk rather than recomputed per question.

What to do at that point, cheapest first: raise the embedding cache hit rate (chunks change far
less often than questions arrive); move embeddings to the offline TF-IDF path, which costs nothing
and is what CI already runs against; then pay for generation, which is metered per token and would
be a few dollars a month at that volume.

## Latency, which is the real cost of the free tier

The API sleeps after 15 minutes idle and takes about **50 seconds** to wake. For a demo that means
loading the site once before presenting. For a product it means the first visitor of the hour has
a bad time, and it is the single strongest argument for the $7/month paid instance — not capacity,
responsiveness.

## Vercel Hobby prohibits commercial use

The front end is deployed on Vercel's Hobby plan, whose terms **do not permit commercial use**.
This is fine for what the project is today — a portfolio piece and a course submission — and it
becomes a terms violation the moment there is a paying customer.

Two ways out, neither urgent and both cheap:

1. **Vercel Pro, $20/month.** Nothing changes but the plan.
2. **Move the front end alongside the API on Render.** The application is a standard Next.js
   server; `render.yaml` already describes one Python service, and a Node service beside it would
   run `next start`. The API proxy already reads its target per request, so the only change is an
   environment variable. Nothing in the code is Vercel-specific.

Recording this rather than fixing it now is deliberate: switching costs money or effort today to
solve a problem that starts on the day of first revenue, and the honest answer to "could you sell
this?" is better than a bill.

## Build minutes

The nightly ingest commits its own output — probe results, archived source pages — and each of
those commits triggered a full front-end build producing a byte-identical deployment. Two such
builds ran in one evening before anyone noticed.

`scripts/vercel_should_build.sh` now decides: a commit touching only `docs/`, `corpus/`, the
Python half or the workflows skips the build. It is deliberately conservative — anything not
clearly irrelevant builds, because a skipped build that should have run ships stale code, which is
far worse than a wasted minute. `config/` is explicitly *not* skippable: `web/lib/kpi.ts` imports
`config/kpi_thresholds.json` at build time, so a threshold change has to reach the bundle.
Eighteen tests cover both directions, and the "must build" cases are the ones that matter.

## Storage

Memos go to Postgres when `DATABASE_URL` is set and to a file store otherwise. On a free-tier
container the file store is **ephemeral**: no persistent disk, and the instance sleeps, so every
memo is lost on restart. `GET /health` reports `store.durable` so this is visible from outside
rather than being something you have to know.

Neither free Postgres slot on the current account is available — both belong to other projects —
so the deployment runs on the ephemeral store today. The durable path is written and tested in CI
against a real Postgres; enabling it is one environment variable.

## Rate limits

Per caller, keyed on the account when signed in and the client address otherwise:

| Surface | Allowance | Why |
|---|---|---|
| Reads | 120 / minute | Stops a scraper, not a person |
| `/ask` | 12 / minute | Spends a model request per question |
| `/memos` | 6 / hour | Runs the agent crew; also requires an analyst credential |
| `/auth/token` | 10 / 15 minutes | Makes password guessing impractical |

Buckets live in the process. That is exact on one instance and would need a shared counter on two,
which is the change to make before scaling horizontally rather than after.

## What is not limited, and should be before real users

- **No per-account quota.** The rate limiter bounds the speed of one caller, not their total for a
  month. Two analysts could between them spend the day's model allowance legitimately.
- **No alerting.** Errors reach Sentry when a DSN is configured; nothing pages anyone.
- **One region, one instance.** No redundancy, and the sleep behaviour above.
