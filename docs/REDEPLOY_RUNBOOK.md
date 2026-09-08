# Redeploy runbook

For a version of me with no memory of building this, working from a downloaded zip of the GitHub
repository, months from now. Numbered steps, in order, with the fast path first.

Nothing here needs anything that is not either in this repository or in your password manager.
Every real secret comes from the password manager. None of them are in the repository, and none of
them should be put there to make a step easier.

**Rough time:** about 35 minutes restoring from a database snapshot, about 50 minutes re-running
ingestion instead. Most of both is waiting for builds.

---

## 1. Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.12 | pinned in `pyproject.toml` and `render.yaml` |
| [uv](https://docs.astral.sh/uv/) | any recent | installs from `uv.lock`, so the environment is the tested one |
| Node.js | 20+ | the web app |
| Git | any | |
| `psql` / `pg_dump` | 16+ | only if restoring or taking a database snapshot |
| [Ollama](https://ollama.com) | optional | only for the local model tier |

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra dev            # Python, from the lockfile
npm ci                         # web app
uv run pytest -q               # 1,008 tests should pass offline, with no keys
```

The suite passing from a cold clone is the check that the zip is complete. It runs with
`LLM_PROVIDER=fake`, so it needs no key and no network.

---

## 2. Create the services and connect the repository

Push the clone to a GitHub repository you own first — Render and Vercel deploy from Git, not from
a folder.

**Render (the API).** New → Blueprint, point it at the repository. `render.yaml` defines the
service, the build and the start command. Everything marked `sync: false` in that file is a value
Render will ask you for; see step 4.

**Vercel (the web app).** New Project → import the repository. Set the root directory to `web/`.
`vercel.json` supplies the rest, including the build-skip gate. No `NEXT_PUBLIC_` variable carries
the API URL — the proxy at `web/app/api/[...path]/route.ts` reads `API_ORIGIN` per request, which
is why one build works against local, preview and production.

**Supabase (Postgres, optional).** Only needed for durable memos. Without `DATABASE_URL` the API
falls back to a file store and `GET /health` reports `store.durable: false`, which is a working
service that loses memos on restart.

---

## 3. Get the database into shape

**Fast path — restore a snapshot.** Check `data/snapshot/` for a `.sql.gz`, or the releases page
for one attached to a `db-snapshot-*` tag.

```bash
export DATABASE_URL='postgresql://...'          # from your password manager
gunzip -c data/snapshot/AI217_YIELDMAP_<date>.sql.gz | psql "$DATABASE_URL"
```

**If there is no snapshot — apply the migrations.** Read `db/migrations/0002_yieldmap_schema.sql`
first; it explains why there are two files and which one you need.

```bash
psql "$DATABASE_URL" -f db/migrations/0002_yieldmap_schema.sql   # required
# 0001 only if YIELDMAP owns this database rather than sharing it — it creates unqualified
# tables in `public`, which on a shared database is somebody else's namespace.
```

Doing nothing at all also works: the application issues the same statements as `0002` the first
time it opens a durable store.

---

## 4. Set the environment variables

Every name is in `.env.example`, with a comment saying what it does. **The names are in the
repository; the values are not, and must come from your password manager.** Set them in Render →
`yieldmap-api` → Environment.

| Variable | Where the value comes from | If unset |
|---|---|---|
| `AUTH_SECRET` | Render generates it (`generateValue: true`) | service refuses to start when `YIELDMAP_ENV=production` |
| `YIELDMAP_USERS` | your password manager; regenerate a hash with `uv run python -m api.auth hash 'password'` | no account can write |
| `DATABASE_URL` | Supabase → Settings → Database → session pooler or direct | memos go to an ephemeral file store |
| `DATABASE_SCHEMA` | `yieldmap` — already in `render.yaml` | defaults to `yieldmap` in code |
| `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> | chain falls through to the offline backend, answers marked degraded |
| `LLM_PROVIDER` | `gemini` | **a value already set in the dashboard wins over `render.yaml`** |
| `SENTRY_DSN` | optional | error tracking stays off |

> The one that has caught us before: setting `GEMINI_API_KEY` while `LLM_PROVIDER` is still `fake`
> changes nothing, because `fake` pins the offline backend rather than starting a chain at it. The
> symptom is that nothing changes. Check the deploy log's `started` line — it carries `llm_chain`
> and `llm_first_available` — or `GET /ask/providers`.

---

## 5. Get data in

**If you restored a snapshot, skip this** — but note the snapshot only carries application state.
The analytics warehouse is derived and is rebuilt on every Render build by
`uv run python -m scripts.build_all --synthetic`, which is already the blueprint's build command.

**For real registry data**, the honest position is in `docs/datasets.md`: the Dubai Land
Department's portal refuses automated clients from every network tried, including a GitHub Actions
runner with open egress, so the download cannot be automated. A person can download the files in a
browser. Then:

```bash
uv run python -m scripts.ingest_upload ~/Downloads --build
uv run python -m scripts.guard_synthetic     # must exit 0 before any Term 4 artefact
```

**To try the automated path anyway** — worth doing, since the block may lift — run the
`Ingest DLD open data` workflow from the Actions tab. It probes every candidate address, records
what each returned in `docs/results/source_probe.json`, and downloads anything it can reach. It is
honest about failing: a run that downloads nothing now reports failure rather than success.

---

## 6. Local model tier (optional)

Only if you want the Ollama rung of the provider chain. Exact tags, from `docs/models.md`:

```bash
ollama pull llama3.1:8b        # generation
```

Embeddings have no local tier — `gemini-embedding-001` truncated to 768 dimensions, cached to
disk, is what the spike in `docs/models.md` settled on. Without a key, retrieval falls back to
offline TF-IDF and says so.

---

## 7. Verify

In order. Each one fails differently, which is the point.

```bash
# 1. The API is up and knows its own configuration
curl -s https://<your-api>.onrender.com/health | python3 -m json.tool
#    expect: status ok · auth.configured true · store.durable true (if DATABASE_URL is set)

# 2. The model tier is what you think it is
curl -s https://<your-api>.onrender.com/ask/providers | python3 -m json.tool
#    expect: chain ["gemini","groq","fake"] — a bare ["fake"] means LLM_PROVIDER was not changed

# 3. The full journey, on a real browser, desktop and phone
npx playwright test            # 78 tests
```

**The core flow to click through by hand**, which is what `e2e/journey.spec.ts` automates: open
the city page, pick a community, open a KPI tile and confirm the drawer shows the SQL behind the
number; then go to Ask, ask a question, and confirm the answer carries citations.

**Governance:** open `/security` and confirm the OWASP scorecard still reports every control
holding. It is generated from `docs/results/redteam.json`, which CI regenerates, so a stale green
tick is not possible.

---

## 8. Regenerating the Term 4 documents

```bash
uv run --extra docs python -m scripts.build_report --draft
uv run --extra docs python -m scripts.build_deck --draft
```

Both read `docs/results/` and restate nothing from memory. `--draft` is required while
`scripts/guard_synthetic.py` blocks — it stamps every generated figure on the cover, in a
provenance column in each table, and in the limitations section. Once real data is loaded the
guard passes, `--draft` is no longer accepted as necessary, and the provenance column disappears
because it has nothing left to say.

---

## What breaks first, and what it looks like

| Symptom | Cause | Fix |
|---|---|---|
| First request takes ~50 s | Render free tier sleeps after 15 minutes idle | expected; wake it before demonstrating |
| Answers say "offline fixture backend" | `LLM_PROVIDER` is `fake`, or no key | step 4 |
| Memos vanish on restart | `DATABASE_URL` unset | step 4; `/health` reports it |
| Web app returns 502 naming the API | API asleep or not deployed | the error names which service is down, by design |
| `guard_synthetic` exits 1 | the warehouse holds generated rows | expected until real data is loaded; step 5 |
