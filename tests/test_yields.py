"""Yield tests.

The headline properties are that net is always below gross, and that every assumption actually
moves the number it claims to move. The second matters as much as the first: an assumption panel
whose sliders do nothing is worse than no panel, because it implies a rigour that is not there.
"""

from __future__ import annotations

import polars as pl
import pytest
import yaml

from finance.yields import (
    ASSUMPTIONS_PATH,
    Assumptions,
    acquisition_cost,
    build_table,
    gross_yield,
    net_yield,
)


@pytest.fixture(scope="module")
def a() -> Assumptions:
    return Assumptions.load()


class TestAssumptionsFile:
    def test_every_assumption_declares_a_value_a_unit_and_its_status(self):
        raw = yaml.safe_load(ASSUMPTIONS_PATH.read_text())
        for key, body in raw.items():
            if not isinstance(body, dict) or "value" not in body:
                continue
            assert "unit" in body, key
            assert body.get("status") in {"verified", "estimate", "unverified"}, key
            assert body.get("label"), key

    def test_a_field_claiming_a_primary_source_carries_the_url(self):
        raw = yaml.safe_load(ASSUMPTIONS_PATH.read_text())
        for key, body in raw.items():
            if isinstance(body, dict) and body.get("status") == "unverified":
                assert body.get("source_url"), f"{key} awaits a source, so it must name one"

    def test_nothing_is_marked_verified_without_a_date(self):
        """A verified flag with no date is a claim nobody can check."""
        raw = yaml.safe_load(ASSUMPTIONS_PATH.read_text())
        for key, body in raw.items():
            if isinstance(body, dict) and body.get("status") == "verified":
                assert body.get("verified_on"), key

    def test_the_panel_exposes_the_provenance_of_each_input(self, a):
        panel = {row["key"]: row for row in a.editable()}
        assert "vacancy" in panel
        assert panel["dld_transfer_fee"]["status"] == "unverified"
        assert panel["dld_transfer_fee"]["source_url"].startswith("https://")


class TestAcquisitionCost:
    def test_costs_more_than_the_asking_price(self, a):
        assert acquisition_cost(1_000_000, a) > 1_000_000

    def test_includes_the_transfer_fee_commission_and_registration(self, a):
        expected = 1_000_000 * (1 + a.dld_transfer_fee + a.agent_commission) + a.registration_fee
        assert acquisition_cost(1_000_000, a) == pytest.approx(expected)


class TestNetIsAlwaysBelowGross:
    @pytest.mark.parametrize("price", [400_000, 1_200_000, 9_000_000])
    @pytest.mark.parametrize("rent_pct", [0.04, 0.07, 0.12])
    def test_across_the_plausible_range(self, a, price, rent_pct):
        working = net_yield(price * rent_pct, price, 90.0, a)
        assert working["net_yield"] < working["gross_yield"]

    def test_even_with_every_cost_assumption_set_to_zero_net_cannot_exceed_gross(self, a):
        """Costs at zero is the best case; net should meet gross, never beat it."""
        free = a.replace(
            vacancy=0.0,
            service_charge_per_sqm=0.0,
            management_fee=0.0,
            maintenance=0.0,
            dld_transfer_fee=0.0,
            agent_commission=0.0,
            registration_fee=0.0,
        )
        working = net_yield(84_000, 1_200_000, 90.0, free)
        assert working["net_yield"] == pytest.approx(working["gross_yield"])

    def test_gross_matches_the_simple_definition(self):
        assert gross_yield(84_000, 1_200_000) == pytest.approx(0.07)

    def test_a_zero_price_yields_nothing_rather_than_infinity(self, a):
        assert gross_yield(84_000, 0) is None
        assert net_yield(84_000, 0, 90.0, a) is None


