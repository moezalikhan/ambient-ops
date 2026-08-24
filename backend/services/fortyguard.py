"""FortyGuard Temperature API client — submit, poll, cache.

The API is asynchronous: POST an area of interest, get an `activity_id` back,
then poll `GET /status/{activity_id}` until the activity completes.

Contract (verified against docs-api.fortyguard.com, API v1.0.0):

    POST /v1/heatmap                 header: api-key: <KEY>
      polygon_aoi    GeoJSON FeatureCollection (required)
      date_time      {start_date, filter_type, start_time?, end_time?, end_date?}
      granularity    60 | 80 | 100  (metres)
      analytic_type  tcm | time_of_measure | exceedance | persistence
      threshold      °C, default 30 (exceedance/persistence only)
      direction      above | below   (exceedance/persistence only)
    -> {"data": {"activity_id": "..."}}

    GET /v1/status/{activity_id}
    -> {"data": {"status": "Completed", "result": {"map_data": ..., "stats_data": ...}}}

Units: tcm returns °C; time_of_measure, exceedance and persistence return hours.
"""

import hashlib
import json
import time
from datetime import date, timedelta
from typing import Any

import httpx

from backend import config
from backend.cache import store
from backend.services.geo import buffered_bbox_polygon, feature_centroid, polygon_area_km2

CACHE_NAMESPACE = "fortyguard_heatmap"

# Heat grids for a fixed historical window do not change. Cache for a week so
# repeated demo runs never touch the network.
CACHE_MAX_AGE_S = 7 * 24 * 3600

VALID_ANALYTIC_TYPES = {"tcm", "time_of_measure", "exceedance", "persistence"}
VALID_GRANULARITIES = {60, 80, 100}

# Basic plan ceiling is 10 mi². Refuse locally rather than burning a submission.
MAX_AOI_KM2 = 10 * 2.58999


class FortyGuardError(RuntimeError):
    """Any failure talking to FortyGuard, with the cause made explicit."""


def _headers() -> dict[str, str]:
    if not config.FORTYGUARD_API_KEY:
        raise FortyGuardError(
            "FORTYGUARD_API_KEY is not set. Add it to .env — see .env.example."
        )
    return {"api-key": config.FORTYGUARD_API_KEY, "Content-Type": "application/json"}


def _raise_for_response(resp: httpx.Response, what: str) -> dict[str, Any]:
    if resp.status_code == 401 or resp.status_code == 403:
        raise FortyGuardError(
            f"{what}: {resp.status_code} — API key rejected. Check FORTYGUARD_API_KEY."
        )
    if resp.status_code == 402:
        raise FortyGuardError(f"{what}: 402 — out of credits on this plan.")
    if resp.status_code == 429:
        raise FortyGuardError(f"{what}: 429 — rate limited. Back off and retry.")
    if resp.status_code >= 400:
        raise FortyGuardError(f"{what}: {resp.status_code} — {resp.text[:400]}")

    body = resp.json()
    if body.get("error"):
        raise FortyGuardError(f"{what}: API reported error — {body.get('message')}")
    return body


def default_date_window(days: int | None = None) -> dict[str, Any]:
    """A multi-week window ending yesterday. filter_type 4 = range of days.

    Not a single day, and deliberately so. Measured in Fresno on 2026-08-24:
    at any single hour the spatial spread across a route is about 0.18 °C,
    which normalises into a ranking that is mostly model noise. Counting
    threshold crossings over 30 days turns that same 0.18 °C into roughly
    10.5 hours of exposure difference — a real signal, because a marginally
    hotter tile crosses the threshold earlier every single afternoon.

    Nights need no special handling: they never reach the threshold, so they
    contribute zero to the count and the result is effectively daylight hours,
    which is the HEI definition in the spec.

    Yesterday is the end point because the API accepts only up to 12 hours
    ahead, and a partial day would skew the count.
    """
    days = days if days is not None else config.HEAT_WINDOW_DAYS
    end = date.today() - timedelta(days=1)
    return {
        "start_date": (end - timedelta(days=days)).isoformat(),
        "end_date": end.isoformat(),
        "filter_type": 4,
    }


