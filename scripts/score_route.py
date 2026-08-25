#!/usr/bin/env python3
"""Run the full pipeline and score a route.

    route -> segments -> heat -> OSM context -> land cover -> HPS ranking

Uses only cached data by default, so it costs nothing and runs in seconds.

Usage:
    python scripts/score_route.py --route route_a
    python scripts/score_route.py --all --svi-table
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.scoring import interventions, model  # noqa: E402
from backend.services import fortyguard as fg  # noqa: E402
from backend.services import osm, routing, segmentation  # noqa: E402

DIM, BOLD, YELLOW, GREEN, OFF = "\033[2m", "\033[1m", "\033[33m", "\033[32m", "\033[0m"


def run(route_id: str, use_table: bool) -> int:
    meta = [r for r in json.loads(config.DEMO_ROUTES_PATH.read_text())["routes"]
            if r["id"] == route_id][0]
    route = routing.get_route((meta["origin"]["lon"], meta["origin"]["lat"]),
                              (meta["destination"]["lon"], meta["destination"]["lat"]))
    segs = segmentation.segment_route(route["coordinates"], route_id=route_id)
    grid = fg.get_heat_grid_for_route(route["coordinates"])
    segs = segmentation.sample_heat_onto_segments(segs, grid["grid"])
    segs = segmentation.attach_context(segs, osm.fetch_route_features(route["coordinates"]))
    segs = segmentation.attach_landcover(segs)

    result = model.score_segments(segs, use_svi_table=use_table)
    scored = result["segments"]

    print(f"\n{BOLD}{meta['name']}{OFF}")
    print(f"{DIM}{len(scored)} segments | SVI from {result['svi_source']} | "
          f"weights {result['weights']}{OFF}")

    deg = result["degenerate_factors"]
    if deg:
        print(f"  {YELLOW}degenerate factors: {', '.join(deg)} — these contribute "
              f"nothing to the ranking{OFF}")
    print(f"  heat spread {result['heat_spread']} h | "
          f"HPS spread {result['hps_spread']}\n")

    print(f"  {'rank':<5}{'seg':<5}{'HPS':>7}  {'HEI':>5}{'DTF':>6}{'SVI':>6}{'PSI':>6}"
          f"  {'tree%':>6}{'run_m':>7}  intervention")
    print("  " + "-" * 92)
    for s in sorted(scored, key=lambda x: x["rank"]):
        cands = interventions.candidates_for(s)
        best = cands[0]["intervention"] if cands else f"{YELLOW}none match{OFF}"
        tree = (s.get("landcover") or {}).get("tree", 0.0)
        print(f"  {s['rank']:<5}{s['index']:<5}{s['HPS']:7.2f}  {s['HEI']:5.2f}"
              f"{s['DTF']:6.2f}{s['SVI']:6.2f}{s['PSI']:6.2f}  {tree:6.2f}"
              f"{s['raw']['exposed_run_m']:7.0f}  {best}")

    top = sorted(scored, key=lambda x: x["rank"])[0]
    n_no_cand = sum(1 for s in scored if not interventions.candidates_for(s))
    print(f"\n  {GREEN}top priority: segment {top['index']} (HPS {top['HPS']}){OFF}")
    if n_no_cand:
        print(f"  {DIM}{n_no_cand} segments matched no intervention row{OFF}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="route_a")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--svi-table", action="store_true",
                    help="use the spec's discrete SVI table instead of continuous")
    args = ap.parse_args()
    ids = ([r["id"] for r in json.loads(config.DEMO_ROUTES_PATH.read_text())["routes"]]
           if args.all else [args.route])
    for rid in ids:
        run(rid, args.svi_table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
