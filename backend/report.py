"""The evidence report behind a ranking.

A ranked list is a claim. This is the working behind it: every factor value,
every raw measurement, the weights used, which factors carried no information,
how much the ranking depends on the weights at all, and what each simulated
intervention assumes.

The sensitivity section is the part that matters most. HPS normalises within
the route, so a ranking is always produced — even from factors that barely
vary. Reporting how far the ranking moves when a weight is changed is what
tells a reader whether the order is a finding or an artefact of four numbers
someone picked.
"""

from datetime import UTC, datetime
from typing import Any

from backend import config
from backend.scoring import interventions as iv
from backend.scoring import model
from backend.scoring import simulate as sim

FACTORS = ("HEI", "DTF", "SVI", "PSI")

FACTOR_MEANINGS = {
    "HEI": "Heat Exposure Index — normalised count of hours above the "
           "temperature threshold over the analysis window. Accumulated "
           "exposure, not a surface temperature.",
    "DTF": "Dwell Time Factor — length of the unbroken unshaded run this "
           "segment belongs to, divided by walking speed. Not the segment's "
           "own length, which is constant by construction.",
    "SVI": "Surface Vulnerability Index — derived from satellite land-cover "
           "percentages: canopy, grass, paving, buildings.",
    "PSI": "Population Sensitivity Index — proximity to schools, clinics and "
           "transit. A proxy for who is exposed; no pedestrian count data "
           "exists.",
}

# Ranks moving less than this on average are treated as stable under a
# weighting change. A judgement call, stated rather than hidden.
STABLE_MEAN_RANK_CHANGE = 1.0


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def sensitivity(segments: list[dict[str, Any]],
                weights: dict[str, float]) -> dict[str, Any]:
    """How much does the ranking depend on the weights?

    Each factor is zeroed and doubled in turn, and the resulting ranking is
    compared against the baseline. A ranking that survives all eight
    perturbations is being driven by the data; one whose top segment changes
    under a single tweak is being driven by the weighting.
    """
    base = model.score_segments(segments, weights=weights)
    base_ranks = {s["id"]: s["rank"] for s in base["segments"]}
    ordered = sorted(base["segments"], key=lambda s: s["rank"])
    base_top = ordered[0]

    margin = (round(ordered[0]["HPS"] - ordered[1]["HPS"], 2)
              if len(ordered) > 1 else None)
    near_top = sum(1 for s in ordered if ordered[0]["HPS"] - s["HPS"] <= 2.0)

    perturbations = []
    for factor in FACTORS:
        for label, multiplier in (("zeroed", 0.0), ("doubled", 2.0)):
            w = dict(weights)
            w[factor] = weights.get(factor, 0.0) * multiplier
            if sum(w.values()) <= 0:
                continue
            alt = model.score_segments(segments, weights=w)
            alt_ranks = {s["id"]: s["rank"] for s in alt["segments"]}
            alt_top = min(alt["segments"], key=lambda s: s["rank"])
            changes = [abs(alt_ranks[i] - base_ranks[i]) for i in base_ranks]
            perturbations.append({
                "factor": factor,
                "change": label,
                "mean_rank_change": round(_mean(changes), 2),
                "max_rank_change": max(changes) if changes else 0,
                "top_segment": alt_top["id"],
                "top_segment_changed": alt_top["id"] != base_top["id"],
            })

    flips = [p for p in perturbations if p["top_segment_changed"]]
    worst = max((p["mean_rank_change"] for p in perturbations), default=0.0)

    return {
        "baseline_top_segment": base_top["id"],
        "baseline_top_HPS": base_top["HPS"],
        "margin_to_second": margin,
        "segments_within_2_HPS_of_top": near_top,
        "perturbations": perturbations,
        "top_segment_flips": len(flips),
        "flipped_by": [f"{p['factor']} {p['change']}" for p in flips],
        "worst_mean_rank_change": round(worst, 2),
        "verdict": _sensitivity_verdict(flips, worst, margin, near_top),
    }


