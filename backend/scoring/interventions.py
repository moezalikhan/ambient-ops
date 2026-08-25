"""The intervention rules table (spec section 7).

The agent selects from this fixed set and explains its choice. It does not
invent interventions — its job is to choose and justify, not to generate.

**No cooling figures are stated here.** Every `cooling_estimate` is None until
Ameera's sourced literature fills it in, and the field carries the citation
alongside the number. Spec section 6: inventing a plausible-sounding number is
the fastest way to lose a technical judge. A None here is not an oversight; it
is the absence of a citation, and `format_for_agent` says so out loud.
"""

from collections.abc import Callable
from typing import Any

CostTier = str  # "Low" | "Medium" | "High"

# TUNABLE — what counts as "long", "wide", "bare".
#
# LOW_CANOPY_PCT is calibrated to the observed local range, not picked in the
# abstract. Measured canopy on these routes runs 0.0-15.3%, so a 5% threshold
# classified most of a near-treeless corridor as adequately treed and left
# 12 of 16 segments with no recommendation at all. At 12% the genuinely
# better-shaded segments (12.8-15.3%) are still excluded, which is the
# distinction a planner needs.
#
# Minqi: this wants a canopy-target citation. US municipal targets are
# typically far above anything measured here, and if the sourced figure says
# so then "every segment needs trees" is the finding, not a bug.
LONG_RUN_M = 150.0
HIGH_SVI = 0.65
LOW_CANOPY_PCT = 12.0
HIGH_BUILDING_PCT = 60.0
HIGH_PAVED_PCT = 25.0
WATER_RADIUS_M = 300.0


def _lc(seg: dict[str, Any]) -> dict[str, float]:
    return seg.get("landcover") or {}


def _ctx(seg: dict[str, Any]) -> dict[str, Any]:
    return seg.get("context") or {}


def _tree(seg) -> float:
    return _lc(seg).get("tree", 0.0)


def _building(seg) -> float:
    return _lc(seg).get("building", 0.0)


def _paved(seg) -> float:
    return _lc(seg).get("road, route", 0.0) + _lc(seg).get("sidewalk, pavement", 0.0)


def _green_space(seg) -> float:
    return _lc(seg).get("grass", 0.0) + _lc(seg).get("earth, ground", 0.0)


def _at_transit(seg) -> bool:
    return bool(_ctx(seg).get("transit_within_100m"))


def _sheltered(seg) -> bool:
    return bool(_ctx(seg).get("shelter"))


def _water_near(seg) -> bool:
    d = _ctx(seg).get("water_within_m")
    return d is not None and d <= WATER_RADIUS_M


def _run_m(seg) -> float:
    return (seg.get("raw") or {}).get("exposed_run_m", seg.get("length_m", 0.0))


