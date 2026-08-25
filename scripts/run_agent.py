#!/usr/bin/env python3
"""Run the agent on a demo route and print its trace and brief.

This is the three-minute demo in text form: route selection, the agent's tool
calls in the order it chose them, the ranked output, and one intervention.

Usage:
    python scripts/run_agent.py --route route_a
    python scripts/run_agent.py --route route_b --timeout 180
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.agent import orchestrator  # noqa: E402

DIM, BOLD, GREEN, RED, YELLOW, OFF = (
    "\033[2m", "\033[1m", "\033[32m", "\033[31m", "\033[33m", "\033[0m")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="route_a")
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args()

    missing = config.missing_keys()
    if missing:
        print(f"{RED}unconfigured: {', '.join(missing)}{OFF}")
        return 2

    print(f"\n{BOLD}Ambient Ops — agent run{OFF}")
    print(f"{DIM}model {config.LLM_PROVIDER}/{config.LLM_MODEL} | route {args.route}{OFF}\n")

    started = time.time()
    run_id = orchestrator.start_run(args.route)
    seen = 0
    while time.time() - started < args.timeout:
        run = orchestrator.get_run(run_id)
        trace = run["trace"]
        while seen < len(trace):
            t = trace[seen]
            mark = f"{GREEN}OK{OFF}" if t["ok"] else f"{RED}ERR{OFF}"
            cache = f" {DIM}(cached){OFF}" if t["cache_hit"] else ""
            call_args = t.get("arguments") or {}
            argstr = ", ".join(f"{k}={v}" for k, v in call_args.items())
            print(f"  {t['seq']:>2}. {mark} {t['tool']:<24} {t['duration_ms']:>6} ms"
                  f"{cache}  {t['result_summary']}")
            if argstr:
                print(f"      {DIM}args: {argstr[:150]}{OFF}")
            seen += 1
        if run["status"] != "running":
            break
        time.sleep(0.4)

    run = orchestrator.get_run(run_id)
    elapsed = time.time() - started

    if run["status"] == "failed":
        print(f"\n{RED}FAILED{OFF} {run['error']}")
        print(f"{DIM}{run.get('traceback', '')[-600:]}{OFF}")
        return 1
    if run["status"] == "running":
        print(f"\n{YELLOW}still running after {args.timeout}s{OFF}")
        return 1

    result = run["result"] or {}
    print(f"\n{DIM}{len(run['trace'])} tool calls in {elapsed:.1f}s{OFF}")

    deg = result.get("degenerate_factors") or []
    if deg:
        print(f"{YELLOW}constant factors: {', '.join(deg)}{OFF}")

    print(f"\n{BOLD}Ranked segments{OFF}  "
          f"{DIM}(HPS spread {result.get('hps_spread')}){OFF}")
    for s in (result.get("segments") or [])[:5]:
        print(f"  {s['rank']}. {s['id']}  HPS {s['HPS']:6.2f}   "
              f"HEI {s['HEI']:.2f}  DTF {s['DTF']:.2f}  "
              f"SVI {s['SVI']:.2f}  PSI {s['PSI']:.2f}")

    print(f"\n{BOLD}Agent brief{OFF}")
    for line in (result.get("brief") or "(none)").splitlines():
        print(f"  {line}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
