-- What the deployment actually has.
--
-- 0001_app_schema.sql describes the full application schema this project was designed around:
-- users, documents, chunks with embeddings, agent runs, messages, audit findings, memories and
-- freshness. It was never applied. The deployed database is a Supabase project shared with
-- another piece of coursework, and the only YIELDMAP object in it is the memo table, created at
-- runtime by agents/store.py the first time a durable store is opened.
--
-- That gap was found during the Term 4 archival pass, by listing the live database rather than
-- reading the repository: `public` held another project's tables and `yieldmap` held exactly one
-- of ours. A migration file that describes an intended schema and a database that has a different
-- one is the failure mode this file exists to close — restoring from this repository now
-- reproduces what is deployed, rather than what was planned.
--
-- Apply order:
--   0001  optional. Run it only when YIELDMAP owns its database. On a shared one it creates
--         unqualified tables in `public`, which is somebody else's namespace.
--   0002  required. This is what the running service needs, and what it would otherwise create
--         for itself on first write.
--
-- Idempotent throughout, because agents/store.py issues the same statements on startup: applying
-- this file to a database the service has already touched is a no-op rather than an error.

-- The namespace. It exists because the database is shared: every statement the application issues
-- names this schema explicitly, so neither project can reach the other's tables even under a
-- transaction pooler, where a search_path set once per session cannot be relied on.
create schema if not exists yieldmap;

create table if not exists yieldmap.memo (
    id            text primary key,
    run_id        text not null,
    area_key      text not null,
    memo_md       text,
    citations     jsonb not null default '[]'::jsonb,
    disagreements jsonb not null default '[]'::jsonb,
    findings      jsonb not null default '[]'::jsonb,
    audit         jsonb not null default '{}'::jsonb,
    budget        jsonb not null default '{}'::jsonb,
    status        text not null,
    -- REAL or SYNTHETIC, carried with the memo so a figure written from generated data still says
    -- so wherever the memo is read, including from another service.
    provenance    text not null,
    user_id       text,
    created_at    timestamptz not null default now()
);

create index if not exists memo_created_idx on yieldmap.memo (created_at desc);

-- Row Level Security is NOT enabled on this table, and that is worth stating rather than leaving
-- to be discovered. The application reaches it over a direct Postgres connection with the service
-- credential, where RLS would not apply anyway. The exposure is Supabase's REST layer: on a shared
-- project, anyone holding that project's anon key can reach this table through it.
--
-- Enabling RLS without policies blocks all access, including the service's own, so it is not done
-- here. The fix, when this database stops being shared or when the anon key is exposed publicly:
--
--     alter table yieldmap.memo enable row level security;
--     create policy memo_service_all on yieldmap.memo
--         for all to service_role using (true) with check (true);
--
-- Deciding that is an operator's call, not a migration's.
