#!/usr/bin/env python3
"""Dump the raw shape of a FortyGuard heatmap result.

Used to tell two very different failures apart when a job completes but yields
no tiles: the city has no coverage, or our parser is wrong about the payload.
Prints structure and a couple of samples, never the whole grid.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from backend import config  # noqa: E402
from backend.services import fortyguard as fg  # noqa: E402
from backend.services.geo import buffered_bbox_polygon  # noqa: E402

CITIES = {
    "fresno": (-119.7871, 36.7378),
    "bakersfield": (-119.0187, 35.3733),
    "san-bernardino": (-117.2898, 34.1083),
    "riverside": (-117.3755, 33.9533),
    "sacramento": (-121.4944, 38.5816),
    "los-angeles": (-118.4456, 34.2247),
    "new-york": (-74.0100, 40.7115),  # the coords used in the official docs example
}


def describe(obj, indent=0, max_depth=4):
    pad = "  " * indent
    if indent > max_depth:
        print(f"{pad}...")
        return
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:12]:
            if isinstance(v, (dict, list)):
                n = len(v)
                print(f"{pad}{k}: {type(v).__name__}({n})")
                describe(v, indent + 1, max_depth)
            else:
                s = str(v)
                print(f"{pad}{k}: {s[:80]}{'…' if len(s) > 80 else ''}")
    elif isinstance(obj, list):
        if not obj:
            print(f"{pad}[] EMPTY")
            return
        print(f"{pad}[0] of {len(obj)}:")
        describe(obj[0], indent + 1, max_depth)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="fresno", choices=list(CITIES))
    ap.add_argument("--layer", default="exceedance")
    ap.add_argument("--granularity", type=int, default=100)
    ap.add_argument("--buffer", type=float, default=500)
    ap.add_argument("--filter-type", type=int, default=None,
                    help="override date_time.filter_type (1-4)")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD")
    ap.add_argument("--time", default=None, help="HH:MM — implies filter_type 1 (single hour)")
    ap.add_argument("--end-date", default=None, help="YYYY-MM-DD — implies filter_type 4")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--center", default=None, help="lon,lat override")
    ap.add_argument("--save", default=None, help="write full raw JSON here")
    args = ap.parse_args()

    if not config.FORTYGUARD_API_KEY:
        print("FORTYGUARD_API_KEY not set")
        return 2

    if args.center:
        lon, lat = (float(x) for x in args.center.split(","))
    else:
        lon, lat = CITIES[args.city]
    polygon = buffered_bbox_polygon([(lon, lat)], args.buffer)

    date_time = fg.default_date_window()
    if args.date:
        date_time["start_date"] = args.date
    if args.time:
        date_time["start_time"] = args.time
        date_time["filter_type"] = 1
        date_time.pop("end_time", None)
    if args.end_date:
        # filter_type 4 = range of days (max 1 month); times do not apply.
        date_time["filter_type"] = 4
        date_time["end_date"] = args.end_date
        date_time.pop("start_time", None)
        date_time.pop("end_time", None)
    if args.filter_type:
        date_time["filter_type"] = args.filter_type
        if args.filter_type == 3:
            date_time.pop("start_time", None)
            date_time.pop("end_time", None)

    payload = fg.build_payload(
        polygon, date_time=date_time,
        granularity=args.granularity, analytic_type=args.layer,
        threshold=args.threshold,
    )
    print(f"\n=== REQUEST ({args.city}, {args.layer}) ===")
    print(json.dumps({k: v for k, v in payload.items() if k != "polygon_aoi"}, indent=2))
    print(f"aoi ring: {payload['polygon_aoi']['features'][0]['geometry']['coordinates'][0]}")

    with httpx.Client(timeout=60.0) as client:
        activity_id = fg.submit_heatmap(payload, client=client)
        print(f"\nactivity_id: {activity_id}")
        result = fg.poll_status(
            activity_id, timeout_s=300, client=client,
            on_poll=lambda n, s: print(f"  poll {n}: {s}"),
        )

    if args.save:
        Path(args.save).write_text(json.dumps(result, indent=2))
        print(f"\nfull result -> {args.save}")

    print("\n=== RESULT STRUCTURE ===")
    describe(result)

    map_data = result.get("map_data") or {}
    feats = map_data.get("features") if isinstance(map_data, dict) else None
    print("\n=== VERDICT ===")
    if not map_data:
        print("map_data is EMPTY -> most likely no coverage for this AOI/date.")
    elif not feats:
        print(f"map_data present but no 'features' key. Top-level keys: {list(map_data)}")
    else:
        print(f"{len(feats)} features. First feature properties:")
        print(json.dumps(feats[0].get("properties", {}), indent=2)[:600])
        print(f"geometry type: {feats[0].get('geometry', {}).get('type')}")
        parsed = fg._flatten_grid(map_data, args.layer)
        print(f"our parser extracted: {len(parsed)} tiles")
        if not parsed:
            print("-> PARSER BUG: features exist but no numeric property matched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
