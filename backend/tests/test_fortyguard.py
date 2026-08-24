"""FortyGuard client tests. All network calls are mocked — these must pass with
no API key and no connectivity, so CI stays green.
"""

from datetime import date

import httpx
import pytest

from backend import config
from backend.cache import store
from backend.services import fortyguard as fg
from backend.services.geo import buffered_bbox_polygon, haversine_m, polygon_area_km2

ROUTE = [(54.3773, 24.4539), (54.3812, 24.4571)]
ACTIVITY_ID = "f52d2453-6a59-4b31-afa3-8fe3bb1ac5df"

# `fg.httpx` is the httpx module itself, so patching fg.httpx.Client patches it
# globally. Hold the real class here or the stub recurses into itself.
_RealClient = httpx.Client


def _patch_client(monkeypatch, transport):
    monkeypatch.setattr(
        fg.httpx, "Client", lambda **kw: _RealClient(transport=transport)
    )
    monkeypatch.setattr(fg.time, "sleep", lambda s: None)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Fresh cache DB and a fake key for every test."""
    monkeypatch.setattr(config, "FORTYGUARD_API_KEY", "test-key-123")
    monkeypatch.setattr(store, "CACHE_DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "CACHE_DB_PATH", tmp_path / "t.db")
    store._initialised.clear()


def _tile(lon, lat, value):
    d = 0.0005
    return {
        "type": "Feature",
        "properties": {"value": value},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [lon - d, lat - d], [lon + d, lat - d],
                [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d],
            ]],
        },
    }


def _mock_api(submit_status=200, poll_sequence=("Processing", "Completed"), tiles=None):
    """MockTransport standing in for the FortyGuard API."""
    calls = {"submit": 0, "status": 0}
    seq = list(poll_sequence)
    features = tiles if tiles is not None else [
        _tile(54.3773, 24.4539, 4.0), _tile(54.3812, 24.4571, 9.0)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["api-key"] == "test-key-123"
        if request.url.path.endswith("/heatmap"):
            calls["submit"] += 1
            if submit_status != 200:
                return httpx.Response(submit_status, text="denied")
            return httpx.Response(200, json={
                "error": False, "status_code": 200,
                "message": "Heatmap Submitted Successfully",
                "data": {"activity_id": ACTIVITY_ID},
            })
        calls["status"] += 1
        status = seq[min(calls["status"] - 1, len(seq) - 1)]
        data = {"activity_id": ACTIVITY_ID, "status": status}
        if status == "Completed":
            data["result"] = {
                "map_data": {"type": "FeatureCollection", "features": features},
                "stats_data": {"units": "hour"},
            }
        return httpx.Response(200, json={
            "error": False, "status_code": 200, "message": status, "data": data,
        })

    return httpx.MockTransport(handler), calls


@pytest.fixture
def mock_api(monkeypatch):
    transport, calls = _mock_api()
    _patch_client(monkeypatch, transport)
    return calls


# --- payload construction -------------------------------------------------

def test_exceedance_payload_carries_threshold_and_direction():
    p = fg.build_payload(buffered_bbox_polygon(ROUTE, 120), analytic_type="exceedance")
    assert p["analytic_type"] == "exceedance"
    assert p["threshold"] == config.HEAT_THRESHOLD_C
    assert p["direction"] == "above"


def test_snapshot_payload_omits_threshold():
    """tcm and time_of_measure ignore threshold/direction; sending them anyway
    invites a confident wrong answer."""
    for layer in ("tcm", "time_of_measure"):
        p = fg.build_payload(buffered_bbox_polygon(ROUTE, 120), analytic_type=layer)
        assert "threshold" not in p
        assert "direction" not in p


def test_rejects_unknown_layer_and_granularity():
    poly = buffered_bbox_polygon(ROUTE, 120)
    with pytest.raises(fg.FortyGuardError, match="unknown analytic_type"):
        fg.build_payload(poly, analytic_type="heat_index")
    with pytest.raises(fg.FortyGuardError, match="granularity"):
        fg.build_payload(poly, granularity=25)


def test_rejects_aoi_over_plan_ceiling():
    """Refuse locally rather than burning a submission on a 402."""
    huge = buffered_bbox_polygon([(54.0, 24.0), (55.0, 25.0)], 120)
    with pytest.raises(fg.FortyGuardError, match="plan ceiling"):
        fg.build_payload(huge)


def test_default_window_accumulates_over_weeks_not_one_day():
    """A single-day window collapses HEI to noise — measured, not assumed.
    filter_type 4 is a range of days and carries no times."""
    w = fg.default_date_window()
    assert w["filter_type"] == 4
    assert "start_time" not in w and "end_time" not in w
    start = date.fromisoformat(w["start_date"])
    end = date.fromisoformat(w["end_date"])
    assert (end - start).days == config.HEAT_WINDOW_DAYS
    assert (end - start).days <= 31, "API rejects windows longer than one month"


def test_window_ends_in_the_past():
    """The API accepts at most 12 hours ahead; a partial day skews the count."""
    assert date.fromisoformat(fg.default_date_window()["end_date"]) < date.today()


def test_threshold_default_discriminates_in_fresno():
    """30 °C is the API default and is exceeded by every tile every daylight
    hour in the Central Valley, flattening HEI."""
    assert config.HEAT_THRESHOLD_C >= 35


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(config, "FORTYGUARD_API_KEY", "")
    with pytest.raises(fg.FortyGuardError, match="FORTYGUARD_API_KEY is not set"):
        fg._headers()


# --- submit / poll --------------------------------------------------------

def test_submit_and_poll_until_complete(mock_api):
    out = fg.get_heat_grid_for_route(ROUTE, analytic_type="exceedance")
    assert out["layer"] == "exceedance"
    assert out["units"] == "hour"
    assert out["tile_count"] == 2
    assert out["cache_hit"] is False
    assert [g["value"] for g in out["grid"]] == [4.0, 9.0]
    # Polled through "Processing" before "Completed".
    assert mock_api["status"] == 2


def test_grid_centroids_land_near_tile_centres(mock_api):
    out = fg.get_heat_grid_for_route(ROUTE)
    first = out["grid"][0]
    assert haversine_m((first["lon"], first["lat"]), (54.3773, 24.4539)) < 5


def test_second_call_is_served_from_cache(mock_api):
    fg.get_heat_grid_for_route(ROUTE)
    assert mock_api["submit"] == 1
    again = fg.get_heat_grid_for_route(ROUTE)
    assert again["cache_hit"] is True
    assert mock_api["submit"] == 1  # no second network call


def test_use_cache_false_forces_a_new_submission(mock_api):
    fg.get_heat_grid_for_route(ROUTE)
    fg.get_heat_grid_for_route(ROUTE, use_cache=False)
    assert mock_api["submit"] == 2


def test_rejected_key_reports_the_actual_cause(monkeypatch):
    transport, _ = _mock_api(submit_status=401)
    _patch_client(monkeypatch, transport)
    with pytest.raises(fg.FortyGuardError, match="API key rejected"):
        fg.get_heat_grid_for_route(ROUTE)


def test_failed_activity_raises(monkeypatch):
    transport, _ = _mock_api(poll_sequence=("Failed",))
    _patch_client(monkeypatch, transport)
    with pytest.raises(fg.FortyGuardError, match="ended as 'failed'"):
        fg.get_heat_grid_for_route(ROUTE)


def test_poll_timeout_raises(monkeypatch):
    transport, _ = _mock_api(poll_sequence=("Processing",))
    _patch_client(monkeypatch, transport)
    with pytest.raises(fg.FortyGuardError, match="still 'processing'"):
        fg.get_heat_grid_for_route(ROUTE, timeout_s=0)


# --- tile value extraction ------------------------------------------------
# Regression tests for a real bug: tcm tiles carry `tile_id` before any
# temperature field, and a "first numeric property" fallback scored the whole
# grid on tile indices while reporting a full, healthy-looking tile count.

def _tcm_tile(lon, lat, tile_id, avg, tmin, tmax):
    d = 0.0005
    return {
        "type": "Feature",
        "properties": {
            "tile_id": tile_id,
            "average_temperature": avg,
            "min_temperature": tmin,
            "max_temperature": tmax,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [lon - d, lat - d], [lon + d, lat - d],
                [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d],
            ]],
        },
    }


def test_tcm_reads_temperature_never_tile_id():
    map_data = {"type": "FeatureCollection", "features": [
        _tcm_tile(-119.78, 36.73, 0, 33.06, 21.05, 39.60),
        _tcm_tile(-119.79, 36.74, 1, 34.10, 22.00, 41.20),
    ]}
    grid = fg._flatten_grid(map_data, "tcm")
    assert [g["value"] for g in grid] == [33.06, 34.10]
    # tile_id 0 and 1 must never surface as the measurement.
    assert all(g["value"] > 15 for g in grid)


def test_tcm_keeps_temporal_range_for_threshold_selection():
    """min/max per tile are what reveal whether a threshold can discriminate."""
    map_data = {"type": "FeatureCollection", "features": [
        _tcm_tile(-119.78, 36.73, 0, 33.06, 21.05, 39.60)
    ]}
    tile = fg._flatten_grid(map_data, "tcm")[0]
    assert tile["min_temperature"] == 21.05
    assert tile["max_temperature"] == 39.60


def test_exceedance_reads_value_key():
    map_data = {"type": "FeatureCollection", "features": [_tile(54.0, 24.0, 7.0)]}
    assert fg._flatten_grid(map_data, "exceedance")[0]["value"] == 7.0


def test_unmapped_layer_raises_rather_than_guessing():
    """No silent fallback. An unknown layer is a code change, not a runtime guess."""
    map_data = {"type": "FeatureCollection", "features": [_tile(54.0, 24.0, 1.0)]}
    with pytest.raises(fg.FortyGuardError, match="no value-key mapping"):
        fg._flatten_grid(map_data, "some_new_layer")


def test_zero_tiles_blames_coverage_not_the_parser(monkeypatch):
    transport, _ = _mock_api(tiles=[])
    _patch_client(monkeypatch, transport)
    with pytest.raises(fg.FortyGuardError, match="outside coverage"):
        fg.get_heat_grid_for_route(ROUTE)


def test_features_without_values_blames_the_parser(monkeypatch):
    """The opposite failure must point at the code, not at coverage."""
    junk = [{"type": "Feature", "properties": {"tile_id": 0},
             "geometry": {"type": "Polygon", "coordinates": [[
                 [54.0, 24.0], [54.1, 24.0], [54.1, 24.1], [54.0, 24.1], [54.0, 24.0]]]}}]
    transport, _ = _mock_api(tiles=junk)
    _patch_client(monkeypatch, transport)
    with pytest.raises(fg.FortyGuardError, match="parser needs updating"):
        fg.get_heat_grid_for_route(ROUTE)


# --- geometry -------------------------------------------------------------

def test_route_aoi_is_one_polygon_within_plan_limits():
    """Spec section 5: one API call per route, not one per sample point."""
    poly = buffered_bbox_polygon(ROUTE, 120)
    assert poly["type"] == "FeatureCollection"
    assert len(poly["features"]) == 1
    ring = poly["features"][0]["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]  # closed
    assert polygon_area_km2(poly) < fg.MAX_AOI_KM2


def test_buffer_actually_contains_the_route():
    poly = buffered_bbox_polygon(ROUTE, 120)
    ring = poly["features"][0]["geometry"]["coordinates"][0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    for lon, lat in ROUTE:
        assert min(lons) < lon < max(lons)
        assert min(lats) < lat < max(lats)


def test_haversine_matches_known_distance():
    # The two demo placeholder points are ~500m apart.
    d = haversine_m(ROUTE[0], ROUTE[1])
    assert 400 < d < 600
