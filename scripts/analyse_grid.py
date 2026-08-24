#!/usr/bin/env python3
"""Does this heat grid carry enough variation to rank anything?

HEI normalises within the route, so a ranking is always produced — even from a
grid that is effectively uniform. That is the failure mode this script exists to
catch: min-max normalisation of a tiny spread manufactures confident-looking
precision out of noise.

Usage:
    python scripts/analyse_grid.py /tmp/fg_fresno_16h.json --layer tcm
    python scripts/analyse_grid.py /tmp/fg_exc.json --layer exceedance
"""

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import fortyguard as fg  # noqa: E402

# Below this within-route spread, treat any ranking as unsupported. Degrees for
# tcm, hours for the accumulating layers. Judgement calls, stated openly rather
# than buried: they are the point at which we would not defend the ranking.
USABLE_SPREAD = {"tcm": 1.0, "exceedance": 3.0, "persistence": 3.0, "time_of_measure": 2.0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--layer", default="tcm")
    ap.add_argument("--segments", type=int, default=12,
                    help="segments a real route would have, for the sampling estimate")
    args = ap.parse_args()

    result = json.loads(Path(args.path).read_text())
    grid = fg._flatten_grid(result.get("map_data") or {}, args.layer)
    if not grid:
        print("no tiles parsed")
        return 1

    vals = sorted(g["value"] for g in grid)
    spread = vals[-1] - vals[0]
    sd = st.pstdev(vals)
    unit = "°C" if args.layer == "tcm" else "hours"

    print(f"\nlayer     : {args.layer}")
    print(f"tiles     : {len(vals)}")
    print(f"range     : {vals[0]:.3f} — {vals[-1]:.3f} {unit}")
    print(f"spread    : {spread:.3f} {unit}")
    print(f"std dev   : {sd:.3f}")
    print(f"median    : {st.median(vals):.3f}")

    if len(vals) >= 10:
        qs = st.quantiles(vals, n=10)
        print("deciles   : " + " ".join(f"{q:.2f}" for q in qs))

    # How much of the spread is one small tail? If the grid is uniform except
    # for a park, most segments still cannot be told apart.
    p10, p90 = vals[len(vals) // 10], vals[-len(vals) // 10]
    print(f"p10—p90   : {p90 - p10:.3f} {unit}  "
          f"({100 * (p90 - p10) / spread:.0f}% of full spread)" if spread else "")

    # A route samples a handful of tiles, not the whole AOI, so its spread is
    # a fraction of what the AOI shows. Rough estimate from the central mass.
    print(f"\nA {args.segments}-segment route sampling the central 80% would see")
    print(f"roughly {p90 - p10:.3f} {unit} of spread, before normalisation.")

    threshold = USABLE_SPREAD.get(args.layer, 1.0)
    print(f"\nusable-spread bar for {args.layer}: {threshold} {unit}")
    if spread >= threshold:
        print("VERDICT: enough variation — HEI can rank segments on its own.")
    elif spread >= threshold / 3:
        print("VERDICT: MARGINAL. A ranking will be produced, but state the raw")
        print("         spread next to it and do not let HEI dominate the weights.")
    else:
        print("VERDICT: TOO FLAT. HEI cannot distinguish segments here. Ranking")
        print("         must come from DTF/SVI/PSI, and the write-up must say so.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
