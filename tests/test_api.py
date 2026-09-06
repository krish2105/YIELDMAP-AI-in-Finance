"""API tests.

The contract test is the important one: every number the API emits must arrive as a Kpi carrying
the SQL that produced it. That is the mechanism behind the project's traceability rule, and it is
worth asserting at the boundary rather than trusting each route to remember.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.kpi import sql_hash
from api.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


REQUIRED_KPI_FIELDS = {
    "id",
    "label",
    "value",
    "unit",
    "format",
    "n",
    "asof",
    "confidence",
    "method_id",
    "sql",
    "sql_hash",
    "sources",
}


def all_kpis(payload) -> list[dict]:
    """Every Kpi anywhere in a response."""
    found: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            if set(node) >= REQUIRED_KPI_FIELDS:
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(payload)
    return found


class TestMeta:
    def test_the_root_states_the_boundary(self, client):
        body = client.get("/").json()
        assert "not financial advice" in body["notice"]
        assert "cannot execute a transaction" in body["notice"]

    def test_health_reports_whether_the_database_is_present(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert "present" in body["database"]

    def test_security_headers_are_set_on_every_response(self, client):
        r = client.get("/health")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]

    def test_there_is_no_endpoint_that_transacts(self, client):
        """The boundary is architectural: no route buys, sells, lists or finances anything.

        Matched on whole path segments rather than substrings, so an analysis endpoint whose name
        contains a transaction word — /simulate/rent-vs-buy compares two options and moves no
        money — is not confused with one that acts.
        """
        transaction_verbs = {
            "buy",
            "sell",
            "order",
            "orders",
            "purchase",
            "execute",
            "checkout",
            "payment",
            "payments",
            "listing",
            "listings",
            "offer",
            "offers",
            "bid",
            "bids",
        }
        for path in client.get("/openapi.json").json()["paths"]:
            segments = {seg.lower() for seg in path.strip("/").split("/")}
            assert not (segments & transaction_verbs), path

    def test_only_read_and_simulate_methods_are_exposed(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for path, methods in paths.items():
            for method in methods:
                assert method.upper() in {"GET", "POST"}, f"{method} on {path}"


class TestKpiContract:
    ENDPOINTS = [
        "/market",
        "/areas/marsa dubai",
        "/buildings/Marsa Tower 1",
        "/compare?areas=marsa dubai",
    ]

    def test_every_number_arrives_as_a_traceable_kpi(self, client):
        seen = 0
        for path in self.ENDPOINTS:
            body = client.get(path).json()
            for kpi in all_kpis(body):
                seen += 1
                assert kpi["sql"].strip(), f"{kpi['id']} carries no SQL"
                assert kpi["sql_hash"] == sql_hash(kpi["sql"])
                assert kpi["method_id"]
                assert kpi["n"] >= 0
        assert seen > 0, "the contract test found no KPIs to check"

    def test_a_thin_cell_is_blanked_rather_than_shown(self, client):
        for kpi in all_kpis(client.get("/market").json()):
            if kpi["confidence"] == "insufficient":
                assert kpi["value"] is None

    def test_every_kpi_declares_its_provenance(self, client):
        for kpi in all_kpis(client.get("/market").json()):
            assert kpi["provenance"] in {"REAL", "SYNTHETIC"}

    def test_a_kpi_names_at_least_one_source(self, client):
        for kpi in all_kpis(client.get("/areas/marsa dubai").json()):
            assert kpi["sources"], kpi["id"]


class TestMarketRoutes:
    def test_the_market_page_returns_headline_kpis(self, client):
        body = client.get("/market").json()
        ids = {k["id"] for k in body["kpis"]}
        assert {"market.transactions", "market.ppsqm", "market.offplan"} <= ids

    def test_areas_reports_how_many_have_no_location(self, client):
        body = client.get("/areas").json()
        assert body["areas"]
        assert "without_location" in body

    def test_an_unknown_area_is_a_clear_404(self, client):
        r = client.get("/areas/nowhere-at-all")
        assert r.status_code == 404
        assert "no transactions" in r.json()["detail"]

    def test_an_area_carries_its_series_risk_and_forecast(self, client):
        body = client.get("/areas/marsa dubai").json()
        assert body["series"]["points"]
        assert body["risk"] is not None
        assert body["forecast"] is not None

    def test_compare_needs_at_least_one_area(self, client):
        assert client.get("/compare").status_code == 400

    def test_compare_refuses_an_unreadable_number_of_areas(self, client):
        r = client.get("/compare", params={"areas": [f"a{i}" for i in range(7)]})
        assert r.status_code == 400
        assert "unreadable" in r.json()["detail"]

    def test_compare_reports_an_area_it_could_not_find_rather_than_failing(self, client):
        body = client.get("/compare", params={"areas": ["marsa dubai", "nowhere"]}).json()
        found = {a["area_key"]: a["found"] for a in body["areas"]}
        assert found["marsa dubai"] is True
        assert found["nowhere"] is False

    def test_the_screener_filters_and_reports_the_total(self, client):
        body = client.get("/screener", params={"property_type": "unit", "limit": 10}).json()
        assert len(body["rows"]) <= 10
        assert body["total_matching"] >= len(body["rows"])
        assert all(r["property_type"] == "unit" for r in body["rows"])

    def test_model_outputs_are_served(self, client):
        for path in ["/index", "/yield", "/forecast", "/risk", "/developers", "/hedonic"]:
            assert client.get(path).status_code == 200, path

    def test_anomalies_name_the_rule_that_fired(self, client):
        body = client.get("/anomalies", params={"limit": 5}).json()
        assert body["by_rule"]
        for example in body["examples"]:
            assert example["reasons"]

    def test_freshness_warns_when_the_data_is_generated(self, client):
        body = client.get("/data/freshness").json()
        assert body["tables"]
        if body["provenance"] == "SYNTHETIC":
            assert "not the Dubai registry" in body["warning"]


class TestSimulate:
    def test_assumptions_are_exposed_with_their_status(self, client):
        body = client.get("/simulate/assumptions").json()
        assert body["yield"] and body["mortgage"]
        assert "ltv_caps" in body["unverified"]

    def test_affordability_names_the_binding_constraint(self, client):
        body = client.post(
            "/simulate/affordability", json={"price": 1_500_000, "monthly_income": 60_000}
        ).json()
        assert body["max_loan"] == pytest.approx(1_200_000)
        assert body["binding_constraint"] == "loan-to-value cap"
        assert "unverified" in body["caveat"]

    def test_a_projection_returns_flows_and_a_disclaimer(self, client):
        body = client.post(
            "/simulate/projection",
            json={"price": 1_500_000, "annual_rent": 105_000, "sqm": 95, "years": 5},
        ).json()
        assert len(body["flows"]) == 6
        assert "not advice" in body["disclaimer"].lower()
        assert "cannot execute" in body["notice"]

    def test_a_loan_larger_than_the_price_is_rejected(self, client):
        r = client.post(
            "/simulate/projection",
            json={"price": 1_000_000, "annual_rent": 70_000, "sqm": 90, "loan_amount": 2_000_000},
        )
        assert r.status_code == 422

    def test_assumption_overrides_change_the_answer(self, client):
        base = {"price": 1_500_000, "annual_rent": 105_000, "sqm": 95, "years": 5}
        low = client.post("/simulate/projection", json={**base, "vacancy": 0.0}).json()
        high = client.post("/simulate/projection", json={**base, "vacancy": 0.30}).json()
        assert high["yield"]["net_yield"] < low["yield"]["net_yield"]

    def test_absurd_inputs_are_refused_by_the_schema(self, client):
        assert (
            client.post(
                "/simulate/projection", json={"price": -5, "annual_rent": 1, "sqm": 1}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/simulate/affordability", json={"price": 1e12, "monthly_income": 1}
            ).status_code
            == 422
        )

    def test_rent_versus_buy_returns_a_verdict(self, client):
        body = client.post(
            "/simulate/rent-vs-buy",
            json={"price": 1_500_000, "annual_rent": 105_000, "sqm": 95, "years": 15},
        ).json()
        assert "verdict" in body
        assert len(body["years"]) == 15

    def test_a_portfolio_is_analysed_for_concentration(self, client):
        body = client.post(
            "/simulate/portfolio",
            json={
                "holdings": [
                    {
                        "area_key": "marsa dubai",
                        "value": 2_000_000,
                        "annual_rent": 120_000,
                        "sqm": 100,
                    },
                    {
                        "area_key": "business bay",
                        "value": 1_000_000,
                        "annual_rent": 70_000,
                        "sqm": 80,
                    },
                ]
            },
        ).json()
        assert body["holdings"] == 2
        assert body["concentration"]["by_area"]["groups"] == 2
        assert body["blended_yield"]["net"] < body["blended_yield"]["gross"]

    def test_an_empty_portfolio_is_refused(self, client):
        assert client.post("/simulate/portfolio", json={"holdings": []}).status_code == 422