def _sensitivity_verdict(flips, worst, margin, near_top) -> str:
    if not flips and worst <= STABLE_MEAN_RANK_CHANGE:
        return ("Stable. The top-ranked segment survives zeroing or doubling "
                "any single factor, and ranks move less than one place on "
                "average. The order reflects the data rather than the "
                "weighting.")
    if not flips:
        return (f"Top segment stable, order sensitive. No single weight change "
                f"unseats the leader, but ranks move up to "
                f"{worst:.1f} places on average — treat positions below the "
                f"top few as indicative.")
    if margin is not None and margin < 1.0:
        return (f"Fragile. The top two segments differ by {margin} HPS and the "
                f"leader changes under {len(flips)} of the weight "
                f"perturbations. Present the top group, not a single winner.")
    causes = ", ".join(f"{p['factor']} {p['change']}" for p in flips)
    return (f"Weight-dependent. The leading segment changes when {causes}. "
            f"The ranking reflects the weighting as much as the measurements, "
            f"which is why the weights are exposed as sliders rather than "
            f"fixed.")


def _fmt(v, nd=1):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "unknown"


def _why_this_segment(seg: dict[str, Any]) -> list[str]:
    """The measurements that put this segment first, in plain words.

    Read off the segment rather than argued: a planner asked to spend money
    here is entitled to see the numbers that chose it.
    """
    raw = seg.get("raw") or {}
    lc = seg.get("landcover") or {}
    ctx = seg.get("context") or {}
    out = [
        f"Heat exposure: {_fmt(raw.get('heat'))} hours above the threshold "
        f"accumulated over the analysis window.",
        f"Unbroken unshaded run: {_fmt(raw.get('exposed_run_m'), 0)} m, about "
        f"{_fmt((raw.get('dwell_s') or 0) / 60)} minutes of walking at 1.3 m/s.",
        f"Surface: {_fmt(lc.get('tree'))}% canopy, "
        f"{_fmt(lc.get('road, route', 0.0) + lc.get('sidewalk, pavement', 0.0))}% "
        f"paving, {_fmt(lc.get('building'))}% buildings.",
    ]
    if ctx.get("transit_within_100m"):
        out.append("A transit stop lies within 100 m"
                   + ("; it is sheltered." if ctx.get("shelter")
                      else ", and it is unsheltered."))
    amenities = ctx.get("nearby_amenities") or []
    if amenities:
        out.append("Nearby: " + ", ".join(
            f"{a.get('type')} at {a.get('distance_m')} m" for a in amenities[:3])
            + ".")
    water = ctx.get("water_within_m")
    out.append(f"Nearest drinking water: {_fmt(water, 0)} m."
               if water is not None else
               "No drinking water tagged within the search radius.")
    return out


def _recommendation(scored: list[dict[str, Any]],
                    result: dict[str, Any]) -> dict[str, Any]:
    """What to build first, and the rules that put it on the shortlist.

    The candidates are the intervention table filtered by this segment's own
    measurements — the same list the agent chose from, so a reader can check
    the choice rather than take it. No cooling figure is attached to any of
    them, because none has been sourced.
    """
    if not scored:
        return {
            "segment_id": None,
            "candidates": [],
            "note": "No segments were scored, so no intervention is proposed.",
            "agent_brief": result.get("brief"),
        }

    top = scored[0]
    candidates = [
        {k: v for k, v in c.items()
         if k in ("id", "intervention", "cost_tier", "time_to_effect",
                  "condition", "trade_off", "cooling_estimate", "source")}
        for c in iv.candidates_for(top)
    ]
    return {
        "segment_id": top.get("id"),
        "segment_index": top.get("index"),
        "rank": top.get("rank"),
        "HPS": top.get("HPS"),
        "why_this_segment": _why_this_segment(top),
        "candidates": candidates,
        "note": (
            "These are the rows of the intervention table whose conditions "
            "this segment meets. The agent selects one and justifies it in "
            "the brief below. Every cooling_estimate is null: no magnitude is "
            "claimed for any of them."
            if candidates else
            "No rule in the intervention table applies to this segment. That "
            "is reported rather than patched over — inventing an intervention "
            "outside the table would put an unsourced claim in front of a "
            "planner."
        ),
        "agent_brief": result.get("brief"),
    }


