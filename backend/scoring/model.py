"""The Heat Priority Score.

**Owner: Minqi** (spec section 12). This file is the frozen interface plus a
defensible reference implementation. Every threshold marked TUNABLE is a
judgement call that belongs to the methodology, not to the code.

    HPS = 100 * (w1*HEI + w2*DTF + w3*SVI + w4*PSI)

Three deviations from spec section 6, all forced by what the data turned out
to be (METHODOLOGY 2.3). They are deviations, not silent fixes:

1. **Normalisation handles a constant factor explicitly.** Route B's heat grid
   returns the same value on every tile, so min-max would divide by zero. A
   constant factor carries no ranking information, so it resolves to a neutral
   0.5 for every segment and is flagged `degenerate` — which the interface
   reports rather than hides.

2. **DTF is the continuous exposed run, not the segment length.** Segments are
   equal length by construction, so "length / 1.3 m/s" is identical for every
   one of them and ranks nothing. The spec's stated intent — "longer unbroken
   exposure is worse than the same temperature crossed quickly" — is preserved
   by measuring the unbroken exposed stretch a segment belongs to.

3. **SVI is computed from imagery, not OSM tags.** OSM has 0 trees and almost
   no surface tags on these routes; FortyGuard's satellite layer gives 0-15%
   tree cover that varies per segment. Spec section 5 prefers imagery anyway.
"""

from typing import Any

from backend import config

# Value assigned to every segment when a factor does not vary. Neutral: it
# shifts all scores equally and so changes no ranking.
DEGENERATE_VALUE = 0.5

# TUNABLE — a segment counts as "exposed" for DTF purposes above this SVI.
EXPOSED_SVI_THRESHOLD = 0.6

WALKING_SPEED_MPS = config.WALKING_SPEED_MPS

# TUNABLE — satellite land-cover thresholds for the spec's SVI table.
# Class names are the API's own labels, kept verbatim so the mapping is
# auditable against the raw response.
TREE = "tree"
GRASS = "grass"
BUILDING = "building"
ROAD = "road, route"
PAVEMENT = "sidewalk, pavement"

CANOPY_CONTINUOUS_PCT = 25.0   # "continuous tree canopy"
CANOPY_SCATTERED_PCT = 8.0     # "paved with scattered trees"
GREEN_ADJACENT_PCT = 40.0      # "adjacent to water or park"
BUILDING_SHADE_PCT = 60.0      # "some adjacent building shade"


def normalise(values: list[float]) -> tuple[list[float], bool]:
    """Min-max onto 0-1. Returns (values, degenerate).

    `degenerate` is True when every input is identical — the factor cannot
    rank anything, and saying so is the whole point of returning the flag.
    """
    if not values:
        return [], True
    lo, hi = min(values), max(values)
    if hi - lo == 0:
        return [DEGENERATE_VALUE] * len(values), True
    return [(v - lo) / (hi - lo) for v in values], False


# --- SVI ------------------------------------------------------------------

def svi_from_landcover(classes: dict[str, float], shelter: bool = False) -> float:
    """Surface Vulnerability Index, 0 (benign) to 1 (worst), from imagery.

    Continuous rather than the spec's five-row table. The table would collapse
    0-15% measured tree cover into two or three buckets, discarding the only
    factor that varies within these routes. `svi_table` below implements the
    spec's discrete version for comparison; the methodology should state which
    one produced the published ranking.
    """
    tree = classes.get(TREE, 0.0)
    grass = classes.get(GRASS, 0.0)
    building = classes.get(BUILDING, 0.0)
    paved = classes.get(ROAD, 0.0) + classes.get(PAVEMENT, 0.0)

    # Vegetation cools; canopy counts for more than grass because it shades
    # the pedestrian rather than just the ground. TUNABLE weighting.
    green = (tree * 1.0 + grass * 0.4) / 100.0
    hard = (paved + building * 0.5) / 100.0

    svi = max(0.0, min(1.0, 0.5 + hard * 0.5 - green * 2.0))
    if shelter:
        svi = max(0.0, svi - 0.15)  # TUNABLE — built shade at this point
    return round(svi, 4)


def svi_table(classes: dict[str, float], context: dict[str, Any]) -> float:
    """The spec's five-row SVI lookup, driven by satellite percentages.

    Kept so the published model can be compared against the specification as
    written.
    """
    tree = classes.get(TREE, 0.0)
    green = tree + classes.get(GRASS, 0.0)
    building = classes.get(BUILDING, 0.0)

    if context.get("water_adjacent") or green >= GREEN_ADJACENT_PCT:
        return 0.1
    if tree >= CANOPY_CONTINUOUS_PCT:
        return 0.2
    if tree >= CANOPY_SCATTERED_PCT:
        return 0.5
    if building >= BUILDING_SHADE_PCT or context.get("shelter"):
        return 0.7
    return 1.0


# --- PSI ------------------------------------------------------------------

