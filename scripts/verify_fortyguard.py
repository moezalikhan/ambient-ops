#!/usr/bin/env python3
"""Day 1 go/no-go: what does our FortyGuard key actually unlock?

Spec section 14, open question 2 — which analysis layer the key can access
cascades into the entire scoring model, so it is resolved before anything is
built on top of it. FortyGuard's own hackathon session warns that picking the
wrong layer hands you a confident wrong answer.

Answers three questions:
  1. Which analytic types work?          tcm / time_of_measure / exceedance / persistence
  2. Which candidate cities have data?   Abu Dhabi / Phoenix / Miami
  3. Is the segmentation layer reachable?  (Premium-only; decides OSM fallback)

Usage:
    python scripts/verify_fortyguard.py                 # layers, Abu Dhabi
    python scripts/verify_fortyguard.py --city all      # coverage across all three
    python scripts/verify_fortyguard.py --quick         # exceedance only
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from backend import config  # noqa: E402
from backend.services import fortyguard as fg  # noqa: E402
from backend.services.geo import buffered_bbox_polygon, polygon_area_km2  # noqa: E402

# ~1 km probe boxes at each candidate city centre.
# FortyGuard coverage is US-only (confirmed empirically: Abu Dhabi returns zero
# tiles on every layer). California is the selected region.
CITIES = {
    "fresno": (-119.7871, 36.7378),
    "bakersfield": (-119.0187, 35.3733),
    "san-bernardino": (-117.2898, 34.1083),
    "riverside": (-117.3755, 33.9533),
    "sacramento": (-121.4944, 38.5816),
    "los-angeles": (-118.4456, 34.2247),  # Panorama City, San Fernando Valley
    "new-york": (-74.0100, 40.7115),      # docs example — known-good control
}

LAYERS = ["exceedance", "persistence", "tcm", "time_of_measure"]

GREEN, RED, YELLOW, DIM, BOLD, OFF = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m",
)


def probe_layer(lon: float, lat: float, layer: str, timeout_s: float) -> tuple[bool, str]:
    """Run one small heatmap job. Returns (ok, one-line summary)."""
    polygon = buffered_bbox_polygon([(lon, lat)], 500)
    try:
        result = fg.get_heat_grid(
            polygon, analytic_type=layer, use_cache=False, timeout_s=timeout_s
        )
    except fg.FortyGuardError as e:
        return False, str(e)[:160]

    vals = [g["value"] for g in result["grid"]]
    return True, (
        f"{result['tile_count']} tiles @ {result['resolution_m']}m, "
        f"range {min(vals):.1f}-{max(vals):.1f} {result['units']}"
    )


def probe_segmentation(lon: float, lat: float) -> tuple[bool, str]:
    """Is /satellite reachable? It is Premium-only, and it decides whether SVI
    comes from FortyGuard imagery or from OpenStreetMap tags (spec section 5)."""
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{config.FORTYGUARD_BASE_URL}/satellite",
                headers=fg._headers(),
                json={
                    "sat": {"latitude": lat, "longitude": lon},
                    "date_time": fg.default_date_window(),
                    "granularity": 80,
                },
            )
            body = fg._raise_for_response(resp, "satellite submit")
            activity_id = (body.get("data") or {}).get("activity_id")
            if not activity_id:
                return False, "no activity_id returned"
            result = fg.poll_status(activity_id, timeout_s=180, client=client)

        # A completed activity is not the same as a useful one. The heatmap
        # probe already burned time on exactly this confusion, so check that
        # real class coverage came back rather than trusting the status alone.
        segments = ((result.get("segmentation") or {}).get("segments")) or {}
        if not segments:
            return False, "activity completed but returned no segmentation classes"
        # Class names contain commas ("road, route"), so join on something else.
        classes = " | ".join(list(segments))
        return True, f"{len(segments)} classes: {classes}"
    except fg.FortyGuardError as e:
        return False, str(e)[:160]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="abu-dhabi", choices=[*CITIES, "all"])
    ap.add_argument("--quick", action="store_true", help="exceedance only")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--skip-segmentation", action="store_true")
    args = ap.parse_args()

    if not config.FORTYGUARD_API_KEY:
        print(f"{RED}FORTYGUARD_API_KEY is not set.{OFF}")
        print("Add it to .env (copy .env.example if you have not already).")
        return 2

    key = config.FORTYGUARD_API_KEY
    print(f"\n{BOLD}FortyGuard key verification{OFF}")
    print(f"{DIM}base url : {config.FORTYGUARD_BASE_URL}{OFF}")
    print(f"{DIM}key      : {key[:6]}…{key[-4:]} ({len(key)} chars){OFF}")
    print(f"{DIM}threshold: {config.HEAT_THRESHOLD_C}°C {config.HEAT_DIRECTION}{OFF}")
    print(f"{DIM}window   : {fg.default_date_window()}{OFF}\n")

    cities = list(CITIES) if args.city == "all" else [args.city]
    layers = ["exceedance"] if args.quick else LAYERS
    working: list[str] = []
    covered: list[str] = []

    for city in cities:
        lon, lat = CITIES[city]
        area = polygon_area_km2(buffered_bbox_polygon([(lon, lat)], 500))
        print(f"{BOLD}{city}{OFF} {DIM}({lat}, {lon}) — {area:.2f} km² probe{OFF}")
        for layer in layers:
            print(f"  {layer:<16} ", end="", flush=True)
            ok, detail = probe_layer(lon, lat, layer, args.timeout)
            print(f"{GREEN}OK{OFF}   {detail}" if ok else f"{RED}FAIL{OFF} {detail}")
            if ok:
                working.append(layer)
                covered.append(city)
        print()

    if not args.skip_segmentation:
        lon, lat = CITIES[cities[0]]
        print(f"{BOLD}segmentation layer{OFF} {DIM}(Premium-only){OFF}")
        print("  satellite        ", end="", flush=True)
        ok, detail = probe_segmentation(lon, lat)
        print(f"{GREEN}OK{OFF}   {detail}" if ok else f"{YELLOW}NO{OFF}   {detail}")
        if not ok:
            print(f"  {DIM}-> fall back to OpenStreetMap for SVI, and say so in "
                  f"METHODOLOGY.md{OFF}")
        print()

    print(f"{BOLD}Verdict{OFF}")
    if not working:
        print(f"  {RED}No layer worked. The key, the plan, or coverage is the problem.{OFF}")
        print("  Do not build the scoring model until this resolves.")
        return 1

    order = [x for x in ("exceedance", "persistence") if x in working]
    if order:
        chosen = order[0]
        print(f"  {GREEN}Use analytic_type='{chosen}'{OFF} for HEI.")
        print(f"  {DIM}Set FORTYGUARD_ANALYTIC_TYPE={chosen} in .env{OFF}")
    else:
        print(f"  {YELLOW}Only snapshot-style layers work "
              f"({', '.join(sorted(set(working)))}).{OFF}")
        print("  A snapshot is weather, not reliable danger. If this is final, the")
        print("  methodology must state the limitation prominently.")

    if args.city == "all":
        good = sorted(set(covered))
        print(f"  {DIM}Cities with data: {', '.join(good) if good else 'none'}{OFF}")
        print(f"  {DIM}-> Minqi picks the city from this list.{OFF}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
