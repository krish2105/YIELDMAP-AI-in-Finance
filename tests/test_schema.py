"""Column-mapping tests.

The publisher's column names are theirs to change. What matters is that the mapping tells the
difference between a column that is absent and a column that is merely named differently.
"""

from __future__ import annotations

from etl.schema import (
    RENT_ALIASES,
    TRANSACTION_ALIASES,
    map_columns,
    normalise_key,
)

DLD_TRANSACTION_COLUMNS = [
    "transaction_id",
    "instance_date",
    "trans_group_en",
    "procedure_name_en",
    "reg_type_en",
    "area_name_en",
    "area_name_ar",
    "building_name_en",
    "project_name_en",
    "property_type_en",
    "property_sub_type_en",
    "rooms_en",
    "has_parking",
    "procedure_area",
    "actual_worth",
    "meter_sale_price",
    "some_column_we_do_not_model",
]


class TestNormalisation:
    def test_ignores_case_separators_and_punctuation(self):
        assert normalise_key("Actual Worth") == normalise_key("actual_worth")
        assert normalise_key("ACTUAL-WORTH") == normalise_key("actualworth")


class TestTransactionMapping:
    def test_resolves_the_publisher_columns(self):
        m = map_columns(DLD_TRANSACTION_COLUMNS, TRANSACTION_ALIASES)
        assert m.resolved["price_aed"] == "actual_worth"
        assert m.resolved["area_sqm"] == "procedure_area"
        assert m.resolved["ts"] == "instance_date"
        assert m.resolved["rooms_raw"] == "rooms_en"

    def test_reports_columns_this_project_does_not_model(self):
        m = map_columns(DLD_TRANSACTION_COLUMNS, TRANSACTION_ALIASES)
        assert "some_column_we_do_not_model" in m.unmapped

    def test_a_file_with_the_expected_columns_is_usable(self):
        assert map_columns(DLD_TRANSACTION_COLUMNS, TRANSACTION_ALIASES).usable is True

    def test_a_file_missing_a_required_column_is_not_usable(self):
        cols = [c for c in DLD_TRANSACTION_COLUMNS if c != "actual_worth"]
        m = map_columns(cols, TRANSACTION_ALIASES)
        assert m.usable is False
        assert "price_aed" in m.missing_required

    def test_a_missing_optional_column_does_not_make_the_file_unusable(self):
        cols = [c for c in DLD_TRANSACTION_COLUMNS if c != "has_parking"]
        m = map_columns(cols, TRANSACTION_ALIASES)
        assert m.usable is True
        assert "has_parking" in m.missing

    def test_survives_a_renamed_column_via_an_alias(self):
        cols = ["date", "area", "amount"]
        m = map_columns(cols, TRANSACTION_ALIASES)
        assert m.resolved["ts"] == "date"
        assert m.resolved["price_aed"] == "amount"
        assert m.usable is True

    def test_alias_priority_is_deterministic_when_a_file_carries_both(self):
        m = map_columns(["meter_sale_price", "price_per_sqm"], TRANSACTION_ALIASES)
        assert m.resolved["price_per_sqm_raw"] == "meter_sale_price"

    def test_one_column_is_never_claimed_by_two_canonical_fields(self):
        m = map_columns(DLD_TRANSACTION_COLUMNS, TRANSACTION_ALIASES)
        actual = list(m.resolved.values())
        assert len(actual) == len(set(actual))

    def test_an_empty_file_reports_everything_missing_rather_than_raising(self):
        m = map_columns([], TRANSACTION_ALIASES)
        assert m.resolved == {}
        assert m.usable is False


class TestRentMapping:
    def test_resolves_ejari_columns(self):
        cols = [
            "contract_id",
            "contract_start_date",
            "contract_end_date",
            "area_name_en",
            "annual_amount",
            "ejari_property_type_en",
        ]
        m = map_columns(cols, RENT_ALIASES)
        assert m.resolved["annual_rent_aed"] == "annual_amount"
        assert m.resolved["start"] == "contract_start_date"
        assert m.usable is True

    def test_rent_files_are_judged_against_rent_requirements_not_transaction_ones(self):
        """A rent file has no price_aed, and demanding one would reject every valid file."""
        m = map_columns(["contract_id", "area_name_en", "annual_amount"], RENT_ALIASES)
        assert m.usable is True
