"""Split a route into fixed segments and attach heat and context to each.

Implements the `segment_route` agent tool (spec section 8) and the sampling
step that connects the FortyGuard grid to the route line.
"""

from typing import Any

from backend import config
from backend.services.geo import Coord, haversine_m


def _cumulative_distances(coords: list[Coord]) -> list[float]:
    cum = [0.0]
    for i in range(len(coords) - 1):
        cum.append(cum[-1] + haversine_m(coords[i], coords[i + 1]))
    return cum


def point_at_distance(coords: list[Coord], cum: list[float], target: float) -> Coord:
    """Interpolate a point `target` metres along the polyline.

    Linear interpolation in lon/lat is accurate to well under a metre at the
    50 m scale we cut at, so no projection is needed.
    """
    if target <= 0:
        return coords[0]
    if target >= cum[-1]:
        return coords[-1]

    for i in range(len(cum) - 1):
        if cum[i] <= target <= cum[i + 1]:
            span = cum[i + 1] - cum[i]
            if span == 0:
                return coords[i]
            t = (target - cum[i]) / span
            lon = coords[i][0] + t * (coords[i + 1][0] - coords[i][0])
            lat = coords[i][1] + t * (coords[i + 1][1] - coords[i][1])
            return (lon, lat)
    return coords[-1]


def segment_route(
    coordinates: list[Coord],
    route_id: str = "route",
    segment_length_m: float | None = None,
) -> list[dict[str, Any]]:
    """Cut a route into equal-length segments of roughly `segment_length_m`.

    Segments are equal rather than exactly 50 m with a remainder: a 704 m route
    becomes 14 segments of 50.3 m, not 14 of 50 m plus a 4 m stub. A stub would
    get its own rank and its own intervention recommendation despite being too
    short to act on, which is a nonsense output to put in front of a planner.
    """
    if len(coordinates) < 2:
        raise ValueError("need at least two coordinates to segment a route")

    target = segment_length_m or config.SEGMENT_LENGTH_M
    cum = _cumulative_distances(coordinates)
    total = cum[-1]
    if total <= 0:
        raise ValueError("route has zero length")

    count = max(1, round(total / target))
    actual = total / count

    segments = []
    for i in range(count):
        start_d = i * actual
        end_d = (i + 1) * actual
        start = point_at_distance(coordinates, cum, start_d)
        end = point_at_distance(coordinates, cum, end_d)
        midpoint = point_at_distance(coordinates, cum, (start_d + end_d) / 2)
        segments.append({
            "id": f"{route_id}_seg_{i:02d}",
            "route_id": route_id,
            "index": i,
            "start": {"lon": start[0], "lat": start[1]},
            "end": {"lon": end[0], "lat": end[1]},
            "midpoint": {"lon": midpoint[0], "lat": midpoint[1]},
            "length_m": round(actual, 2),
        })
    return segments


def sample_heat_onto_segments(
    segments: list[dict[str, Any]],
    grid: list[dict[str, float]],
    max_distance_m: float = 200.0,
) -> list[dict[str, Any]]:
    """Attach the nearest heat-grid tile value to each segment.

    Nearest tile rather than an average: tiles are 60 m and segments ~50 m, so
    a segment sits inside roughly one tile. Averaging neighbours would blur the
    small spatial differences that the ranking depends on.

    `heat_tile_distance_m` is kept for validation — if it approaches the tile
    size, the segment is being scored from a tile it does not sit in.
    """
    if not grid:
        raise ValueError("cannot sample an empty heat grid")

    out = []
    for seg in segments:
        mid = (seg["midpoint"]["lon"], seg["midpoint"]["lat"])
        best = None
        best_d = float("inf")
        for tile in grid:
            d = haversine_m(mid, (tile["lon"], tile["lat"]))
            if d < best_d:
                best_d, best = d, tile

        if best_d > max_distance_m:
            raise ValueError(
                f"segment {seg['id']} is {best_d:.0f} m from the nearest heat tile; "
                "the AOI polygon probably does not cover the route"
            )

        out.append({
            **seg,
            "heat_value": best["value"],
            "heat_tile_distance_m": round(best_d, 1),
        })
    return out


def attach_context(
    segments: list[dict[str, Any]], features: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach OSM context to each segment. Makes no network call."""
    from backend.services.osm import get_segment_context

    return [
        {
            **seg,
            "context": get_segment_context(
                (seg["midpoint"]["lon"], seg["midpoint"]["lat"]), features
            ),
        }
        for seg in segments
    ]


def summarise(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Route-level facts, including the within-route heat spread.

    The spread is reported alongside every ranking because HEI normalises
    within the route: a small spread means the ranking is amplifying a small
    absolute difference, and a reader is entitled to know that
    (METHODOLOGY section 2.1).
    """
    values = [s["heat_value"] for s in segments if "heat_value" in s]
    total_m = sum(s["length_m"] for s in segments)
    out = {
        "segment_count": len(segments),
        "total_length_m": round(total_m, 1),
        "mean_segment_length_m": round(total_m / len(segments), 1) if segments else 0,
    }
    if values:
        out["heat_min"] = min(values)
        out["heat_max"] = max(values)
        out["heat_spread"] = round(max(values) - min(values), 3)
    return out


def attach_landcover(
    segments: list[dict[str, Any]], use_cache_only: bool = True
) -> list[dict[str, Any]]:
    """Attach FortyGuard satellite land-cover classes to each segment.

    With use_cache_only=True (the default) this makes no network call and no
    credit spend: segments without cached imagery simply carry no `landcover`,
    and the scoring model falls back to OSM for them. Pre-fetch with
    scripts/fetch_segmentation.py.
    """
    from backend.cache import store
    from backend.services.fortyguard import (
        SATELLITE_CACHE_MAX_AGE_S,
        SATELLITE_NAMESPACE,
        get_surface_segmentation,
    )

    out = []
    for seg in segments:
        mid = seg["midpoint"]
        key = f"{mid['lat']:.6f},{mid['lon']:.6f}@80"
        cached = store.get(SATELLITE_NAMESPACE, key, max_age_s=SATELLITE_CACHE_MAX_AGE_S)
        if cached is None and not use_cache_only:
            cached = get_surface_segmentation(mid["lat"], mid["lon"])
        out.append({**seg, "landcover": (cached or {}).get("classes")})
    return out