def _conclusion(scored: list[dict[str, Any]], sens: dict[str, Any] | None,
                degenerate: list[str],
                recommendation: dict[str, Any]) -> list[str]:
    """The three things a reader should leave with.

    Composed from the values above rather than written, so the conclusion
    cannot drift away from what the report actually measured.
    """
    out = []

    if scored:
        top = scored[0]
        margin = (sens or {}).get("margin_to_second")
        near = (sens or {}).get("segments_within_2_HPS_of_top") or 1
        where = (f"Act first on segment {top.get('index')} "
                 f"({top.get('id')}), which scores {top.get('HPS')} HPS across "
                 f"{len(scored)} segments.")
        if margin is not None:
            where += (f" It leads the second-placed segment by {margin} HPS"
                      + (f", and {near} segments sit within 2 HPS of it — "
                         f"treat those as one group, not a ranking."
                         if near > 1 else "."))
        out.append(where)
    else:
        out.append("No segments were scored, so this run supports no "
                   "conclusion about where to act.")

    if sens and sens.get("verdict"):
        out.append("How far to trust that order: " + sens["verdict"])

    if degenerate:
        out.append(
            f"{', '.join(degenerate)} took the same value on every segment of "
            f"this route and so contributed nothing to the ranking. The order "
            f"above is produced by the remaining factors."
        )

    cands = recommendation.get("candidates") or []
    if cands:
        out.append(
            "Shortlist for that segment: "
            + "; ".join(f"{c['intervention']} ({c['cost_tier'].lower()} cost, "
                        f"effect {c['time_to_effect'].lower()})" for c in cands)
            + ". No cooling magnitude is claimed for any of them, so choose on "
              "cost, timing and trade-off, not on a predicted degree count."
        )
    else:
        out.append(recommendation.get("note", ""))

    out.append(
        "This is decision support with a transparent model, not a prediction. "
        "There is no ground truth to validate the ranking against, and the "
        "limitations above are part of the result, not a disclaimer attached "
        "to it."
    )
    return [x for x in out if x]


