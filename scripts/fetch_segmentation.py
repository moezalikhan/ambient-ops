#!/usr/bin/env python3
"""Pre-fetch FortyGuard land-cover segmentation for every segment.

Measured on the Fresno routes, OSM has 0 trees and almost no surface tags, so
imagery-derived land cover is the only per-segment signal available for the
Surface Vulnerability Index (METHODOLOGY 2.3).

Costs ~14,400 credits per segment and runs one job at a time, so a 17-segment
route takes roughly 20 minutes. Results cache for a year — run this once.

Usage:
    python scripts/fetch_segmentation.py --all
    python scripts/fetch_segmentation.py --route route_a --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.services import fortyguard as fg  # noqa: E402
from backend.services import routing, segmentation  # noqa: E402

CREDITS_PER_CALL = 14_400


def segments_for(route_id: str):
    meta = [r for r in json.loads(config.DEMO_ROUTES_PATH.read_text())["routes"]
            if r["id"] == route_id][0]
    route = routing.get_route((meta["origin"]["lon"], meta["origin"]["lat"]),
                              (meta["destination"]["lon"], meta["destination"]["lat"]))
    return meta, segmentation.segment_route(route["coordinates"], route_id=route_id)


def run(route_id: str, dry_run: bool) -> int:
    meta, segs = segments_for(route_id)
    print(f"\n{meta['name']}  —  {len(segs)} segments")

    if dry_run:
        print(f"  would cost {len(segs) * CREDITS_PER_CALL:,} credits "
              f"({len(segs)} calls). Nothing fetched.")
        return 0

    fetched = cached = 0
    for s in segs:
        mid = s["midpoint"]
        try:
            r = fg.get_surface_segmentation(mid["lat"], mid["lon"])
        except fg.FortyGuardError as e:
            print(f"  seg {s['index']:>2}  FAILED  {str(e)[:80]}")
            continue
        if r["cache_hit"]:
            cached += 1
        else:
            fetched += 1
        c = r["classes"]
        tree = c.get("tree", 0.0)
        built = c.get("building", 0.0) + c.get("road, route", 0.0)
        print(f"  seg {s['index']:>2}  tree {tree:5.2f}%  built {built:5.2f}%  "
              f"{'(cached)' if r['cache_hit'] else ''}")

    print(f"\n  fetched {fetched}, cached {cached}, "
          f"spent ~{fetched * CREDITS_PER_CALL:,} credits")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="route_a")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ids = ([r["id"] for r in json.loads(config.DEMO_ROUTES_PATH.read_text())["routes"]]
           if args.all else [args.route])
    for rid in ids:
        run(rid, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
