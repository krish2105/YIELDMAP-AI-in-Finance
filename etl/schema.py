"""The canonical shape YIELDMAP works in, and how publisher columns map onto it.

The publisher's column names are theirs to change, and the transactions file carries dozens of
columns this project does not model. Keeping the mapping in one place means a rename upstream is a
one-line edit here rather than a hunt through the pipeline, and it lets the cleaner tell the
difference between "this column is missing" and "this column has a different name".
"""

from __future__ import annotations

from dataclasses import dataclass

# Canonical name -> the publisher column names that have been seen to carry it, in priority order.
# Lower-cased and stripped of non-alphanumerics before matching, so "Actual Worth", "actual_worth"
# and "ACTUAL-WORTH" all resolve to the same thing.
TRANSACTION_ALIASES: dict[str, tuple[str, ...]] = {
    "transaction_id": ("transaction_id", "trans_id", "id", "transactionnumber", "procedure_id"),
    "ts": ("instance_date", "transaction_date", "date", "instancedate", "trans_date"),
    "procedure": ("procedure_name_en", "procedure_en", "procedure"),
    "trans_group": ("trans_group_en", "transaction_group_en", "group_en"),
    "reg_type": ("reg_type_en", "registration_type_en", "reg_type"),
    "area_name": ("area_name_en", "area_en", "area", "master_area_en"),
    "area_name_ar": ("area_name_ar", "area_ar"),
    "building_name": ("building_name_en", "building_en", "building"),
    "project_name": ("project_name_en", "project_en", "project"),
    "master_project": ("master_project_en", "master_project"),
    "property_type": ("property_type_en", "prop_type_en", "property_type"),
    "property_sub_type": ("property_sub_type_en", "prop_sb_type_en", "property_sub_type"),
    "property_usage": ("property_usage_en", "usage_en", "property_usage"),
    "rooms_raw": ("rooms_en", "rooms", "no_of_rooms"),
    "area_sqm": ("procedure_area", "actual_area", "area_sqm", "size_sqm"),
    "price_aed": ("actual_worth", "amount", "trans_value", "price", "worth"),
    "price_per_sqm_raw": ("meter_sale_price", "price_per_sqm", "meter_price"),
    "has_parking": ("has_parking", "parking"),
    "nearest_metro": ("nearest_metro_en", "nearest_metro"),
    "nearest_landmark": ("nearest_landmark_en", "nearest_landmark"),
    "nearest_mall": ("nearest_mall_en", "nearest_mall"),
}

RENT_ALIASES: dict[str, tuple[str, ...]] = {
    "contract_id": ("contract_id", "ejari_contract_number", "id"),
    "start": ("contract_start_date", "start_date", "registration_date"),
    "end": ("contract_end_date", "end_date"),
    "area_name": ("area_name_en", "area_en", "area"),
    "building_name": ("building_name_en", "property_name", "building"),
    "project_name": ("project_name_en", "project_en"),
    "property_type": ("ejari_property_type_en", "property_type_en", "property_type"),
    "property_sub_type": ("ejari_property_sub_type_en", "property_sub_type_en"),
    "rooms_raw": ("ejari_bus_property_type_en", "rooms_en", "rooms", "no_of_rooms"),
    "area_sqm": ("actual_area", "property_size_sqm", "area_sqm"),
    "annual_rent_aed": ("annual_amount", "contract_amount", "annual_rent", "amount"),
    "contract_type": ("version_en", "contract_type_en", "contract_type"),
    "usage": ("ejari_property_usage_en", "property_usage_en", "usage_en"),
}

# Columns without which a row cannot be used for anything this project does.
REQUIRED_TRANSACTION_FIELDS: tuple[str, ...] = ("ts", "area_name", "price_aed")
REQUIRED_RENT_FIELDS: tuple[str, ...] = ("area_name", "annual_rent_aed")


def normalise_key(name: str) -> str:
    """Reduce a column name to its comparable form."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


@dataclass(frozen=True)
class ColumnMapping:
    """The outcome of matching a file's columns against the canonical schema."""

    resolved: dict[str, str]  # canonical name -> the actual column in this file
    missing: tuple[str, ...]  # canonical names with no column in this file
    unmapped: tuple[str, ...]  # columns in the file this project does not model

    @property
    def usable(self) -> bool:
        return not self.missing_required

    @property
    def missing_required(self) -> tuple[str, ...]:
        return tuple(f for f in self.missing if f in _required_for(self.resolved))


def _required_for(resolved: dict[str, str]) -> tuple[str, ...]:
    # Rent contracts have no price_aed; transactions have no annual_rent_aed.
    if "annual_rent_aed" in resolved or "contract_id" in resolved:
        return REQUIRED_RENT_FIELDS
    return REQUIRED_TRANSACTION_FIELDS


def map_columns(columns: list[str], aliases: dict[str, tuple[str, ...]]) -> ColumnMapping:
    """Match a file's actual columns onto the canonical schema.

    Matching is by normalised name and respects alias priority, so when a file carries both
    ``meter_sale_price`` and ``price_per_sqm`` the one listed first wins deterministically.
    """
    by_norm: dict[str, str] = {}
    for col in columns:
        by_norm.setdefault(normalise_key(col), col)

    resolved: dict[str, str] = {}
    taken: set[str] = set()
    for canonical, candidates in aliases.items():
        for cand in candidates:
            actual = by_norm.get(normalise_key(cand))
            if actual and actual not in taken:
                resolved[canonical] = actual
                taken.add(actual)
                break

    missing = tuple(k for k in aliases if k not in resolved)
    unmapped = tuple(c for c in columns if c not in taken)
    return ColumnMapping(resolved=resolved, missing=missing, unmapped=unmapped)
