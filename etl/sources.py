"""Candidate open-data sources, and how to discover them.

Nothing here is asserted to work. The sandbox this project is developed in cannot reach any
government domain, so the URLs below are *candidates* that the probe job resolves from a GitHub
Actions runner, which has open egress. Whatever the probe finds is written to
``docs/results/source_probe.json`` and that file — not this one — is the record of what is real.

Discovery is preferred over hardcoded filenames: Dubai Pulse exposes a CKAN-style catalogue, so
asking the catalogue which resources exist survives the publisher renaming a file, which guessing
does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DUBAI_PULSE = "https://www.dubaipulse.gov.ae"
DLD = "https://dubailand.gov.ae"


@dataclass(frozen=True)
class Candidate:
    """One thing to try, and what a success would mean."""

    key: str
    url: str
    kind: str  # "catalogue" | "page" | "file"
    note: str
    method: str = "GET"
    expect: tuple[str, ...] = field(default=("200",))


# Catalogue endpoints first: if any of these answer, we can enumerate real resource URLs instead
# of guessing them.
CATALOGUE_CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        key="pulse_ckan_package_list",
        url=f"{DUBAI_PULSE}/api/3/action/package_list",
        kind="catalogue",
        note="CKAN package list — enumerates every dataset id on the portal",
    ),
    Candidate(
        key="pulse_ckan_search_dld",
        url=f"{DUBAI_PULSE}/api/3/action/package_search?q=dld&rows=100",
        kind="catalogue",
        note="CKAN search for DLD datasets, with resource download URLs",
    ),
    Candidate(
        key="pulse_ckan_transactions",
        url=f"{DUBAI_PULSE}/api/3/action/package_show?id=dld_transactions",
        kind="catalogue",
        note="CKAN metadata for the transactions dataset specifically",
    ),
    Candidate(
        key="pulse_opendata_api",
        url=f"{DUBAI_PULSE}/open-data/api",
        kind="page",
        note="Dubai Pulse open-data API landing page",
    ),
)

# Plain reachability checks, so a failure can be told apart from a wrong path.
PAGE_CANDIDATES: tuple[Candidate, ...] = (
    Candidate(key="pulse_root", url=f"{DUBAI_PULSE}/", kind="page", note="portal root"),
    Candidate(
        key="pulse_dataset_transactions",
        url=f"{DUBAI_PULSE}/dataset/dld_transactions",
        kind="page",
        note="transactions dataset page",
    ),
    Candidate(
        key="pulse_dataset_rent_contracts",
        url=f"{DUBAI_PULSE}/dataset/dld_rent_contracts",
        kind="page",
        note="rent contracts (Ejari) dataset page",
    ),
    Candidate(key="dld_root", url=f"{DLD}/", kind="page", note="DLD site root"),
    Candidate(
        key="dld_open_data",
        url=f"{DLD}/en/open-data/real-estate-data/",
        kind="page",
        note="DLD open-data downloads page",
    ),
    Candidate(
        key="dld_gateway",
        url="https://gateway.dubailand.gov.ae/",
        kind="page",
        note="DLD API gateway root",
    ),
)

ALL_CANDIDATES: tuple[Candidate, ...] = CATALOGUE_CANDIDATES + PAGE_CANDIDATES

# Datasets we want, matched case-insensitively against catalogue titles and ids.
WANTED_DATASETS: dict[str, tuple[str, ...]] = {
    "transactions": ("transaction",),
    "rent_contracts": ("rent_contract", "rent contract", "ejari"),
    "valuation": ("valuation",),
    "projects": ("project",),
    "buildings": ("building",),
    "units": ("unit",),
}

# Primary sources the memo and the mortgage config cite. Archived with a hash so a citation always
# points at a fixed document.
REFERENCE_DOCS: tuple[Candidate, ...] = (
    Candidate(
        key="dld_fees",
        url=f"{DLD}/en/services/",
        kind="page",
        note="DLD service and fee schedule — the 4% transfer fee used in net yield and DCF",
    ),
    Candidate(
        key="cbuae_regulations",
        url="https://www.centralbank.ae/en/our-operations/banking-supervision/regulations/",
        kind="page",
        note="UAE Central Bank regulations — LTV and debt-burden caps in config/mortgage.yaml",
    ),
    Candidate(
        key="rera_rent_index",
        url=f"{DLD}/en/eservices/rental-index/",
        kind="page",
        note="RERA rental index — backs the rent-increase calculator",
    ),
)
