"""Routing, segmentation, and OSM context. All network mocked."""

import httpx
import pytest

from backend import config
from backend.cache import store
from backend.services import osm, routing, segmentation
from backend.services.geo import haversine_m

_RealClient = httpx.Client

# A straight ~450m east-west run in Fresno.
ROUTE = [(-119.8000, 36.7500), (-119.7950, 36.7500)]


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CACHE_DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "CACHE_DB_PATH", tmp_path / "t.db")
    store._initialised.clear()


# --- segmentation ---------------------------------------------------------

def test_segments_are_equal_length_with_no_stub():
    """A 4m orphan segment would get its own rank and its own intervention
    recommendation despite being too short to act on."""
    segs = segmentation.segment_route(ROUTE, segment_length_m=50)
    lengths = {s["length_m"] for s in segs}
    assert len(lengths) == 1, "segments must be uniform"
    assert 45 <= segs[0]["length_m"] <= 55


def test_segment_count_matches_route_length():
    segs = segmentation.segment_route(ROUTE, segment_length_m=50)
    total = sum(s["length_m"] for s in segs)
    assert abs(total - haversine_m(*ROUTE)) < 1.0


def test_segments_are_contiguous_and_ordered():
    segs = segmentation.segment_route(ROUTE, segment_length_m=50)
    for i in range(len(segs) - 1):
        assert segs[i]["index"] == i
        end = (segs[i]["end"]["lon"], segs[i]["end"]["lat"])
        nxt = (segs[i + 1]["start"]["lon"], segs[i + 1]["start"]["lat"])
        assert haversine_m(end, nxt) < 0.5, "gap between consecutive segments"


def test_midpoint_lies_between_ends():
    seg = segmentation.segment_route(ROUTE, segment_length_m=50)[0]
    start = (seg["start"]["lon"], seg["start"]["lat"])
    end = (seg["end"]["lon"], seg["end"]["lat"])
    mid = (seg["midpoint"]["lon"], seg["midpoint"]["lat"])
    assert abs(haversine_m(start, mid) - haversine_m(mid, end)) < 1.0


def test_short_route_still_yields_one_segment():
    segs = segmentation.segment_route(
        [(-119.80, 36.75), (-119.7998, 36.75)], segment_length_m=50
    )
    assert len(segs) == 1


def test_rejects_degenerate_routes():
    with pytest.raises(ValueError, match="at least two"):
        segmentation.segment_route([(-119.8, 36.75)])
    with pytest.raises(ValueError, match="zero length"):
        segmentation.segment_route([(-119.8, 36.75), (-119.8, 36.75)])


# --- heat sampling --------------------------------------------------------

def _grid(*vals):
    return [{"lon": -119.7999 + i * 0.001, "lat": 36.7500, "value": v}
            for i, v in enumerate(vals)]


def test_sampling_picks_the_nearest_tile():
    segs = segmentation.segment_route(ROUTE, segment_length_m=200)
    out = segmentation.sample_heat_onto_segments(segs, _grid(10.0, 20.0, 30.0, 40.0))
    assert all("heat_value" in s for s in out)
    assert all(s["heat_tile_distance_m"] < 200 for s in out)


def test_sampling_rejects_a_grid_that_misses_the_route():
    """Silently scoring from a tile 5 km away would look completely healthy."""
    segs = segmentation.segment_route(ROUTE, segment_length_m=50)
    far = [{"lon": -119.9, "lat": 36.9, "value": 1.0}]
    with pytest.raises(ValueError, match="nearest heat tile"):
        segmentation.sample_heat_onto_segments(segs, far)


def test_sampling_an_empty_grid_is_an_error():
    segs = segmentation.segment_route(ROUTE, segment_length_m=50)
    with pytest.raises(ValueError, match="empty heat grid"):
        segmentation.sample_heat_onto_segments(segs, [])


def test_summarise_reports_within_route_spread():
    """The spread is what tells a reader whether the ranking means anything."""
    segs = segmentation.segment_route(ROUTE, segment_length_m=200)
    out = segmentation.sample_heat_onto_segments(segs, _grid(10.0, 20.0, 30.0, 40.0))
    s = segmentation.summarise(out)
    assert s["heat_spread"] == round(s["heat_max"] - s["heat_min"], 3)
    assert s["segment_count"] == len(out)


# --- OSM geometry ---------------------------------------------------------

def test_distance_uses_nearest_vertex_not_centroid():
    """Regression: a long road's centroid can sit far from the route while the
    road itself runs alongside it. Measuring to the centroid found zero asphalt
    on a route that is entirely asphalt."""
    long_road = {
        "tags": {"highway": "residential", "surface": "asphalt"},
        "points": [(-119.8000, 36.7500), (-119.7000, 36.7500)],  # ~9km east
    }
    target = (-119.7995, 36.7500)  # 45m from the west end, ~4.5km from centroid
    assert osm.distance_to(long_road, target) < 60


def test_context_finds_surface_from_an_adjacent_way():
    features = [{
        "tags": {"highway": "residential", "surface": "asphalt"},
        "points": [(-119.8000, 36.7500), (-119.7000, 36.7500)],
    }]
    ctx = osm.get_segment_context((-119.7999, 36.7500), features)
    assert ctx["surface"] == "asphalt"


