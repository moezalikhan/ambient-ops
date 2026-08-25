"""OpenStreetMap context via the Overpass API.

Implements the `get_segment_context` agent tool (spec section 8). This is what
turns a temperature number into a recommendation: trees, shelter, surface, and
the amenities that tell us who is walking here.

**One query per route, not one per segment.** The spec defines the tool as
get_segment_context(segment_id), and that is the interface the agent sees. But
issuing one Overpass query per 50 m segment would mean ~18 requests per route,
and Overpass rate-limits hard (spec section 5). So the whole route buffer is
fetched in a single query and features are assigned to segments locally. Same
contract, one network call.
"""

import hashlib
import time
from typing import Any

import httpx

from backend import config
from backend.cache import store
from backend.services.geo import Coord, haversine_m

CACHE_NAMESPACE = "overpass"

# OSM changes slowly and demo routes are fixed. A long TTL keeps the demo off
# the network entirely.
CACHE_MAX_AGE_S = 30 * 24 * 3600

# Metres either side of the route to fetch context for. Wider than the 25 m
# assignment radius so features just off the line are available for the
# "within 100 m" and "within 300 m" tests.
CONTEXT_BUFFER_M = 350

# Radius for "what is physically present at this segment" (spec section 5).
SEGMENT_RADIUS_M = 25

# Spec thresholds.
AMENITY_RADIUS_M = 100
WATER_RADIUS_M = 300

SENSITIVE_AMENITIES = {"school", "kindergarten", "clinic", "hospital", "doctors",
                       "social_facility", "nursing_home"}


class OverpassError(RuntimeError):
    """Any failure fetching OSM context."""


def build_query(south: float, west: float, north: float, east: float) -> str:
    """Overpass QL for everything the scoring model needs, in one request.

    `out geom` rather than `out center`. A centroid is fine for a building but
    wrong for anything linear: a 1 km road's centre can sit 500 m from our
    route, so distance-to-centroid found zero asphalt surfaces along a route
    that runs entirely on asphalt. With full geometry we measure to the nearest
    vertex instead, which is right for roads, parks, and water alike.
    """
    bbox = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:90];
