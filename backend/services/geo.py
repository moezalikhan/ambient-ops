"""Geometry helpers. No geo dependencies — the maths here is small and exact
enough at street scale, and every extra wheel is a deploy risk during a hackathon.
"""

import math

EARTH_RADIUS_M = 6_371_000.0

Coord = tuple[float, float]  # (lon, lat) — GeoJSON order throughout


def haversine_m(a: Coord, b: Coord) -> float:
    """Great-circle distance in metres between two (lon, lat) points."""
    lon1, lat1 = a
    lon2, lat2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def path_length_m(coords: list[Coord]) -> float:
    return sum(haversine_m(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def buffered_bbox_polygon(coords: list[Coord], buffer_m: float) -> dict:
    """One GeoJSON FeatureCollection covering the whole route plus a margin.

    Spec section 5 efficiency note: the heatmap endpoint takes a polygon, not a
    point, so buffering the entire route into a single AOI means one API call
    per route instead of one per sample point. A 900m route with a 120m buffer
    is roughly 0.5 mi², comfortably inside the 10 mi² Basic-plan ceiling.
    """
    if not coords:
        raise ValueError("cannot build a polygon from an empty route")

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    # Degrees per metre. Longitude converges toward the poles, so scale it by
    # the cosine of the mid-latitude rather than reusing the latitude figure.
    mid_lat = (min_lat + max_lat) / 2
    d_lat = buffer_m / 111_320.0
    d_lon = buffer_m / (111_320.0 * max(math.cos(math.radians(mid_lat)), 1e-6))

    w, e = min_lon - d_lon, max_lon + d_lon
    s, n = min_lat - d_lat, max_lat + d_lat

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    # Closed ring, counter-clockwise from the south-west corner.
                    "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
                },
            }
        ],
    }


def polygon_area_km2(polygon_fc: dict) -> float:
    """Approximate AOI area. Used to stay under the plan's mi² ceiling."""
    ring = polygon_fc["features"][0]["geometry"]["coordinates"][0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    mid_lat = (min(lats) + max(lats)) / 2
    width_km = (max(lons) - min(lons)) * 111.32 * math.cos(math.radians(mid_lat))
    height_km = (max(lats) - min(lats)) * 111.32
    return width_km * height_km


def feature_centroid(feature: dict) -> Coord:
    """Centroid of a GeoJSON Polygon feature, as (lon, lat).

    Heatmap tiles come back as small polygons; the scoring pipeline needs one
    representative point per tile.
    """
    geom = feature["geometry"]
    if geom["type"] == "Point":
        return (geom["coordinates"][0], geom["coordinates"][1])
    ring = geom["coordinates"][0]
    pts = ring[:-1] if ring[0] == ring[-1] else ring
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
