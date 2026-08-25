#!/usr/bin/env python3
"""Warm every cache the demo touches, then prove it is warm.

Spec section 13: async polling means dead air, so pre-run both routes and store
the results. Never rely on a live API round trip for the main demo flow.

Run this the day before judging. It fills the SQLite cache with the routes,
heat grids, OSM context, and satellite land cover for both demo routes, then
re-runs everything with the network disabled to prove nothing reaches out.

    python scripts/precache_demo.py            # warm, then verify
    python scripts/precache_demo.py --verify   # verify only, no spend
"""

import argparse
import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.cache import store  # noqa: E402
from backend.scoring import model  # noqa: E402
from backend.services import fortyguard as fg  # noqa: E402
from backend.services import osm, routing, segmentation  # noqa: E402

GREEN, RED, YELLOW, DIM, BOLD, OFF = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m")


class NetworkBlocked(RuntimeError):
    pass


def _block_network():
    """Make any socket connection raise, so a cache miss cannot hide."""
    def guard(*args, **kwargs):
        raise NetworkBlocked("network access attempted — this is a cache MISS")
    socket.socket.connect = guard  # type: ignore[method-assign]


def routes():
    return json.loads(config.DEMO_ROUTES_PATH.read_text())["routes"]


def build(route_meta, warm_satellite: bool) -> dict:
    origin = (route_meta["origin"]["lon"], route_meta["origin"]["lat"])
    dest = (route_meta["destination"]["lon"], route_meta["destination"]["lat"])

    route = routing.get_route(origin, dest)
    segs = segmentation.segment_route(route["coordinates"], route_id=route_meta["id"])
    grid = fg.get_heat_grid_for_route(route["coordinates"])
    segs = segmentation.sample_heat_onto_segments(segs, grid["grid"])
    segs = segmentation.attach_context(segs, osm.fetch_route_features(route["coordinates"]))
    segs = segmentation.attach_landcover(segs, use_cache_only=not warm_satellite)
    scored = model.score_segments(segs)

    missing_lc = sum(1 for s in segs if not s.get("landcover"))
    return {
        "segments": len(segs),
        "tiles": grid["tile_count"],
        "missing_landcover": missing_lc,
        "hps_spread": scored["hps_spread"],
        "degenerate": scored["degenerate_factors"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="skip warming; only prove the cache is complete")
    ap.add_argument("--warm-satellite", action="store_true",
                    help="also fetch missing satellite tiles (~14,400 credits each)")
    args = ap.parse_args()

    print(f"\n{BOLD}Ambient Ops — demo pre-cache{OFF}")
    print(f"{DIM}cache: {config.CACHE_DB_PATH}{OFF}\n")

    if not args.verify:
        for meta in routes():
            t0 = time.time()
            try:
                info = build(meta, args.warm_satellite)
            except Exception as e:  # noqa: BLE001 — reported, not raised
                print(f"  {RED}FAIL{OFF} {meta['id']}: {e}")
                return 1
            gap = (f"  {YELLOW}{info['missing_landcover']} segments lack land cover{OFF}"
                   if info["missing_landcover"] else "")
            print(f"  {GREEN}warm{OFF} {meta['id']:<9} {info['segments']:>2} segments, "
                  f"{info['tiles']:>3} tiles, spread {info['hps_spread']:>6.2f}  "
                  f"{DIM}{time.time() - t0:.1f}s{OFF}{gap}")

    print(f"\n{DIM}cache contents: {store.stats()}{OFF}")
    print(f"\n{BOLD}Verifying with the network blocked{OFF}")
    _block_network()

    ok = True
    for meta in routes():
        try:
            t0 = time.time()
            info = build(meta, warm_satellite=False)
            print(f"  {GREEN}OFFLINE OK{OFF} {meta['id']:<9} {info['segments']} segments, "
                  f"spread {info['hps_spread']:.2f}, "
                  f"degenerate={info['degenerate'] or 'none'}  "
                  f"{DIM}{time.time() - t0:.2f}s{OFF}")
            if info["missing_landcover"]:
                print(f"    {YELLOW}{info['missing_landcover']} segments without "
                      f"land cover — SVI falls back to OSM for those{OFF}")
        except NetworkBlocked as e:
            print(f"  {RED}CACHE MISS{OFF} {meta['id']}: {e}")
            ok = False
        except Exception as e:  # noqa: BLE001
            print(f"  {RED}FAIL{OFF} {meta['id']}: {type(e).__name__}: {e}")
            ok = False

    if ok:
        print(f"\n  {GREEN}Both routes run entirely from cache.{OFF}")
        print(f"  {DIM}The agent still calls the model over the network — only the "
              f"data pipeline is offline.{OFF}\n")
        return 0
    print(f"\n  {RED}Demo would hit the network. Re-run without --verify.{OFF}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
