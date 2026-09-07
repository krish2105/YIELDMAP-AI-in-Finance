# Loading the real Dubai Land Department data

Everything in this project is built and tested against a labelled stand-in. Replacing it with the
published files changes every number on the site and requires no code change. This is the
procedure, and it takes about ten minutes.

## Why a person has to do this

Two separate obstacles, both measured rather than assumed.

**Dubai Pulse refuses datacenter addresses**, and as of 2026-09-07 it was not answering an ordinary
browser either — `ERR_CONNECTION_TIMED_OUT` from a residential connection, and `ConnectTimeout`
from a GitHub Actions runner. `docs/results/source_probe.json` records the runner side. Whether
that is an outage or a geo-restriction is not something this repository can determine.

**The Land Department's own portal works**, and is the same publisher:

<https://dubailand.gov.ae/en/open-data/real-estate-data/>

It answered 200 in the same probe that timed out on Dubai Pulse. It is a *query* interface rather
than a bulk download: pick a date range, solve a CAPTCHA, and export what matches. Its own banner
says *"For previous year data kindly visit Dubai Pulse"*, so the deep history lives on the portal
that is down and this one serves the recent window.

So this is not a workaround for a missing feature. It is the correct route to published files,
taken by the one kind of client the publisher serves.

## 1. Download

Open <https://dubailand.gov.ae/en/open-data/real-estate-data/> and export twice:

| Tab | What it is |
|---|---|
| **Transactions** | every recorded sale and purchase |
| **Rents** | registered Ejari tenancies |

On each tab: set **From Date** as far back as it allows, leave every other filter on **All**, solve
the CAPTCHA, **Search**, then **Download as CSV**.

**If a wide range times out, narrow it and download several.** A year at a time is fine — put every
file in one folder and the loader reads them all. Overlapping ranges cost nothing, because rows are
deduplicated by transaction id. This matters for the repeat-sales index in particular, which needs
pairs of sales of the *same unit* years apart, so a single recent slice will not support it.

If Dubai Pulse comes back, its bulk CSVs are the better source — one file per table, full history —
and the same command below reads them without change.

## 2. Load

```bash
uv run python -m scripts.ingest_upload ~/Downloads --build
```

That is the whole thing. It:

- looks at every file in the folder, including inside `.zip` archives;
- works out which is the transactions extract and which is the rents extract **by their columns**,
  not their names, because the portal calls them whatever it likes;
- **keeps every file that matches a table**, not just the best one, so a year-by-year download
  loads in full — they land as `transactions__000.csv`, `__001` and so on, and the cleaner reads
  the set;
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

## If it says the file is not UTF-8

Dubai's registry data is full of Arabic names, and the loader refuses a file it cannot read as
UTF-8 rather than guessing at the encoding. Guessing is the tempting fix and the wrong one: the
wrong codepage does not fail, it turns every Arabic area name into a different string, and every
figure on the site is grouped by area.

The message names the file and the conversion:

```bash
iconv -f WINDOWS-1256 -t UTF-8 'Transactions.csv' > 'Transactions-utf8.csv'
```

UTF-8 and UTF-8 with a byte-order mark both load unchanged — the second is what Excel writes, so
opening a CSV to look at it before uploading is safe.

## If the columns have moved

The publisher renames columns occasionally. `etl/schema.py` holds the aliases, and
`scripts/ingest_upload.py` will tell you exactly which required column it could not find. Add the
new name to the alias tuple; nothing else needs touching.