class TestEveryAssumptionMoves:
    """An assumption panel whose sliders do nothing implies a rigour that is not there."""

    BASE = (84_000.0, 1_200_000.0, 90.0)

    def _net(self, a: Assumptions) -> float:
        return net_yield(*self.BASE, a)["net_yield"]

    def test_more_vacancy_lowers_net_yield(self, a):
        assert self._net(a.replace(vacancy=0.20)) < self._net(a.replace(vacancy=0.02))

    def test_a_higher_service_charge_lowers_net_yield(self, a):
        assert self._net(a.replace(service_charge_per_sqm=400.0)) < self._net(
            a.replace(service_charge_per_sqm=50.0)
        )

    def test_a_higher_management_fee_lowers_net_yield(self, a):
        assert self._net(a.replace(management_fee=0.15)) < self._net(a.replace(management_fee=0.0))

    def test_more_maintenance_lowers_net_yield(self, a):
        assert self._net(a.replace(maintenance=0.03)) < self._net(a.replace(maintenance=0.0))

    def test_a_higher_transfer_fee_lowers_net_yield(self, a):
        assert self._net(a.replace(dld_transfer_fee=0.08)) < self._net(
            a.replace(dld_transfer_fee=0.02)
        )

    def test_a_longer_hold_spreads_purchase_costs_and_raises_net_yield(self, a):
        """One-off costs charged over ten years bite less each year than over two."""
        assert self._net(a.replace(amortisation_years=10)) > self._net(
            a.replace(amortisation_years=2)
        )

    def test_gross_yield_ignores_all_of_them(self, a):
        """Gross is rent over price and nothing else, which is exactly why it misleads."""
        expensive = a.replace(vacancy=0.3, service_charge_per_sqm=500.0, management_fee=0.2)
        assert net_yield(*self.BASE, expensive)["gross_yield"] == pytest.approx(
            net_yield(*self.BASE, a)["gross_yield"]
        )


class TestWorkingIsShown:
    def test_the_cost_lines_reconcile_to_the_net_income(self, a):
        w = net_yield(84_000, 1_200_000, 90.0, a)
        rebuilt = (
            w["effective_rent"]
            - w["service_charge"]
            - w["management"]
            - w["maintenance"]
            - w["amortised_purchase_costs"]
        )
        assert w["net_income"] == pytest.approx(rebuilt)

    def test_effective_rent_is_gross_rent_less_the_vacancy_cost(self, a):
        w = net_yield(84_000, 1_200_000, 90.0, a)
        assert w["effective_rent"] == pytest.approx(w["gross_rent"] - w["vacancy_cost"])


def _cell(
    area="marina",
    ptype="unit",
    rooms=1,
    n_sales=50,
    n_contracts=40,
    price=1_200_000.0,
    rent=84_000.0,
    sqm=90.0,
):
    prices = pl.DataFrame(
        [
            {
                "area_key": area,
                "property_type": ptype,
                "rooms": rooms,
                "n_sales": n_sales,
                "median_price": price,
                "median_sqm": sqm,
                "median_ppsqm": price / sqm,
                "price_sd": 1.0,
                "last_sale": None,
            }
        ]
    )
    rents = pl.DataFrame(
        [
            {
                "area_key": area,
                "property_type": ptype,
                "rooms": rooms,
                "n_contracts": n_contracts,
                "median_rent": rent,
                "median_rent_sqm": sqm,
                "rent_sd": 1.0,
                "last_contract": None,
            }
        ]
    )
    return prices, rents


class TestTable:
    def test_matches_sales_to_rents_on_the_same_cell(self, a):
        prices, rents = _cell()
        table = build_table(prices, rents, a)
        assert table.height == 1
        assert table["gross_yield"][0] == pytest.approx(0.07)

    def test_a_cell_with_rents_but_no_sales_produces_no_yield(self, a):
        prices, rents = _cell()
        rents = rents.with_columns(pl.lit("elsewhere").alias("area_key"))
        assert build_table(prices, rents, a).height == 0

    def test_the_binding_sample_is_the_thinner_side(self, a):
        """Two hundred sales and three tenancies is a three-observation yield."""
        prices, rents = _cell(n_sales=200, n_contracts=3)
        table = build_table(prices, rents, a)
        assert table["n"][0] == 3
        assert table["sufficient"][0] is False

    def test_a_cell_above_the_floor_is_published(self, a):
        prices, rents = _cell(n_sales=40, n_contracts=40)
        assert build_table(prices, rents, a)["sufficient"][0] is True
