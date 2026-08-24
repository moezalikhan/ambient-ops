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


def test_unimplemented_endpoints_are_honest():
    """Stubs must 501, not return fabricated data."""
    assert client.post("/api/analyze", json={"route_id": "route_a"}).status_code == 501
    assert client.get("/api/analyze/abc").status_code == 501
    assert client.get("/api/agent-trace/abc").status_code == 501


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
