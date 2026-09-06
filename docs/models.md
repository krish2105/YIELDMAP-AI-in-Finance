# Model choices

What this project runs, why, and what was measured. The governing constraint is that inference
costs nothing, so every choice here is bounded by what is available free.

## Generation

The provider chain is **Ollama → Gemini → Groq → offline fixtures**, with an Anthropic backend
present in the code and switched off. Enabling the paid backend needs both a key and an explicit
opt-in flag, and even fully configured it refuses to run — two switches rather than one, because a
zero-cost claim should not be one stray environment variable away from being false.

| Backend | Model | Role | Status in this environment |
|---|---|---|---|
| Ollama | `llama3.1:8b` | local, private, unmetered | absent — the binary is not installed in the cloud sandbox |
| Gemini | `gemini-2.5-flash` | primary remote free tier | reachable; needs `GEMINI_API_KEY` |
| Groq | `llama-3.3-70b-versatile` | second remote free tier | unreachable from this sandbox; kept for the deployed API |
| Offline fixtures | none | deterministic answers for CI | always available |
| Anthropic | — | present, off | refuses by design |

Falling through is the normal case rather than an error path. In this sandbox the chain skips
three tiers and lands on the offline backend; in CI it is pinned there so tests cannot reach the
network. Every hop is recorded, so the interface can show which backend actually answered and the
report can state honestly how often the system degraded.

Quotas are counted in **requests**, not tokens, because that is how the free tiers meter. The
ledger is durable across processes, since a nightly job and an interactive session share one daily
allowance and a counter that reset on restart would let the same allowance be spent twice.

## Embeddings

**Decision: Gemini `gemini-embedding-001` truncated to 768 dimensions, cached to disk, fused with
BM25 by reciprocal rank fusion, with a TF-IDF/SVD fallback that needs no network.**

### Why the choice was constrained before it was made

The plan called for a spike comparing local sentence-transformer embeddings against an API tier.
That comparison cannot be run here: `huggingface.co` and its CDN are blocked by this environment's
network policy, so no model weights can be downloaded at all. That removes local embeddings and the
local cross-encoder reranker from the option set entirely — not as a preference, but as a fact
about what can be installed.

What remains:

| Option | Dimensions | Needs network | Semantic | Cost |
|---|---|---|---|---|
| Gemini embeddings | 768 (truncated from 3072) | yes, once per chunk | yes | free tier, request-metered |
| TF-IDF + SVD, fitted on the corpus | 256 | no | weakly — co-occurrence, not meaning | none |
| BM25 | n/a | no | no — lexical only | none |
| Offline fixtures | 768 | no | no — hash-derived | none |

### Why 768 dimensions

`gemini-embedding-001` emits 3072 by default and supports Matryoshka truncation. pgvector's HNSW
index does not support vectors that wide, so an untruncated embedding could be stored but not
indexed, which defeats the purpose. 768 is the widest setting that stays indexable, and truncation
is the mechanism the model is designed for rather than a lossy hack.

### Why the vectors are cached

Quota is spent per request, so embedding a chunk twice costs twice. Embeddings are cached to disk
keyed by the hash of the text, which means re-indexing an unchanged corpus is free, and the day's
allowance is spent on new material only.

### Why retrieval is hybrid rather than purely vector

Two reasons, one principled and one practical.

The principled one: this corpus mixes prose with structured facts. A question naming an exact area
or a specific decree is answered better by lexical matching than by semantic similarity, and BM25
is very good at exactly that. Fusing the two by reciprocal rank fusion takes the strengths of both
without needing to tune a weight between incomparable scores.

The practical one: BM25 needs no network, no key and no quota. When the embedding tier is
unreachable or its allowance is spent, retrieval degrades to lexical rather than failing, and the
answer says so.

### What is still pending

The empirical part of the spike — measured recall@5 for Gemini embeddings against the TF-IDF/SVD
baseline on the thirty-case set — needs `GEMINI_API_KEY`, which is not yet provided. The harness
is built and runs offline today against the fallback, so supplying the key produces the comparison
without any further work. Until then the eval reports the lexical baseline's score, and labels it
as such.

## Reranking

No local cross-encoder is downloadable, so reranking is done by asking the generation model to
order candidates, with a lexical fallback when no model is reachable. This is slower per query than
a cross-encoder and costs a request, so it runs only on the shortlist rather than the full
candidate set.

## Forecasting and valuation

Not language models, and chosen on measured performance rather than availability. Both are recorded
in `docs/results/`: the hedonic model is scored against a cell-median baseline and against the
data's own irreducible noise, and the forecast against a seasonal naive benchmark on a held-out
year. See `docs/term4_yieldmap.ipynb` for the charts.
