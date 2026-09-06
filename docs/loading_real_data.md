# Loading the real Dubai Land Department data

Everything in this project is built and tested against a labelled stand-in. Replacing it with the
published files changes every number on the site and requires no code change. This is the
procedure, and it takes about ten minutes.

## Why a person has to do this

Dubai Pulse publishes the bulk CSVs openly, and refuses connections from datacenter addresses —
every request from a GitHub Actions runner times out at connect, while the same URLs load normally
in a browser on an ordinary connection. `docs/results/source_probe.json` records the measurement.

So this is not a workaround for a missing feature. It is the correct route to exactly the same
published files, taken by the one kind of client the publisher serves.

## 1. Download

Open <https://www.dubaipulse.gov.ae/organisation/dld> in a normal browser and download:

| Dataset | What it is | Roughly |
|---|---|---|
| **Transactions** (`dld_transactions`) | every recorded sale and purchase, 2004 onward | 300–600 MB |
| **Rent contracts** (`dld_rent_contracts`) | registered Ejari tenancies | 300–800 MB |

Take the **full CSV export** of each, not a filtered view — the models want the whole history, and
the repeat-sales index in particular needs pairs of sales of the same unit, which a recent slice
does not contain.

If the site offers a date-partitioned set instead of one file, download them all into one folder.
The next step reads a folder.

## 2. Load

```bash
uv run python -m scripts.ingest_upload ~/Downloads --build
```

That is the whole thing. It:

- looks at every file in the folder, including inside `.zip` archives;
- works out which is the transactions extract and which is the rents extract **by their columns**,
  not their names, because the portal calls them whatever it likes;
- keeps the fuller extract when two files match the same table;
- ignores anything that is not one of them, and says so rather than guessing;
- removes the `SYNTHETIC` marker, which is what stamps every downstream row as generated;
- rebuilds the warehouse, the ten model stages and the retrieval index.

Add `--dry-run` first if you want to see what it would do without writing anything.

## 3. Check

```bash
uv run python scripts/guard_synthetic.py     # should now pass
uv run python -m security.redteam --gate
uv run pytest -q
```

The provenance guard is the one that matters. While any generated row remains it blocks, and that
block is deliberate: it is what stops a figure computed from invented data reaching a submitted
report. Once it passes, the Term 4 artefacts are unblocked.

Then commit the refreshed results and push — the deployed API rebuilds its warehouse during its
own build, so it picks the new data up on the next deploy.

## What changes

Every figure in the README's measured table, on all twenty pages, and in the notebook. The banner
saying the numbers are generated disappears on its own, because it is driven by the provenance
column rather than by a setting.

What does **not** change: any code. That is the point of having built it this way.

## If the columns have moved

The publisher renames columns occasionally. `etl/schema.py` holds the aliases, and
`scripts/ingest_upload.py` will tell you exactly which required column it could not find. Add the
new name to the alias tuple; nothing else needs touching.
