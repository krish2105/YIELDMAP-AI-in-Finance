# Datasets

Every dataset used by YIELDMAP is public open data published by the Dubai Land Department (DLD),
mostly through the Dubai Pulse open-data portal. **No portal listings are scraped.** Each source
below is recorded with its licence and the date the ingest job retrieved it.

## How data reaches this project

Downloads run inside GitHub Actions, not in a developer sandbox, because the sandbox's network
policy blocks the government domains (see `CLAUDE.md` for the measured evidence). The workflow
`.github/workflows/ingest.yml` fetches each source, records an SHA-256 and a retrieval timestamp,
and publishes the result as a GitHub Release asset that the rest of the pipeline consumes.

### What the retrieval attempts established

Measured from a GitHub Actions runner on 2026-09-06, recorded in `docs/results/source_probe.json`
and `docs/results/spa_discovery.json`:

| Host | Result |
|---|---|
| `dubailand.gov.ae` | reachable — the open-data, services and rental-index pages all return 200 |
| `www.dubaipulse.gov.ae` | every address times out at connect, which reads as a block on datacenter addresses rather than a wrong path |
| `gateway.dubailand.gov.ae` | reachable, answers as a JSON API (404 at the root) |
| `centralbank.ae` | 403 to an automated client |

The DLD open-data page returns almost no HTML: its dataset list and download links are built
client-side by the site's own `scripts/api/OpenDataApi.js`, so a plain fetch finds nothing. The
ingest job therefore drives a real browser and harvests the endpoints out of that script.

Driving the page in a browser resolved the question fully. It renders 127 links across nine dataset
tabs — transactions, rents, projects, valuations, land, buildings, units, brokers, developers — and
each tab fetches its rows through the site's own API rather than offering a file. For **bulk
downloads the page links out to Dubai Pulse** (`dubaipulse.gov.ae/organisation/dld`), which is the
host that refuses automated clients.

So the position is settled and is not a matter of finding the right URL: the bulk CSVs exist, are
open, and are published only on a host that will not serve them to a datacenter address. A person
browsing from an ordinary connection is unaffected, which makes the operator upload below the
correct route to exactly the same published files, rather than a workaround.

### Uploading the files (rung 2)

1. Open `https://www.dubaipulse.gov.ae/organisation/dld` in an ordinary browser.
2. Download the transactions and rent-contracts CSVs. A single recent year is enough to start.
3. In this repository: **Releases → Draft a new release**, tag it `data-YYYY-MM`, attach the files,
   and publish.
4. The ingest job reads release assets, so the next run picks them up, rebuilds the database and
   recomputes every model against real numbers.

The retrieval ladder, in order:

1. **Actions download** direct from the publisher.
2. **Operator upload** — the same publisher CSV attached to a GitHub Release by hand.
3. **Labelled synthetic fixture** — schema-faithful generated rows used only to exercise the
   pipeline. Synthetic rows carry `provenance = 'SYNTHETIC'`, surface a banner in the UI, are
   recorded as synthetic in every results file, and are blocked from every Term 4 artefact by
   `scripts/guard_synthetic.py`.

Which rung a given table came from is recorded in `docs/results/provenance.json` and in the
`provenance` column of every table.

## Sources

| Dataset | Publisher | Contents | Licence | Retrieved |
|---|---|---|---|---|
| Real-estate transactions | DLD via Dubai Pulse | unit-level sales and other procedures, 2004 onward | Open data, attribution to DLD | recorded by the ingest job |
| Rent contracts (Ejari) | DLD via Dubai Pulse | registered tenancy contracts with annual rent | Open data, attribution to DLD | recorded by the ingest job |
| Valuations | DLD via Dubai Pulse | official valuation records | Open data, attribution to DLD | recorded by the ingest job |
| Projects | DLD via Dubai Pulse | registered projects and completion status | Open data, attribution to DLD | recorded by the ingest job |
| Buildings and units | DLD via Dubai Pulse | building register | Open data, attribution to DLD | recorded by the ingest job |

Row counts, column lists, date ranges and null rates are measured rather than asserted — see
`docs/results/profile.json`, produced by `etl/profile.py`. The table below is generated from that
file by the ingest job, so it cannot drift from the data.

<!-- profile:start -->
No profile has been produced yet. Run the ingest workflow (`.github/workflows/ingest.yml`); it
writes `docs/results/profile.json` and regenerates this table.
<!-- profile:end -->

## Reference documents (RAG corpus)

The ingest job also archives the primary sources that the Ask feature and the mortgage parameters
cite, each with an SHA-256 and a retrieval date, so a citation always points at a fixed document.

| Document | Why it is needed |
|---|---|
| Dubai rent-increase decree and RERA rental index guidance | answers "can my landlord raise rent" and the rent calculator |
| DLD fee schedule | the 4% transfer fee and registration costs in net yield and DCF |
| UAE Central Bank mortgage regulation | LTV and debt-burden caps in `config/mortgage.yaml` |
| Ejari guidance | how tenancy registration works, for the rent pages |

Until the ingest job has archived a given document, the parameters that depend on it are marked
`status: unverified` in `config/mortgage.yaml` and are shown in the UI as editable assumptions
rather than as facts.

## Area geometry

No reachable source publishes community polygons for Dubai under an open licence from this
environment. `data/areas.csv` therefore holds approximate centroids for the named DLD areas, and the
3D city renders extruded hex cells around those centroids rather than true boundaries. These
coordinates are cartographic only — **they never enter a financial calculation** — and the
limitation is stated in the report.

## Known data limitations

- Older transaction rows lack a stable unit identifier, so the repeat-sales index falls back to
  building level for those pairs.
- Service charges are estimated per area unless a real per-building index is loaded.
- Yields use Ejari medians by area, type and room count — not the specific unit's actual rent.
- Mortgage parameters are as published and are re-verified by each ingest run.
