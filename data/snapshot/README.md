# Database snapshots

Empty on purpose, and the reason is worth recording rather than leaving as an absence.

## Why there is no snapshot committed

Two facts, both checked during the Term 4 archival pass rather than assumed:

1. **There is almost nothing to snapshot.** The Postgres database holds application state only —
   the analytics live in DuckDB and are rebuilt from source by `scripts/build_all.py`. Listing the
   live database found exactly one YIELDMAP table, `yieldmap.memo`, holding **0 rows**. A dump of
   it would be a schema and no data, and `db/migrations/0002_yieldmap_schema.sql` already carries
   that schema in a form a human can read.
2. **The credential is deliberately not in this repository.** `DATABASE_URL` is `sync: false` in
   `render.yaml`, which means Render holds it and the blueprint does not. Taking a dump requires it,
   and putting it here to make that convenient would defeat the arrangement.

So the commands are documented and the snapshot is not taken. When there are memos worth keeping,
run the first command below and commit the result here.

## Taking one

```bash
# The connection string comes from your password manager or Render → yieldmap-api → Environment.
# Never paste it into a file in this repository.
export DATABASE_URL='postgresql://...'

pg_dump "$DATABASE_URL" \
  --no-owner --no-privileges \
  --schema=yieldmap \
  | gzip > "data/snapshot/AI217_YIELDMAP_$(date +%Y%m%d).sql.gz"
```

`--schema=yieldmap` matters on this deployment: the database is shared with another project, and a
dump without it captures their tables too.

## Committing it, or releasing it

Under about 50 MB, commit it here. Larger, attach it to a release instead and record the URL in
`docs/REDEPLOY_RUNBOOK.md` rather than committing the file:

```bash
gh release create db-snapshot-$(date +%Y%m%d) \
  data/snapshot/AI217_YIELDMAP_$(date +%Y%m%d).sql.gz \
  --notes "Database snapshot for archival"
```

## Restoring

```bash
gunzip -c data/snapshot/AI217_YIELDMAP_<date>.sql.gz | psql "$DATABASE_URL"
```

Restoring from a snapshot is faster than re-running ingestion, and it is the first option in the
runbook. Re-ingestion remains the fallback when no snapshot exists or the one you have is stale —
it works because every data source is public and the build is reproducible from a seed.

## What is deliberately not in a snapshot

No table here stores a credential. Accounts are not in the database at all: they come from the
`YIELDMAP_USERS` environment variable as `email:role:argon2-hash`, so a dump of this database
contains no password material, hashed or otherwise. That was checked, not assumed — `yieldmap.memo`
is the only table, and its columns are listed in the migration.