def test_context_counts_trees_only_within_radius():
    features = [
        {"tags": {"natural": "tree"}, "points": [(-119.80000, 36.75000)]},
        {"tags": {"natural": "tree"}, "points": [(-119.80005, 36.75000)]},
        {"tags": {"natural": "tree"}, "points": [(-119.79000, 36.75000)]},  # ~890m
    ]
    ctx = osm.get_segment_context((-119.80000, 36.75000), features, radius_m=25)
    assert ctx["canopy"]["tree_count"] == 2


def test_missing_surface_is_none_not_asphalt():
    """Absent OSM data is not the same as bare asphalt (METHODOLOGY 5.4)."""
    ctx = osm.get_segment_context((-119.80, 36.75), [])
    assert ctx["surface"] is None
    assert ctx["canopy"]["tree_count"] == 0


def test_amenities_use_the_100m_radius_and_are_sorted():
    features = [
        {"tags": {"amenity": "school", "name": "Far"},
         "points": [(-119.79910, 36.75000)]},   # ~80m
        {"tags": {"amenity": "clinic", "name": "Near"},
         "points": [(-119.79997, 36.75000)]},   # ~3m
        {"tags": {"amenity": "school", "name": "TooFar"},
         "points": [(-119.79500, 36.75000)]},   # ~450m
    ]
    ctx = osm.get_segment_context((-119.80, 36.75), features)
    names = [a["name"] for a in ctx["nearby_amenities"]]
    assert names == ["Near", "Far"]


def test_water_uses_the_300m_radius():
    near = [{"tags": {"amenity": "drinking_water"}, "points": [(-119.79890, 36.75000)]}]
    far = [{"tags": {"amenity": "drinking_water"}, "points": [(-119.79000, 36.75000)]}]
    assert osm.get_segment_context((-119.80, 36.75), near)["water_within_m"] is not None
    assert osm.get_segment_context((-119.80, 36.75), far)["water_within_m"] is None


def test_overpass_query_requests_geometry():
    q = osm.build_query(36.74, -119.81, 36.76, -119.79)
    assert "out geom" in q, "centroids are wrong for linear features"
    assert '"natural"="tree"' in q and '"amenity"="drinking_water"' in q


# --- routing --------------------------------------------------------------

def _ors_transport(status=200, coords=None, distance=704.0):
    coords = coords or [[-119.8, 36.75], [-119.799, 36.75], [-119.7950, 36.75]]

    def handler(request):
        assert request.headers["User-Agent"], "Overpass and ORS both need a UA"
        if status != 200:
            return httpx.Response(status, text="denied")
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"summary": {"distance": distance, "duration": 507.0}},
            }],
        })

    return httpx.MockTransport(handler)


def _patch(monkeypatch, transport, key="test-ors-key"):
    monkeypatch.setattr(config, "ORS_API_KEY", key)
    monkeypatch.setattr(routing.httpx, "post",
                        lambda *a, **kw: _RealClient(transport=transport).post(*a, **kw))
    monkeypatch.setattr(routing.httpx, "get",
                        lambda *a, **kw: _RealClient(transport=transport).get(*a, **kw))


def test_ors_route_is_parsed(monkeypatch):
    _patch(monkeypatch, _ors_transport())
    r = routing.get_route((-119.8, 36.75), (-119.795, 36.75))
    assert r["distance_m"] == 704.0
    assert r["provider"] == "openrouteservice"
    assert r["profile"] == "foot-walking"
    assert len(r["coordinates"]) == 3
    assert r["cache_hit"] is False


def test_second_route_call_is_cached(monkeypatch):
    calls = {"n": 0}
    transport = _ors_transport()
    inner = transport.handler

    def counting(request):
        calls["n"] += 1
        return inner(request)

    _patch(monkeypatch, httpx.MockTransport(counting))
    routing.get_route((-119.8, 36.75), (-119.795, 36.75))
    again = routing.get_route((-119.8, 36.75), (-119.795, 36.75))
    assert again["cache_hit"] is True
    assert calls["n"] == 1


def test_rejected_ors_key_is_reported_clearly(monkeypatch):
    _patch(monkeypatch, _ors_transport(status=403))
    with pytest.raises(routing.RoutingError, match="rejected the key"):
        routing.get_route((-119.8, 36.75), (-119.795, 36.75))


def test_ors_rate_limit_names_the_quota(monkeypatch):
    _patch(monkeypatch, _ors_transport(status=429))
    with pytest.raises(routing.RoutingError, match="rate limit"):
        routing.get_route((-119.8, 36.75), (-119.795, 36.75))


def test_single_point_route_is_rejected(monkeypatch):
    _patch(monkeypatch, _ors_transport(coords=[[-119.8, 36.75]]))
    with pytest.raises(routing.RoutingError, match="fewer than two points"):
        routing.get_route((-119.8, 36.75), (-119.795, 36.75))


def test_missing_ors_key_falls_back_to_osrm(monkeypatch):
    monkeypatch.setattr(config, "ORS_API_KEY", "")

    def handler(request):
        assert "project-osrm.org" in str(request.url)
        return httpx.Response(200, json={"routes": [{
            "distance": 800.0, "duration": 600.0,
            "geometry": {"coordinates": [[-119.8, 36.75], [-119.795, 36.75]]},
        }]})

    monkeypatch.setattr(routing.httpx, "get",
                        lambda *a, **kw: _RealClient(
                            transport=httpx.MockTransport(handler)).get(*a, **kw))
    r = routing.get_route((-119.8, 36.75), (-119.795, 36.75))
    assert r["provider"] == "osrm"
    assert "car-biased" in r["profile"]
