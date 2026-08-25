#!/usr/bin/env python3
"""Find real transit-stop to school/clinic walking routes in Fresno.

Spec section 3 requires two demo routes, each a transit stop to a school or
clinic, 400-900 m long. Rather than picking coordinates by eye, this queries
OSM for actual bus stops and destinations, pairs them, and measures the real
walking distance with OpenRouteService.

Route choice is Minqi's call (spec section 12). This produces evidence-backed
candidates for that decision, not the decision itself.

Usage:
    python scripts/find_routes.py                  # top candidates
    python scripts/find_routes.py --max-verify 40  # spend more ORS calls
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from backend import config  # noqa: E402
from backend.cache import store  # noqa: E402
from backend.services.geo import haversine_m  # noqa: E402
from backend.services.routing import RoutingError, get_route  # noqa: E402

# Central Fresno.
BBOX = (36.70, -119.86, 36.82, -119.72)  # south, west, north, east

MIN_M, MAX_M = 400, 900

QUERY = """
[out:json][timeout:90];
(
  node["highway"="bus_stop"]({bbox});
  node["amenity"~"^(school|clinic|hospital|doctors)$"]({bbox});
  way["amenity"~"^(school|clinic|hospital|doctors)$"]({bbox});
);
out center tags;
"""


def fetch(use_cache=True):
    q = QUERY.format(bbox=f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}").strip()
    if use_cache:
        cached = store.get("route_finder", "fresno_v1", max_age_s=7 * 24 * 3600)
        if cached:
            print(f"  (from cache: {len(cached)} elements)")
            return cached
    print("  querying Overpass ...")
    r = httpx.post(config.OVERPASS_URL, data={"data": q},
                   headers={"User-Agent": config.USER_AGENT}, timeout=120.0)
    r.raise_for_status()
    els = r.json().get("elements", [])
    store.put("route_finder", "fresno_v1", els)
    return els


def point(el):
    if "lon" in el:
        return (float(el["lon"]), float(el["lat"]))
    c = el.get("center")
    return (float(c["lon"]), float(c["lat"])) if c else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-verify", type=int, default=25,
                    help="how many candidate pairs to measure with ORS")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    print("\nFinding transit-stop -> school/clinic routes in Fresno\n")
    els = fetch(use_cache=not args.no_cache)

    stops, dests = [], []
    for el in els:
        p = point(el)
        if not p:
            continue
        tags = el.get("tags") or {}
        if tags.get("highway") == "bus_stop":
            stops.append({"pt": p, "name": tags.get("name") or "Bus stop"})
        elif tags.get("amenity") in ("school", "clinic", "hospital", "doctors"):
            dests.append({
                "pt": p,
                "name": tags.get("name") or tags["amenity"].title(),
                "kind": tags["amenity"],
            })

    print(f"  {len(stops)} bus stops, {len(dests)} schools/clinics\n")
    if not stops or not dests:
        print("  nothing to pair — widen BBOX")
        return 1

    # Straight-line prefilter. Walking is always longer than straight-line, so
    # scan a band below the target range and let ORS decide.
    pairs = []
    for d in dests:
        best = None
        for s in stops:
            m = haversine_m(s["pt"], d["pt"])
            if 250 <= m <= 800 and (best is None or m < best[0]):
                best = (m, s)
        if best:
            pairs.append({"straight_m": best[0], "stop": best[1], "dest": d})

    pairs.sort(key=lambda p: abs(p["straight_m"] - 550))
    print(f"  {len(pairs)} candidate pairs; measuring the closest "
          f"{min(args.max_verify, len(pairs))} with OpenRouteService\n")

    results = []
    for p in pairs[:args.max_verify]:
        try:
            r = get_route(p["stop"]["pt"], p["dest"]["pt"])
        except RoutingError as e:
            print(f"  skip: {str(e)[:70]}")
            continue
        if not r.get("cache_hit"):
            time.sleep(1.6)  # ORS free tier: 40 requests/minute
        dist = r["distance_m"]
        if MIN_M <= dist <= MAX_M:
            results.append({**p, "walk_m": dist, "duration_s": r["duration_s"],
                            "points": len(r["coordinates"])})

    if not results:
        print("  no pairs landed in the 400-900 m band. Try --max-verify 60.")
        return 1

    results.sort(key=lambda r: r["dest"]["kind"] != "school")

    print(f"{'':2} {'walk':>6}  {'kind':<9} {'destination':<38} from")
    print("  " + "-" * 86)
    for i, r in enumerate(results, 1):
        print(f"{i:2} {r['walk_m']:6.0f}m  {r['dest']['kind']:<9} "
              f"{r['dest']['name'][:37]:<38} {r['stop']['name'][:28]}")

    out = Path("data/route_candidates.json")
    out.write_text(json.dumps([
        {
            "origin_name": r["stop"]["name"],
            "destination_name": r["dest"]["name"],
            "destination_kind": r["dest"]["kind"],
            "origin": {"lon": r["stop"]["pt"][0], "lat": r["stop"]["pt"][1]},
            "destination": {"lon": r["dest"]["pt"][0], "lat": r["dest"]["pt"][1]},
            "walk_distance_m": round(r["walk_m"], 1),
            "walk_duration_s": round(r["duration_s"], 1),
        }
        for r in results
    ], indent=2))
    print(f"\n  {len(results)} candidates -> {out}")
    print("  Minqi picks two: ideally one school, one clinic.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
