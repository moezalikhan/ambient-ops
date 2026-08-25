#!/usr/bin/env python3
"""Run the full Step 3 pipeline for one demo route and print what came back.

    route -> segments -> heat sample -> OSM context

Doubles as the pre-caching tool for demo day (spec section 13): running it once
per route fills the SQLite cache, after which the same run makes no network
calls at all.

Usage:
    python scripts/preview_route.py                 # route_a
    python scripts/preview_route.py --route route_b
    python scripts/preview_route.py --all           # pre-cache everything
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.services import fortyguard as fg  # noqa: E402
from backend.services import osm, routing, segmentation  # noqa: E402

DIM, BOLD, GREEN, YELLOW, OFF = "\033[2m", "\033[1m", "\033[32m", "\033[33m", "\033[0m"


def load_route(route_id: str) -> dict:
    routes = json.loads(config.DEMO_ROUTES_PATH.read_text())["routes"]
    for r in routes:
        if r["id"] == route_id:
            return r
    raise SystemExit(f"unknown route {route_id}; have {[r['id'] for r in routes]}")


def run(route_id: str) -> int:
    meta = load_route(route_id)
    origin = (meta["origin"]["lon"], meta["origin"]["lat"])
    dest = (meta["destination"]["lon"], meta["destination"]["lat"])

    print(f"\n{BOLD}{meta['name']}{OFF}")
    print(f"{DIM}{meta['origin_name']} -> {meta['destination_name']}{OFF}\n")

    # 1. route
    route = routing.get_route(origin, dest)
    print(f"  route     {route['distance_m']:.0f} m, {route['duration_s']/60:.1f} min, "
          f"{len(route['coordinates'])} points  "
          f"{DIM}[{route['provider']}, cache_hit={route['cache_hit']}]{OFF}")

    # 2. segments
    segs = segmentation.segment_route(route["coordinates"], route_id=route_id)
    print(f"  segments  {len(segs)} x {segs[0]['length_m']:.1f} m")

    # 3. heat
    grid = fg.get_heat_grid_for_route(route["coordinates"])
    segs = segmentation.sample_heat_onto_segments(segs, grid["grid"])
    print(f"  heat      {grid['tile_count']} tiles, layer={grid['layer']}, "
          f"units={grid['units']}  {DIM}[cache_hit={grid['cache_hit']}]{OFF}")

    # 4. context
    features = osm.fetch_route_features(route["coordinates"])
    segs = segmentation.attach_context(segs, features)
    print(f"  context   {len(features)} OSM features")

    s = segmentation.summarise(segs)
    spread = s.get("heat_spread", 0)
    flag = GREEN if spread >= 3 else YELLOW
    print(f"\n  {BOLD}within-route heat spread: {flag}{spread} "
          f"{grid['units']}{OFF}  ({s['heat_min']} - {s['heat_max']})")
    if spread < 3:
        print(f"  {YELLOW}small spread — HEI will be amplifying a narrow range; "
              f"report it beside the ranking{OFF}")

    print(f"\n  {'seg':<4} {'heat':>7}  {'tree':>4} {'shel':>4} {'bldg':>4} "
          f"{'surface':<10} {'water':>6}  amenities")
    print("  " + "-" * 82)
    for sg in segs:
        c = sg["context"]
        am = ", ".join(f"{a['type']}@{a['distance_m']:.0f}m"
                       for a in c["nearby_amenities"][:2]) or "-"
        water = f"{c['water_within_m']:.0f}m" if c["water_within_m"] else "-"
        print(f"  {sg['index']:<4} {sg['heat_value']:7.2f}  "
              f"{c['canopy']['tree_count']:>4} {'yes' if c['shelter'] else '-':>4} "
              f"{c['building_count']:>4} {(c['surface'] or '-'):<10} {water:>6}  {am}")

    tiles_far = [s for s in segs if s["heat_tile_distance_m"] > 60]
    if tiles_far:
        print(f"\n  {YELLOW}{len(tiles_far)} segments are >60 m from their heat tile{OFF}")

    no_surface = sum(1 for s in segs if s["context"]["surface"] is None)
    print(f"\n  {DIM}segments with no OSM surface tag: {no_surface}/{len(segs)} "
          f"— missing data is not 'bare asphalt' (METHODOLOGY 5.4){OFF}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="route_a")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.all:
        ids = [r["id"] for r in json.loads(config.DEMO_ROUTES_PATH.read_text())["routes"]]
        for rid in ids:
            run(rid)
        return 0
    return run(args.route)


if __name__ == "__main__":
    raise SystemExit(main())