INTERVENTIONS: list[dict[str, Any]] = [
    {
        "id": "shaded_shelter",
        "intervention": "Shaded shelter with seating",
        "cost_tier": "Medium",
        "time_to_effect": "Immediate",
        "condition": "Unsheltered transit stop with high heat exposure",
        "applies": lambda s: _at_transit(s) and not _sheltered(s) and s.get("SVI", 0) >= 0.5,
        "trade_off": "Helps only people who are waiting, not people walking through.",
        "cooling_estimate": None,
        "source": None,
    },
    {
        "id": "cool_pavement",
        "intervention": "Cool pavement coating (reflective surface)",
        "cost_tier": "Medium",
        "time_to_effect": "Immediate",
        "condition": "Wide bare pavement with no adjacent planting space",
        "applies": lambda s: (_paved(s) >= HIGH_PAVED_PCT
                              and _tree(s) < LOW_CANOPY_PCT
                              and _green_space(s) < 5.0),
        "trade_off": "Lowers surface temperature but reflects light and heat "
                     "upward, which can raise what a pedestrian actually feels.",
        "cooling_estimate": None,
        "source": None,
    },
    {
        "id": "street_trees",
        "intervention": "Street tree planting",
        "cost_tier": "Low",
        "time_to_effect": "Years",
        "condition": "Bare pavement with a verge or setback available",
        "applies": lambda s: _tree(s) < LOW_CANOPY_PCT and _green_space(s) >= 5.0,
        "trade_off": "Cheapest durable fix and the only one that improves with "
                     "time, but delivers no meaningful canopy for roughly a "
                     "decade — no help to anyone walking this route now.",
        "cooling_estimate": None,
        "source": None,
    },
    {
        "id": "drinking_water",
        "intervention": "Drinking water point",
        "cost_tier": "Low",
        "time_to_effect": "Immediate",
        "condition": "Long exposed stretch with no water within 300 m",
        "applies": lambda s: _run_m(s) >= LONG_RUN_M and not _water_near(s),
        "trade_off": "Mitigates the consequence rather than the exposure; the "
                     "segment stays exactly as hot.",
        "cooling_estimate": None,
        "source": None,
    },
    {
        "id": "shade_sail",
        "intervention": "Awning or shade sail",
        "cost_tier": "Low",
        "time_to_effect": "Immediate",
        "condition": "Building-adjacent walkway with no canopy",
        "applies": lambda s: _building(s) >= HIGH_BUILDING_PCT and _tree(s) < LOW_CANOPY_PCT,
        "trade_off": "Works immediately but covers only a few metres, so it "
                     "treats a point rather than a corridor.",
        "cooling_estimate": None,
        "source": None,
    },
    {
        "id": "shaded_corridor",
        "intervention": "Continuous shaded corridor",
        "cost_tier": "High",
        "time_to_effect": "Mixed",
        "condition": "Several adjacent high-scoring segments",
        "applies": lambda s: _run_m(s) >= LONG_RUN_M and s.get("SVI", 0) >= HIGH_SVI,
        "trade_off": "The only option that fixes an unbroken stretch rather "
                     "than a point, and the only one likely to exceed a small "
                     "capital budget.",
        "cooling_estimate": None,
        "source": None,
    },
]


def candidates_for(segment: dict[str, Any]) -> list[dict[str, Any]]:
    """Which rows of the table apply to this segment.

    Returns the table rows minus their predicates, so the result is JSON-safe
    and can be handed straight to the agent.
    """
    out = []
    for rule in INTERVENTIONS:
        applies: Callable = rule["applies"]
        try:
            if applies(segment):
                out.append({k: v for k, v in rule.items() if k != "applies"})
        except (TypeError, KeyError):
            continue
    return out


def format_for_agent(segment: dict[str, Any]) -> dict[str, Any]:
    """The choice the agent is asked to make, with its constraints attached."""
    cands = candidates_for(segment)
    return {
        "segment_id": segment.get("id"),
        "HPS": segment.get("HPS"),
        "rank": segment.get("rank"),
        "factors": {k: segment.get(k) for k in ("HEI", "DTF", "SVI", "PSI")},
        "evidence": {
            "tree_percent_of_image": _tree(segment),
            "building_percent_of_image": _building(segment),
            "paved_percent_of_image": round(_paved(segment), 2),
            "units_note": "Percentages are already in percent; 0.9 means 0.9%.",
            "exposed_run_m": _run_m(segment),
            "at_transit_stop": _at_transit(segment),
            "sheltered": _sheltered(segment),
            "water_within_m": _ctx(segment).get("water_within_m"),
            "nearby_amenities": _ctx(segment).get("nearby_amenities", []),
        },
        "candidates": cands,
        "rules": (
            "Choose exactly one intervention from `candidates`. If candidates "
            "is empty, say so rather than inventing one. Justify the choice "
            "using `evidence`, explain why this segment outranks others, and "
            "state the trade-off. Do not state any cooling figure: every "
            "cooling_estimate is null because none has been sourced yet."
        ),
    }
