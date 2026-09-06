"""Canonicalisation tests.

The governing rule is that an unreadable value becomes None rather than a guess. A null shrinks a
sample and lowers a confidence badge, which is honest; a guess becomes a number someone acts on.
"""

from __future__ import annotations

import pytest

from etl.canon import (
    canon_area_key,
    canon_area_name,
    canon_area_sqm,
    canon_is_offplan,
    canon_price,
    canon_property_type,
    canon_rooms,
    price_per_sqm,
    rooms_label,
)


class TestRooms:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Studio", 0),
            ("STUDIO", 0),
            (" studio ", 0),
            ("1 B/R", 1),
            ("3 B/R", 3),
            ("10 B/R", 10),
            ("2 BR", 2),
            ("4 Bedroom", 4),
            ("5", 5),
            (3, 3),
            (0, 0),
        ],
    )
    def test_reads_the_bedroom_count(self, raw, expected):
        assert canon_rooms(raw) == expected

    def test_a_studio_is_zero_bedrooms_not_missing(self):
        """Treating a studio as null would drop the whole studio segment from every yield table."""
        assert canon_rooms("Studio") == 0
        assert canon_rooms("Studio") is not None

    @pytest.mark.parametrize("raw", ["PENTHOUSE", "Office", "Shop", "Land", "N/A", "", "  "])
    def test_returns_nothing_for_values_that_are_not_bedroom_counts(self, raw):
        assert canon_rooms(raw) is None

    @pytest.mark.parametrize("raw", [None, "banana", -1, 99, "99 B/R"])
    def test_returns_nothing_rather_than_guessing(self, raw):
        assert canon_rooms(raw) is None

    def test_does_not_read_a_boolean_as_a_room_count(self):
        assert canon_rooms(True) is None

    @pytest.mark.parametrize(
        ("rooms", "label"), [(None, "unknown"), (0, "studio"), (1, "1br"), (4, "4br")]
    )
    def test_labels_are_stable_grouping_keys(self, rooms, label):
        assert rooms_label(rooms) == label


class TestPropertyType:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Unit", "unit"),
            ("Flat", "unit"),
            ("apartment", "unit"),
            ("Villa", "villa"),
            ("Villa/House", "villa"),
            ("Land", "land"),
            ("Building", "building"),
            ("Shop", "retail"),
            ("Warehouse", "industrial"),
        ],
    )
    def test_collapses_the_publisher_vocabulary(self, raw, expected):
        assert canon_property_type(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "Spaceship"])
    def test_returns_nothing_for_an_unknown_type(self, raw):
        assert canon_property_type(raw) is None


class TestOffPlan:
    @pytest.mark.parametrize(
        "reg", ["Off-Plan Properties", "off plan", "OFFPLAN", "Sell Pre-Registration"]
    )
    def test_recognises_off_plan(self, reg):
        assert canon_is_offplan(reg) is True

    @pytest.mark.parametrize("reg", ["Existing Properties", "Ready", "resale"])
    def test_recognises_existing(self, reg):
        assert canon_is_offplan(reg) is False

    def test_falls_back_to_the_procedure_when_registration_type_is_blank(self):
        assert canon_is_offplan("", "Sell Pre-Registration") is True
        assert canon_is_offplan(None, "Sell") is None

    def test_registration_type_wins_over_the_procedure(self):
        assert canon_is_offplan("Existing Properties", "Sell Pre-Registration") is False

    def test_returns_nothing_when_neither_field_says(self):
        assert canon_is_offplan(None, None) is None
        assert canon_is_offplan("Grant", "Transfer") is None


class TestAreaNames:
    def test_the_same_community_spelled_three_ways_gets_one_key(self):
        variants = ["Al Barsha South Fourth", "AL BARSHA SOUTH FOURTH", "Al Barsha South  Fourth"]
        assert len({canon_area_key(v) for v in variants}) == 1

    def test_strips_punctuation_and_accents(self):
        assert canon_area_key("Al Barsha, South-Fourth") == canon_area_key("Al Barsha South Fourth")

    def test_an_apostrophe_does_not_split_a_transliterated_name(self):
        """The publisher writes both "Za'abeel" and "Zaabeel" for the same place."""
        assert canon_area_key("Za'abeel") == "zaabeel"
        assert canon_area_key("Za\u2019abeel") == "zaabeel"
        assert canon_area_key("Al Warqa'a First") == canon_area_key("Al Warqaa First")

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_returns_nothing_for_an_empty_name(self, raw):
        assert canon_area_key(raw) is None
        assert canon_area_name(raw) is None

    def test_display_name_keeps_casing_but_collapses_spacing(self):
        assert canon_area_name("  Dubai   Marina ") == "Dubai Marina"


class TestMoney:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(1_250_000, 1_250_000.0), ("1250000", 1_250_000.0), ("1,250,000", 1_250_000.0)],
    )
    def test_reads_a_price(self, raw, expected):
        assert canon_price(raw) == expected

    @pytest.mark.parametrize("raw", [0, 1, -5, None, "", "n/a", 1e12])
    def test_rejects_values_that_cannot_be_a_price(self, raw):
        assert canon_price(raw) is None

    @pytest.mark.parametrize("raw", [float("nan"), float("inf"), float("-inf")])
    def test_rejects_non_finite_numbers(self, raw):
        assert canon_price(raw) is None
        assert canon_area_sqm(raw) is None

    @pytest.mark.parametrize(("raw", "expected"), [(85.5, 85.5), ("120", 120.0)])
    def test_reads_a_floor_area(self, raw, expected):
        assert canon_area_sqm(raw) == expected

    @pytest.mark.parametrize("raw", [0, 1.0, -10, 2_000_000])
    def test_rejects_an_impossible_floor_area(self, raw):
        assert canon_area_sqm(raw) is None

    def test_price_per_sqm_is_derived_from_what_was_stored(self):
        assert price_per_sqm(1_200_000.0, 100.0) == 12_000.0

    @pytest.mark.parametrize(
        ("price", "area"), [(None, 100.0), (1_000_000.0, None), (1_000_000.0, 0.0)]
    )
    def test_price_per_sqm_is_none_when_either_side_is_missing(self, price, area):
        assert price_per_sqm(price, area) is None
