"""What-if: apply an intervention to a segment and re-score the route.

Spec section 8 calls this the differentiator — most entries stop at a ranked
heat map; this lets a planner ask what happens if they act.

**The honest part.** Simulating an intervention means changing something the
model reads. Some of those changes are definitional and need no citation: a
shade sail makes a segment sheltered, because that is what a shade sail is.
Others are quantities — how much canopy a tree planting eventually delivers —
and those are assumptions, not findings.

So every effect below carries `sourced`, and every one of them is currently
False. The API returns those flags alongside the numbers, and the interface is
expected to show them. An unsourced magnitude presented as a result is the
failure spec section 6 warns about; an unsourced magnitude presented as a
labelled assumption is a legitimate what-if.
"""

from copy import deepcopy
from typing import Any

from backend.scoring import model

# TUNABLE and UNSOURCED. Ameera's literature review replaces these values and
# fills in `source`; until then they are illustrative and labelled as such.
EFFECTS: dict[str, dict[str, Any]] = {
    "street_trees": {
        "label": "Street tree planting",
        "sets": {"tree_pct": 20.0},
        "assumption": "Mature canopy reaches roughly 20% cover at this scale.",
        "sourced": False,
        "caveat": "Delivers nothing for about a decade — the score change is "
                  "the eventual state, not next summer.",
    },
    "shade_sail": {
        "label": "Awning or shade sail",
        "sets": {"shelter": True},
        "assumption": "The segment becomes sheltered at the point of installation.",
        "sourced": True,   # definitional, not an empirical magnitude
        "caveat": "Covers a few metres, not the whole segment.",
    },
    "shaded_shelter": {
        "label": "Shaded shelter with seating",
        "sets": {"shelter": True},
        "assumption": "The waiting area becomes sheltered.",
        "sourced": True,
        "caveat": "Helps people waiting, not people walking through.",
    },
    "shaded_corridor": {
        "label": "Continuous shaded corridor",
        "sets": {"shelter": True, "tree_pct": 15.0},
        "applies_to_run": True,
        "assumption": "Shade is continuous along the whole exposed run.",
        "sourced": False,
        "caveat": "Applied to every segment in the run, which is why its cost "
                  "tier is High.",
    },
    "cool_pavement": {
        "label": "Cool pavement coating",
        "sets": {"svi_delta": -0.10},
        "assumption": "A reflective coating lowers surface vulnerability by 0.10.",
        "sourced": False,
        "caveat": "Reflects heat upward; what a pedestrian feels may not "
                  "improve as much as the surface reading does.",
    },
    "drinking_water": {
        "label": "Drinking water point",
        "sets": {},
        "assumption": "No modelled effect — none of the four factors changes.",
        "sourced": True,
        "caveat": "This mitigates the consequence, not the exposure. The score "
                  "is unchanged by design, and a zero delta here is the "
                  "correct answer rather than a bug.",
    },
}


class SimulationError(RuntimeError):
    pass


def _apply(segment: dict[str, Any], sets: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(segment)
    lc = out.get("landcover")
    if "tree_pct" in sets and lc:
        # Raise canopy to the target, taking the increase off the hardest
        # surface present so the classes still sum sensibly.
        target = sets["tree_pct"]
        current = lc.get("tree", 0.0)
        if target > current:
            gain = target - current
            lc["tree"] = target
            for key in ("road, route", "sidewalk, pavement", "earth, ground", "building"):
                if gain <= 0:
                    break
                take = min(gain, lc.get(key, 0.0))
                lc[key] = lc.get(key, 0.0) - take
                gain -= take
    if sets.get("shelter"):
        out.setdefault("context", {})["shelter"] = True
    if "svi_delta" in sets:
        out["_svi_delta"] = sets["svi_delta"]
    return out


def simulate_intervention(
    segments: list[dict[str, Any]],
    segment_id: str,
    intervention_id: str,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Re-score the route with one intervention applied.

    Returns the before/after score for the target segment, the delta, and the
    full re-ranked route — plus the assumptions the change rests on.
    """
    effect = EFFECTS.get(intervention_id)
    if effect is None:
        raise SimulationError(
            f"unknown intervention {intervention_id!r}. Known: {sorted(EFFECTS)}"
        )
    if not any(s["id"] == segment_id for s in segments):
        raise SimulationError(f"unknown segment_id {segment_id!r}")

    baseline = model.score_segments(segments, weights=weights)
    before = next(s for s in baseline["segments"] if s["id"] == segment_id)

    target = next(s for s in segments if s["id"] == segment_id)
    target_index = target["index"]

    # A corridor treats the whole exposed run, not one segment. Reuse the same
    # run-detection the DTF factor uses so the two cannot disagree.
    if effect.get("applies_to_run"):
        svi_values = [s.get("SVI", 1.0) for s in baseline["segments"]]
        ordered = sorted(baseline["segments"], key=lambda s: s["index"])
        svi_values = [s["SVI"] for s in ordered]
        lengths = [s["length_m"] for s in ordered]
        runs = model.exposed_runs(svi_values, lengths)
        run_length = runs[target_index]
        affected = {s["id"] for s, r in zip(ordered, runs, strict=True)
                    if abs(r - run_length) < 1e-6 and r > s["length_m"]} or {segment_id}
    else:
        affected = {segment_id}

    modified = [
        _apply(s, effect["sets"]) if s["id"] in affected else s
        for s in segments
    ]
    after_all = model.score_segments(modified, weights=weights)
    after = next(s for s in after_all["segments"] if s["id"] == segment_id)

    return {
        "segment_id": segment_id,
        "intervention": intervention_id,
        "intervention_label": effect["label"],
        "segments_affected": sorted(affected),
        "before": {"HPS": before["HPS"], "rank": before["rank"],
                   "SVI": before["SVI"], "DTF": before["DTF"]},
        "after": {"HPS": after["HPS"], "rank": after["rank"],
                  "SVI": after["SVI"], "DTF": after["DTF"]},
        "delta_HPS": round(after["HPS"] - before["HPS"], 2),
        "delta_rank": before["rank"] - after["rank"],
        "route_hps_spread_before": baseline["hps_spread"],
        "route_hps_spread_after": after_all["hps_spread"],
        "new_route_ranking": [
            {"id": s["id"], "index": s["index"], "rank": s["rank"], "HPS": s["HPS"]}
            for s in sorted(after_all["segments"], key=lambda x: x["rank"])
        ],
        "assumption": effect["assumption"],
        "assumption_sourced": effect["sourced"],
        "caveat": effect["caveat"],
        "disclaimer": (
            "Illustrative. The magnitude of this change is an assumption, not a "
            "sourced cooling estimate."
            if not effect["sourced"] else
            "The modelled change is definitional rather than an empirical "
            "cooling estimate."
        ),
    }