def build_payload(
    polygon_aoi: dict,
    date_time: dict | None = None,
    granularity: int | None = None,
    analytic_type: str | None = None,
    threshold: float | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    """Assemble and validate a heatmap request body."""
    granularity = granularity or config.FORTYGUARD_GRANULARITY_M
    analytic_type = analytic_type or config.FORTYGUARD_ANALYTIC_TYPE

    if analytic_type not in VALID_ANALYTIC_TYPES:
        raise FortyGuardError(
            f"unknown analytic_type {analytic_type!r}; expected one of "
            f"{sorted(VALID_ANALYTIC_TYPES)}"
        )
    if granularity not in VALID_GRANULARITIES:
        raise FortyGuardError(
            f"granularity must be one of {sorted(VALID_GRANULARITIES)}, got {granularity}"
        )

    area = polygon_area_km2(polygon_aoi)
    if area > MAX_AOI_KM2:
        raise FortyGuardError(
            f"AOI is {area:.1f} km², over the {MAX_AOI_KM2:.1f} km² plan ceiling. "
            "Shorten the route or reduce ROUTE_BUFFER_M."
        )

    payload: dict[str, Any] = {
        "polygon_aoi": polygon_aoi,
        "date_time": date_time or default_date_window(),
        "granularity": granularity,
        "analytic_type": analytic_type,
    }
    # threshold and direction are ignored by tcm and time_of_measure — sending
    # them anyway invites a confident wrong answer, so leave them off.
    if analytic_type in ("exceedance", "persistence"):
        payload["threshold"] = (
            threshold if threshold is not None else config.HEAT_THRESHOLD_C
        )
        payload["direction"] = direction or config.HEAT_DIRECTION
    return payload


def _cache_key(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def submit_heatmap(payload: dict, client: httpx.Client | None = None) -> str:
    """POST the job. Returns the activity_id."""
    owns = client is None
    client = client or httpx.Client(timeout=60.0)
    try:
        resp = client.post(
            f"{config.FORTYGUARD_BASE_URL}/heatmap", headers=_headers(), json=payload
        )
        body = _raise_for_response(resp, "heatmap submit")
    finally:
        if owns:
            client.close()

    activity_id = (body.get("data") or {}).get("activity_id")
    if not activity_id:
        raise FortyGuardError(f"no activity_id in submit response: {body}")
    return activity_id


def poll_status(
    activity_id: str,
    timeout_s: float = 300.0,
    interval_s: float = 3.0,
    client: httpx.Client | None = None,
    on_poll=None,
) -> dict[str, Any]:
    """Poll until the activity completes. Returns the `result` object."""
    owns = client is None
    client = client or httpx.Client(timeout=60.0)
    deadline = time.monotonic() + timeout_s
    attempt = 0
    try:
        while True:
            attempt += 1
            resp = client.get(
                f"{config.FORTYGUARD_BASE_URL}/status/{activity_id}", headers=_headers()
            )
            body = _raise_for_response(resp, "status poll")
            data = body.get("data") or {}
            status = str(data.get("status", "")).lower()

            if on_poll:
                on_poll(attempt, status)

            if status == "completed":
                result = data.get("result")
                if result is None:
                    raise FortyGuardError(f"activity {activity_id} completed with no result")
                return result
            if status in ("failed", "error", "cancelled"):
                raise FortyGuardError(
                    f"activity {activity_id} ended as {status!r}: {body.get('message')}"
                )
            if time.monotonic() >= deadline:
                raise FortyGuardError(
                    f"activity {activity_id} still {status!r} after {timeout_s:.0f}s"
                )
            time.sleep(interval_s)
    finally:
        if owns:
            client.close()


# Which tile property holds the measurement, per analytic type. Verified against
# live responses on 2026-08-24:
#   exceedance / persistence / time_of_measure -> "value"        (hours)
#   tcm                                        -> "average_temperature" (°C)
#
# There is deliberately NO "first numeric property" fallback. tcm tiles carry a
# `tile_id` before any temperature field, so a fallback silently scores the grid
# on tile indices — a wrong answer that looks entirely healthy downstream.
VALUE_KEYS: dict[str, tuple[str, ...]] = {
    "exceedance": ("value",),
    "persistence": ("value",),
    "time_of_measure": ("value",),
    "tcm": ("average_temperature", "value"),
}

# Never treat these as measurements, whatever the layer.
NON_VALUE_KEYS = frozenset({"tile_id", "id", "index"})


def _flatten_grid(map_data: dict, analytic_type: str) -> list[dict[str, float]]:
    """GeoJSON tiles -> [{lat, lon, value, ...}] for a known analytic type."""
    keys = VALUE_KEYS.get(analytic_type)
    if keys is None:
        raise FortyGuardError(
            f"no value-key mapping for analytic_type {analytic_type!r}; "
            "add one to VALUE_KEYS rather than guessing at runtime"
        )

    grid: list[dict[str, float]] = []
    for feature in (map_data or {}).get("features", []):
        props = feature.get("properties") or {}
        value = next(
            (
                float(props[k])
                for k in keys
                if k not in NON_VALUE_KEYS and isinstance(props.get(k), (int, float))
            ),
            None,
        )
        if value is None:
            continue
        lon, lat = feature_centroid(feature)
        tile = {"lat": lat, "lon": lon, "value": value}
        # tcm also reports the temporal range within the tile, which is what
        # tells us whether a threshold can discriminate at all.
        for extra in ("min_temperature", "max_temperature"):
            if isinstance(props.get(extra), (int, float)):
                tile[extra] = float(props[extra])
        grid.append(tile)
    return grid


def get_heat_grid(
    polygon_aoi: dict,
    date_time: dict | None = None,
    analytic_type: str | None = None,
    granularity: int | None = None,
    threshold: float | None = None,
    direction: str | None = None,
    use_cache: bool = True,
    timeout_s: float = 300.0,
    on_poll=None,
) -> dict[str, Any]:
    """Submit, poll, and normalise one heatmap. Cache-first.

    This is the `get_heat_grid` agent tool from spec section 8: it handles
    submit and poll internally and checks the cache first.
    """
    payload = build_payload(
        polygon_aoi, date_time, granularity, analytic_type, threshold, direction
    )
    key = _cache_key(payload)

    if use_cache:
        cached = store.get(CACHE_NAMESPACE, key, max_age_s=CACHE_MAX_AGE_S)
        if cached is not None:
            cached["cache_hit"] = True
            return cached

    with httpx.Client(timeout=60.0) as client:
        activity_id = submit_heatmap(payload, client=client)
        result = poll_status(
            activity_id, timeout_s=timeout_s, client=client, on_poll=on_poll
        )

    map_data = result.get("map_data") or {}
    stats = result.get("stats_data") or {}
    features = map_data.get("features") if isinstance(map_data, dict) else None
    grid = _flatten_grid(map_data, payload["analytic_type"])
    if not grid:
        # Distinguish the two very different causes. An empty FeatureCollection
        # means the AOI is outside coverage (FortyGuard is US-only); features
        # that exist but yield nothing means our parser is wrong. Conflating
        # them cost real debugging time once already.
        if not features:
            raise FortyGuardError(
                f"heatmap completed but returned zero tiles (n_cells={stats.get('n_cells', 0)}). "
                "The AOI is almost certainly outside coverage — FortyGuard data is US-only."
            )
        raise FortyGuardError(
            f"heatmap returned {len(features)} features but none had a numeric value "
            f"property — parser needs updating. First feature: "
            f"{list((features[0].get('properties') or {}).keys())}"
        )

    out = {
        "grid": grid,
        "layer": payload["analytic_type"],
        "resolution_m": payload["granularity"],
        "units": "hour" if payload["analytic_type"] != "tcm" else "celsius",
        "threshold_c": payload.get("threshold"),
        "direction": payload.get("direction"),
        "date_time": payload["date_time"],
        "stats_data": result.get("stats_data") or {},
        "activity_id": activity_id,
        "tile_count": len(grid),
        "cache_hit": False,
    }
    store.put(CACHE_NAMESPACE, key, out)
    return out


def get_heat_grid_for_route(
    coordinates: list[tuple[float, float]], **kwargs
) -> dict[str, Any]:
    """Convenience wrapper: buffer a route into one AOI and fetch its grid."""
    polygon = buffered_bbox_polygon(coordinates, config.ROUTE_BUFFER_M)
    return get_heat_grid(polygon, **kwargs)