def build_report(run: dict[str, Any]) -> dict[str, Any]:
    """Full evidence record for one completed run."""
    result = run.get("result") or {}
    raw_segments = run.get("segments") or []
    weights = run.get("weights") or config.DEFAULT_WEIGHTS

    by_id = {s["id"]: s for s in raw_segments}
    scored = sorted(result.get("segments") or [],
                    key=lambda s: s.get("rank", 999))

    segments = []
    for s in scored:
        src = by_id.get(s["id"], {})
        ctx = src.get("context") or {}
        segments.append({
            "id": s["id"],
            "index": s["index"],
            "rank": s["rank"],
            "HPS": s["HPS"],
            "factors": {k: s.get(k) for k in FACTORS},
            "raw": {
                "heat_hours": (s.get("raw") or {}).get("heat"),
                "exposed_run_m": (s.get("raw") or {}).get("exposed_run_m"),
                "dwell_s": (s.get("raw") or {}).get("dwell_s"),
                "length_m": src.get("length_m"),
                "heat_tile_distance_m": src.get("heat_tile_distance_m"),
            },
            "land_cover_percent": src.get("landcover"),
            "context": {
                "surface": ctx.get("surface"),
                "tree_count_osm": (ctx.get("canopy") or {}).get("tree_count"),
                "shelter": ctx.get("shelter"),
                "building_count": ctx.get("building_count"),
                "transit_within_100m": ctx.get("transit_within_100m"),
                "water_within_m": ctx.get("water_within_m"),
                "nearby_amenities": ctx.get("nearby_amenities"),
            },
            "midpoint": src.get("midpoint"),
        })

    degenerate = result.get("degenerate_factors") or []
    sens = sensitivity(raw_segments, weights) if raw_segments else None
    recommendation = _recommendation(scored, result)

    return {
        "report": "Ambient Ops — evidence record",
        "generated_at": datetime.now(UTC).isoformat(),
        "run": {
            "run_id": run["run_id"],
            "status": run["status"],
            "route_id": run["route_id"],
            "model": run["model"],
            "tool_calls": len(run.get("trace") or []),
            "elapsed_s": (round(run["finished_at"] - run["started_at"], 2)
                          if run.get("finished_at") else None),
        },
        "route": result.get("route"),
        "scoring": {
            "formula": "HPS = 100 * (w_HEI*HEI + w_DTF*DTF + w_SVI*SVI + w_PSI*PSI)",
            "weights_used": weights,
            "weights_note": "Renormalised to sum to 1; only relative size matters.",
            "factor_meanings": FACTOR_MEANINGS,
            "hps_spread": result.get("hps_spread"),
            "heat_spread": result.get("heat_spread"),
            "svi_source": result.get("svi_source"),
        },
        "degenerate_factors": {
            "factors": degenerate,
            "meaning": (
                "These factors take the same value on every segment of this "
                "route, so they carry no ranking information. They resolve to "
                "a neutral 0.5 and shift all scores equally. A ranking is "
                "still produced; it is produced by the other factors."
                if degenerate else
                "None. Every factor varies across this route."
            ),
        },
        "data_provenance": {
            "heat": {
                "source": "FortyGuard /v1/heatmap",
                "layer": (result.get("heat_layer") or {}).get("layer"),
                "units": (result.get("heat_layer") or {}).get("units"),
                "threshold_c": (result.get("heat_layer") or {}).get("threshold_c"),
                "window_days": config.HEAT_WINDOW_DAYS,
                "granularity_m": config.FORTYGUARD_GRANULARITY_M,
                "note": "Coverage is US-only. Values are hours above the "
                        "threshold accumulated over the window.",
            },
            "land_cover": {
                "source": "FortyGuard /v1/satellite",
                "note": "One point sample at each segment midpoint, not a "
                        "polygon average — the endpoint takes a point.",
            },
            "route": {"source": "OpenRouteService, foot-walking profile"},
            "context": {
                "source": "OpenStreetMap via Overpass",
                "note": "Volunteer-tagged; completeness varies. On these "
                        "routes OSM reports no trees and almost no surface "
                        "tags, which is why SVI uses imagery instead.",
            },
        },
        "sensitivity": sens,
        "recommendation": recommendation,
        "segments": segments,
        "intervention_assumptions": [
            {
                "id": k,
                "label": v["label"],
                "assumption": v["assumption"],
                "magnitude_sourced": v["sourced"],
                "caveat": v["caveat"],
            }
            for k, v in sim.EFFECTS.items()
        ],
        "cooling_estimates": {
            "stated": False,
            "note": "No cooling figure appears anywhere in this system. Every "
                    "cooling_estimate is null pending sourced literature, and "
                    "a test fails if a figure is added without a citation "
                    "beside it. Simulated magnitudes are labelled assumptions.",
        },
        "limitations": [
            "Population sensitivity uses amenity proximity, not pedestrian "
            "counts. Real deployment would require footfall data.",
            "No ground truth exists to validate the ranking against. This is "
            "decision support with a transparent model, not a prediction.",
            "Heat varies at neighbourhood scale, not street scale: across a "
            "4 km2 transect the spread is 22.2 hours, across an 800 m route "
            "between 0.63 and 0.00.",
            "Land cover is a single point sample per segment.",
            "Two routes in one city is a demonstration, not evidence of "
            "generalisation.",
            "The weights are a starting position, not an empirically derived "
            "optimum. The sensitivity section above quantifies how much that "
            "matters for this route.",
        ],
        "conclusion": _conclusion(scored, sens, degenerate, recommendation),
        "agent_trace": run.get("trace") or [],
    }
