"""Pedestrian routing via OpenRouteService, with an OSRM fallback.

Implements the `get_route` agent tool (spec section 8).

Why OpenRouteService: its foot-walking profile follows footways, crossings, and
paths. OSRM's public demo server only offers a driving profile, so it snaps
pedestrians onto the road network. That matters more than it sounds — segment
geometry drives DTF, and every segment's heat and context lookup is anchored to
the route line, so a car-shaped route quietly corrupts the whole score.
"""

from typing import Any

import httpx

from backend import config
from backend.cache import store
from backend.services.geo import Coord, path_length_m

CACHE_NAMESPACE = "route"

# Demo routes are fixed, so a route computed once never needs recomputing.
CACHE_MAX_AGE_S = 30 * 24 * 3600

ORS_URL = "https://api.openrouteservice.org/v2/directions/foot-walking/geojson"
OSRM_URL = "https://router.project-osrm.org/route/v1/foot"

WALKING_PROFILE = "foot-walking"


class RoutingError(RuntimeError):
    """Any failure producing a walking route."""


def _cache_key(origin: Coord, destination: Coord, provider: str) -> str:
    return f"{provider}:{origin[0]:.6f},{origin[1]:.6f}->{destination[0]:.6f},{destination[1]:.6f}"


def _route_via_ors(origin: Coord, destination: Coord) -> dict[str, Any]:
    if not config.ORS_API_KEY:
        raise RoutingError("ORS_API_KEY is not set")

    try:
        resp = httpx.post(
            ORS_URL,
            headers={
                "Authorization": config.ORS_API_KEY,
                "Content-Type": "application/json",
                "User-Agent": config.USER_AGENT,
            },
            json={"coordinates": [list(origin), list(destination)]},
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        raise RoutingError(f"OpenRouteService unreachable: {e}") from e

    if resp.status_code in (401, 403):
        raise RoutingError(f"OpenRouteService rejected the key ({resp.status_code})")
    if resp.status_code == 429:
        raise RoutingError("OpenRouteService rate limit reached (2000/day, 40/min)")
    if resp.status_code >= 400:
        raise RoutingError(f"OpenRouteService error {resp.status_code}: {resp.text[:300]}")

    body = resp.json()
    features = body.get("features") or []
    if not features:
        raise RoutingError("OpenRouteService returned no route between those points")

    feature = features[0]
    coords = [(float(c[0]), float(c[1])) for c in feature["geometry"]["coordinates"]]
    summary = (feature.get("properties") or {}).get("summary") or {}

    return {
        "coordinates": coords,
        # Summary is empty for zero-length routes; fall back to measuring.
        "distance_m": float(summary.get("distance") or path_length_m(coords)),
        "duration_s": float(summary.get("duration") or 0.0),
        "provider": "openrouteservice",
        "profile": WALKING_PROFILE,
    }


def _route_via_osrm(origin: Coord, destination: Coord) -> dict[str, Any]:
    """Fallback only. The public demo server is car-biased — see module docstring."""
    url = (
        f"{OSRM_URL}/{origin[0]},{origin[1]};{destination[0]},{destination[1]}"
        "?overview=full&geometries=geojson"
    )
    try:
        resp = httpx.get(url, headers={"User-Agent": config.USER_AGENT},
                         timeout=30.0)
    except httpx.HTTPError as e:
        raise RoutingError(f"OSRM unreachable: {e}") from e

    if resp.status_code >= 400:
        raise RoutingError(f"OSRM error {resp.status_code}: {resp.text[:300]}")

    body = resp.json()
    routes = body.get("routes") or []
    if not routes:
        raise RoutingError(f"OSRM returned no route: {body.get('message')}")

    route = routes[0]
    coords = [(float(c[0]), float(c[1])) for c in route["geometry"]["coordinates"]]
    return {
        "coordinates": coords,
        "distance_m": float(route.get("distance") or path_length_m(coords)),
        "duration_s": float(route.get("duration") or 0.0),
        "provider": "osrm",
        "profile": "driving (car-biased fallback)",
    }


def get_route(
    origin: Coord,
    destination: Coord,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Walking route between two (lon, lat) points.

    Returns {coordinates, distance_m, duration_s, provider, profile}.
    """
    provider = "ors" if config.ORS_API_KEY else "osrm"
    key = _cache_key(origin, destination, provider)

    if use_cache:
        cached = store.get(CACHE_NAMESPACE, key, max_age_s=CACHE_MAX_AGE_S)
        if cached is not None:
            cached["coordinates"] = [tuple(c) for c in cached["coordinates"]]
            cached["cache_hit"] = True
            return cached

    route = _route_via_ors(origin, destination) if config.ORS_API_KEY else _route_via_osrm(
        origin, destination
    )

    if len(route["coordinates"]) < 2:
        raise RoutingError("route has fewer than two points; cannot segment it")

    route["cache_hit"] = False
    store.put(CACHE_NAMESPACE, key, route)
    return route