(
  node["natural"="tree"]({bbox});
  way["natural"="tree_row"]({bbox});
  way["landuse"~"grass|forest|meadow"]({bbox});
  way["leisure"~"park|garden"]({bbox});
  node["amenity"="shelter"]({bbox});
  way["amenity"="shelter"]({bbox});
  node["highway"="bus_stop"]({bbox});
  node["public_transport"="platform"]({bbox});
  way["building"]({bbox});
  way["highway"]["surface"]({bbox});
  node["amenity"="drinking_water"]({bbox});
  node["amenity"~"school|kindergarten|clinic|hospital|doctors|social_facility"]({bbox});
  way["amenity"~"school|kindergarten|clinic|hospital|doctors|social_facility"]({bbox});
  way["natural"="water"]({bbox});
);
out geom tags;
""".strip()


def _element_points(el: dict) -> list[Coord]:
    """Every (lon, lat) belonging to an element.

    One point for a node; all vertices for a way. Distance to a feature is then
    the distance to its nearest vertex, which is correct for linear and areal
    features rather than only for compact ones.
    """
    if el.get("type") == "node" and "lon" in el:
        return [(float(el["lon"]), float(el["lat"]))]
    geom = el.get("geometry") or []
    pts = [(float(g["lon"]), float(g["lat"])) for g in geom if "lon" in g]
    if pts:
        return pts
    center = el.get("center")
    if center:
        return [(float(center["lon"]), float(center["lat"]))]
    return []


def distance_to(feature: dict, target: Coord) -> float:
    """Metres from `target` to the nearest vertex of `feature`."""
    return min(haversine_m(target, p) for p in feature["points"])


def fetch_features(
    south: float,
    west: float,
    north: float,
    east: float,
    use_cache: bool = True,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """Run one Overpass query and return normalised features.

    Each feature: {osm_type, osm_id, lon, lat, tags}.
    """
    query = build_query(south, west, north, east)
    key = hashlib.sha256(query.encode()).hexdigest()

    if use_cache:
        cached = store.get(CACHE_NAMESPACE, key, max_age_s=CACHE_MAX_AGE_S)
        if cached is not None:
            return cached

    last_error = None
    for attempt in range(max_retries):
        try:
            resp = httpx.post(
                config.OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": config.USER_AGENT},
                timeout=120.0,
            )
        except httpx.HTTPError as e:
            last_error = f"unreachable: {e}"
            time.sleep(2 ** attempt)
            continue

        # Overpass signals overload with 429 and 504. Backing off is the
        # documented remedy; hammering it earns a longer ban.
        if resp.status_code in (429, 504):
            last_error = f"rate limited ({resp.status_code})"
            time.sleep(5 * (attempt + 1))
            continue
        if resp.status_code >= 400:
            raise OverpassError(f"Overpass error {resp.status_code}: {resp.text[:300]}")

        elements = resp.json().get("elements", [])
        features = []
        for el in elements:
            points = _element_points(el)
            if not points:
                continue
            features.append({
                "osm_type": el.get("type"),
                "osm_id": el.get("id"),
                "points": points,
                "tags": el.get("tags") or {},
            })
        store.put(CACHE_NAMESPACE, key, features)
        return features

    raise OverpassError(f"Overpass failed after {max_retries} attempts: {last_error}")


def fetch_route_features(
    coordinates: list[Coord], buffer_m: float = CONTEXT_BUFFER_M, **kwargs
) -> list[dict[str, Any]]:
    """One Overpass call covering an entire route."""
    from backend.services.geo import buffered_bbox_polygon

    ring = buffered_bbox_polygon(coordinates, buffer_m)["features"][0]["geometry"][
        "coordinates"
    ][0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return fetch_features(min(lats), min(lons), max(lats), max(lons), **kwargs)


# --- classification -------------------------------------------------------

def _is_tree(tags: dict) -> bool:
    return tags.get("natural") in ("tree", "tree_row")


def _is_green(tags: dict) -> bool:
    return tags.get("leisure") in ("park", "garden") or tags.get("landuse") in (
        "grass", "forest", "meadow"
    )


def _is_water(tags: dict) -> bool:
    return tags.get("natural") == "water"


def _is_shelter(tags: dict) -> bool:
    return tags.get("amenity") == "shelter" or tags.get("shelter") == "yes"


def _is_transit(tags: dict) -> bool:
    return tags.get("highway") == "bus_stop" or tags.get("public_transport") == "platform"


def _is_building(tags: dict) -> bool:
    return "building" in tags


def _sensitive_amenity(tags: dict) -> str | None:
    a = tags.get("amenity")
    return a if a in SENSITIVE_AMENITIES else None


def get_segment_context(
    midpoint: Coord,
    features: list[dict[str, Any]],
    radius_m: float = SEGMENT_RADIUS_M,
) -> dict[str, Any]:
    """What is physically present around one segment.

    Returns the shape from spec section 8:
    {surface, canopy, shelter, nearby_amenities, water_within_m}

    `features` is the route-wide result of fetch_route_features, so this makes
    no network call.
    """
    trees = 0
    green_within = False
    water_within = False
    shelter = False
    buildings = 0
    surfaces: list[str] = []
    amenities: list[dict[str, Any]] = []
    transit_within = False
    water_distance: float | None = None

    for f in features:
        d = distance_to(f, midpoint)
        tags = f["tags"]

        if d <= radius_m:
            if _is_tree(tags):
                trees += 1
            if _is_green(tags):
                green_within = True
            if _is_water(tags):
                water_within = True
            if _is_shelter(tags):
                shelter = True
            if _is_building(tags):
                buildings += 1
            if tags.get("surface"):
                surfaces.append(tags["surface"])

        if d <= AMENITY_RADIUS_M:
            kind = _sensitive_amenity(tags)
            if kind:
                amenities.append({
                    "type": kind,
                    "name": tags.get("name"),
                    "distance_m": round(d, 1),
                })
            if _is_transit(tags):
                transit_within = True

        if d <= WATER_RADIUS_M and tags.get("amenity") == "drinking_water":
            if water_distance is None or d < water_distance:
                water_distance = round(d, 1)

    # Most common surface tag within the radius; None means OSM has no data
    # here, which is NOT the same as "bare asphalt" (METHODOLOGY 5.4).
    surface = max(set(surfaces), key=surfaces.count) if surfaces else None

    return {
        "surface": surface,
        "canopy": {
            "tree_count": trees,
            "green_area_within_m": green_within,
        },
        "shelter": shelter,
        "building_count": buildings,
        "water_adjacent": water_within,
        "nearby_amenities": sorted(amenities, key=lambda a: a["distance_m"]),
        "transit_within_100m": transit_within,
        "water_within_m": water_distance,
        "radius_m": radius_m,
    }