def psi_from_context(context: dict[str, Any]) -> float:
    """Population Sensitivity Index, straight from spec section 6.

    A proxy. There is no pedestrian count data, so this stands in for "who is
    exposed here" using what is nearby. Stated in METHODOLOGY 5.5 rather than
    left for a judge to discover.
    """
    if context.get("nearby_amenities"):
        return 1.0
    if context.get("transit_within_100m"):
        return 0.7
    return 0.4


# --- DTF ------------------------------------------------------------------

def exposed_runs(svi_values: list[float], lengths: list[float]) -> list[float]:
    """For each segment, the length of the unbroken exposed stretch it is in.

    A segment that is one of eight consecutive unshaded segments carries the
    whole run's length; a shaded segment carries only its own. This is what
    makes DTF mean "how long am I stuck in the sun", which is the spec's
    stated intent and is not what per-segment length measures.
    """
    n = len(svi_values)
    out = [0.0] * n
    i = 0
    while i < n:
        if svi_values[i] >= EXPOSED_SVI_THRESHOLD:
            j = i
            while j < n and svi_values[j] >= EXPOSED_SVI_THRESHOLD:
                j += 1
            run_length = sum(lengths[i:j])
            for k in range(i, j):
                out[k] = run_length
            i = j
        else:
            out[i] = lengths[i]
            i += 1
    return out


# --- the score ------------------------------------------------------------

def score_segments(
    segments: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
    use_svi_table: bool = False,
) -> dict[str, Any]:
    """Score and rank a route's segments.

    Each input segment needs `heat_value`, `length_m`, `context`, and
    `landcover` (the `classes` dict from the satellite layer; may be absent,
    in which case SVI falls back to OSM-derived context).

    Returns {segments: [...], degenerate_factors: [...], weights, spread}.
    The degenerate list is not diagnostics — it is a finding, and the UI and
    the methodology are both expected to surface it.
    """
    if not segments:
        raise ValueError("no segments to score")

    w = dict(config.DEFAULT_WEIGHTS if weights is None else weights)
    total = sum(w.values())
    if total <= 0:
        raise ValueError("weights must sum to more than zero")
    w = {k: v / total for k, v in w.items()}

    lengths = [s["length_m"] for s in segments]
    contexts = [s.get("context") or {} for s in segments]

    raw_hei = [s["heat_value"] for s in segments]
    raw_svi = []
    for s, ctx in zip(segments, contexts, strict=True):
        classes = (s.get("landcover") or {})
        if classes:
            raw_svi.append(
                svi_table(classes, ctx) if use_svi_table
                else svi_from_landcover(classes, shelter=bool(ctx.get("shelter")))
            )
        else:
            # No imagery for this segment: fall back to the OSM signal, which
            # on these routes is close to empty. Flagged by the caller via the
            # degenerate list if it turns out constant.
            trees = (ctx.get("canopy") or {}).get("tree_count", 0)
            raw_svi.append(0.5 if trees else 1.0)

    raw_dtf = [r / WALKING_SPEED_MPS for r in exposed_runs(raw_svi, lengths)]
    raw_psi = [psi_from_context(c) for c in contexts]

    hei, hei_deg = normalise(raw_hei)
    dtf, dtf_deg = normalise(raw_dtf)
    # SVI and PSI are already absolute 0-1 scales with a defined meaning, so
    # they are NOT renormalised — doing so would stretch a genuinely mild
    # route to look as bad as a genuinely severe one.
    svi, psi = raw_svi, raw_psi
    svi_deg = len(set(svi)) == 1
    psi_deg = len(set(psi)) == 1

    scored = []
    for i, s in enumerate(segments):
        hps = 100.0 * (w["HEI"] * hei[i] + w["DTF"] * dtf[i]
                       + w["SVI"] * svi[i] + w["PSI"] * psi[i])
        scored.append({
            **s,
            "HEI": round(hei[i], 4),
            "DTF": round(dtf[i], 4),
            "SVI": round(svi[i], 4),
            "PSI": round(psi[i], 4),
            "HPS": round(hps, 2),
            "raw": {
                "heat": raw_hei[i],
                "exposed_run_m": round(raw_dtf[i] * WALKING_SPEED_MPS, 1),
                "dwell_s": round(raw_dtf[i], 1),
            },
        })

    for rank, s in enumerate(sorted(scored, key=lambda x: -x["HPS"]), start=1):
        s["rank"] = rank

    degenerate = [name for name, flag in
                  (("HEI", hei_deg), ("DTF", dtf_deg), ("SVI", svi_deg), ("PSI", psi_deg))
                  if flag]

    return {
        "segments": scored,
        "weights": w,
        "degenerate_factors": degenerate,
        "heat_spread": round(max(raw_hei) - min(raw_hei), 4),
        "hps_spread": round(max(s["HPS"] for s in scored)
                            - min(s["HPS"] for s in scored), 2),
        "svi_source": "satellite" if any(s.get("landcover") for s in segments) else "osm",
    }
