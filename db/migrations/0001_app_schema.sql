-- YIELDMAP application schema — the intended one, and NOT what is deployed.
--
-- Read 0002_yieldmap_schema.sql before applying this. As of the Term 4 archival pass this file
-- had never been run: the deployed database is shared with another project, and the only YIELDMAP
-- object in it is yieldmap.memo, which the application creates for itself. These tables are
-- unqualified, so applying this to a shared database creates them in `public`, alongside somebody
-- else's. Apply it only when YIELDMAP owns the database.
--
-- This database holds application state only: users, memos, agent runs, the document corpus and
-- its embeddings. The property analytics live in DuckDB, because 1.5 million transactions plus
-- indexes do not fit a 500 MB free tier, and because keeping the analytics in DuckDB lets every
-- KPI carry the literal SQL that produced it.
--
-- Embedding width is 768. Gemini's embedding model emits 3072 by default but supports
-- Matryoshka truncation, and pgvector's HNSW index tops out below 3072 dimensions, so 768 is the
-- widest choice that stays indexable. The Task 15 spike records the measured trade-off.

create extension if not exists vector;
create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- identity

create type user_role as enum ('viewer', 'analyst', 'admin');

create table app_user (
    id          uuid primary key default gen_random_uuid(),
    email       text not null unique,
    role        user_role not null default 'viewer',
    locale      text not null default 'en',
    created_at  timestamptz not null default now()
);

-- ----------------------------------------------------------------- corpus

create table document (
    id          uuid primary key default gen_random_uuid(),
    kind        text not null check (kind in ('law', 'rera', 'service_charge', 'community', 'memo')),
    title       text not null,
    source_url  text,
    path        text,
    -- Content hash, so a citation always points at a fixed version of a document.
    sha256      text not null,
    retrieved_at timestamptz,
    created_at  timestamptz not null default now(),
    unique (sha256)
);

create table chunk (
    id          uuid primary key default gen_random_uuid(),
    document_id uuid references document (id) on delete cascade,
    -- Either a document chunk or a row of structured context; exactly one of the two.
    table_ref   text,
    ordinal     int not null default 0,
    text        text not null,
    lang        text not null default 'en',
    embedding   vector(768),
    meta        jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now(),
    constraint chunk_has_one_source check (
        (document_id is not null and table_ref is null)
        or (document_id is null and table_ref is not null)
    )
);

create index chunk_document_idx on chunk (document_id);
create index chunk_lang_idx on chunk (lang);
-- Cosine distance: embeddings are compared by direction, not magnitude.
create index chunk_embedding_idx on chunk using hnsw (embedding vector_cosine_ops);
-- Lexical half of hybrid retrieval, so BM25-style matching survives an empty embedding cache.
create index chunk_text_idx on chunk using gin (to_tsvector('simple', text));

-- ------------------------------------------------------------- agent runs

create type run_status as enum ('running', 'succeeded', 'failed', 'killed', 'over_budget');

create table agent_run (
    id             uuid primary key default gen_random_uuid(),
    user_id        uuid references app_user (id) on delete set null,
    goal           text not null,
    status         run_status not null default 'running',
    -- Budgets are request counts and seconds, never money: this project spends no money on
    -- inference and the ledger has to be able to prove it.
    requests_used  int not null default 0,
    requests_limit int not null,
    seconds_used   numeric(10, 2) not null default 0,
    seconds_limit  int not null,
    provider_hops  jsonb not null default '[]'::jsonb,
    started_at     timestamptz not null default now(),
    finished_at    timestamptz
);

create table agent_message (
    id          uuid primary key default gen_random_uuid(),
    run_id      uuid not null references agent_run (id) on delete cascade,
    ordinal     int not null,
    sender      text not null,
    recipient   text,
    kind        text not null,
    body        jsonb not null,
    -- Signature over (run_id, ordinal, sender, body); the bus rejects an unsigned message.
    signature   text not null,
    created_at  timestamptz not null default now(),
    unique (run_id, ordinal)
);

create table audit_finding (
    id          uuid primary key default gen_random_uuid(),
    run_id      uuid not null references agent_run (id) on delete cascade,
    severity    text not null check (severity in ('info', 'warn', 'block')),
    rule        text not null,
    detail      text not null,
    created_at  timestamptz not null default now()
);

create index audit_finding_run_idx on audit_finding (run_id);

-- ------------------------------------------------------------------ memos

create table memo (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid references app_user (id) on delete set null,
    run_id      uuid references agent_run (id) on delete set null,
    query       text not null,
    memo_md     text not null,
    -- One entry per factual sentence. A memo with an uncited fact is rejected before it is stored.
    citations   jsonb not null default '[]'::jsonb,
    -- REAL or SYNTHETIC: a memo written from the stand-in must say so wherever it is shown.
    provenance  text not null default 'REAL' check (provenance in ('REAL', 'SYNTHETIC')),
    created_at  timestamptz not null default now()
);

create index memo_user_idx on memo (user_id, created_at desc);

-- ----------------------------------------------------------------- memory

create table agent_memory (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid references app_user (id) on delete cascade,
    scope        text not null,
    text         text not null,
    embedding    vector(768),
    -- Memory is untrusted input: it is quarantined by the Auditor rather than deleted, so a
    -- poisoning attempt stays inspectable after the fact.
    quarantined  boolean not null default false,
    quarantine_reason text,
    created_at   timestamptz not null default now()
);

create index agent_memory_user_idx on agent_memory (user_id) where not quarantined;

-- --------------------------------------------------------------- freshness

create table data_freshness (
    table_name   text primary key,
    rows         bigint not null,
    as_of        date,
    provenance   text not null check (provenance in ('REAL', 'SYNTHETIC')),
    source_sha256 text,
    refreshed_at timestamptz not null default now()
);
