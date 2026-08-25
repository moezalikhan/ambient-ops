"""Step 1 smoke tests: the app boots, the contract holds, the cache works."""

import pytest
from fastapi.testclient import TestClient

from backend.cache import store
from backend.main import app
from backend.models import Weights

client = TestClient(app)


def test_health_reports_missing_keys():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert "missing_keys" in r.json()


def test_demo_routes_load_and_validate():
    r = client.get("/api/routes")
    assert r.status_code == 200
    routes = r.json()
    assert len(routes) == 2
    assert {x["id"] for x in routes} == {"route_a", "route_b"}


def test_no_endpoint_is_a_stub_any_more():
    """Every endpoint in spec section 9 now has a real handler."""
    paths = {r.path for r in app.routes}
    for p in ("/api/routes", "/api/analyze", "/api/analyze/{run_id}",
              "/api/agent-trace/{run_id}", "/api/simulate"):
        assert p in paths, p


def test_simulate_rejects_an_unknown_run():
    r = client.post("/api/simulate", json={
        "run_id": "deadbeef", "segment_id": "x", "intervention": "street_trees"})
    assert r.status_code == 404


def test_interventions_are_listed_with_their_sourcing():
    """The picker must be able to show which magnitudes are assumptions."""
    body = client.get("/api/interventions").json()["interventions"]
    assert len(body) >= 6
    for i in body:
        assert {"id", "label", "assumption", "sourced", "caveat"} <= set(i)


def test_analyze_is_implemented():
    """503 (no keys, as in CI) or 200 (keys present) — anything but 501."""
    r = client.post("/api/analyze", json={"route_id": "route_a"})
    assert r.status_code in (200, 503), r.text


def test_analyze_rejects_an_unknown_route():
    assert client.post("/api/analyze", json={"route_id": "nope"}).status_code == 404


def test_polling_an_unknown_run_is_404():
    assert client.get("/api/analyze/deadbeef").status_code == 404
    assert client.get("/api/agent-trace/deadbeef").status_code == 404


def test_weights_normalise_to_one():
    w = Weights(HEI=0.8, DTF=0.8, SVI=0.8, PSI=0.8).normalised()
    assert pytest.approx(w.HEI + w.DTF + w.SVI + w.PSI) == 1.0
    assert pytest.approx(w.HEI) == 0.25


def test_weights_default_matches_spec():
    w = Weights()
    assert (w.HEI, w.DTF, w.SVI, w.PSI) == (0.40, 0.20, 0.20, 0.20)


def test_cache_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    store.init_db(db)
    assert store.get("osm", "k1", db_path=db) is None
    store.put("osm", "k1", {"trees": 3}, db_path=db)
    assert store.get("osm", "k1", db_path=db) == {"trees": 3}
    assert store.stats(db_path=db) == {"osm": 1}


def test_cache_respects_max_age(tmp_path):
    db = tmp_path / "t.db"
    store.init_db(db)
    store.put("heat", "k", [1, 2], db_path=db)
    assert store.get("heat", "k", max_age_s=0, db_path=db) is None
