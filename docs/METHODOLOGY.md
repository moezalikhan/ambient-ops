# Ambient Ops — Methodology

> **Owner: Minqi.** Skeleton created by Moez in Step 1 so the sections are agreed
> up front. Every `TODO` below is a claim that needs a source or a decision.
> Due end of Step 8 (Aug 29) per the build plan.

---

## 1. Study area

- **City: Fresno, California.** Locked Aug 24. FortyGuard temperature coverage
  is **US-only** — Abu Dhabi returns zero tiles on every analytic layer, which
  we confirmed empirically rather than assumed. Within the US, California was
  the selected region; Fresno is the hottest large city in it, with roughly 25%
  poverty and top-percentile CalEnviroScreen tracts.
- **Routes:** two, each a transit stop to a school or clinic, 400–900 m.
  - Route A: TODO
  - Route B: TODO
- **Why these routes:** non-discretionary journeys — walked by people with the
  least ability to choose an alternative.
- **Route selection evidence:** TODO — CalEnviroScreen is a real state dataset
  identifying disadvantaged communities. Using it to justify *why these two
  routes* is stronger than picking them by eye.

## 2. Heat threshold

What temperature counts as dangerous for a pedestrian, and on whose authority.

- **Threshold:** TODO °C at 2 m above ground
- **Source:** TODO — needs a citation, not a round number
- **Rationale:** TODO

> **The threshold is not a free parameter.** HEI is derived from an exceedance
> count and then normalised *within the route*. If the threshold sits outside
> the temperature spread along the route, every tile returns the same value —
> 0 hours if it is too high, a saturated 12/12 if it is too low — and after
> normalisation HEI becomes constant. The 0.40-weighted factor then contributes
> **nothing** to the ranking while still appearing to work.
>
> This is not hypothetical: a probe over lower Manhattan at the API's default
> 30 °C returned `min 0.0, max 0.0, mean 0.0` across all 113 tiles.
>
> So the threshold must satisfy two constraints at once: defensible in the
> literature, **and** inside the observed spread for the route. Where those
> conflict, say so here rather than quietly moving the number.

### 2.1 Measured spatial variation in Fresno

Probes run Aug 24 against the live API, `tcm` layer, 60 m granularity:

| AOI | Window | Tiles | Spread | Std dev |
|---|---|---|---|---|
| 1 km², downtown | 06:00–18:00 mean | 168 | 0.076 °C | 0.021 |
| 4 km², park to urban core | 16:00 single hour | 1024 | 0.380 °C | 0.080 |

Two things follow, and both need stating in the final write-up.

**Averaging destroys the signal.** A 12-hour mean flattens spatial variation to
under a tenth of a degree. The urban heat island is a peak-hours phenomenon, so
any window that averages across the whole day averages the effect away.

**Absolute spatial variation is small even at peak.** 0.38 °C across a 4 km²
transect that deliberately spanned parkland and dense urban fabric. HEI
normalises *within the route*, which rescales whatever spread exists onto 0–1 —
so a ranking will always be produced. The honest question is whether that
ranking carries information or amplifies model noise. **If the within-route
spread is small relative to the model's own uncertainty, min-max normalisation
manufactures false precision.** State the observed within-route spread in this
document alongside the ranking, so a reader can judge that for themselves.

TODO — obtain FortyGuard's stated model uncertainty, if published. Without it,
the amplification concern cannot be quantified and should be named as an
open limitation rather than glossed.

### 2.2 Why the window is 30 days, not one day

This is the most consequential implementation decision in the project, so the
evidence for it is recorded in full.

The problem: a threshold defensible in the literature (35 °C) is exceeded by
every tile in Fresno for most of every summer afternoon. At any single hour,
that leaves nothing to rank. A threshold chosen to split the tiles at one hour
would have to sit near 39.4 °C — tuned to one AOI's distribution on one day,
and indefensible to anyone who asks where the number came from.

The resolution: **integrate over time.** A tile that runs a fraction of a
degree hotter crosses the threshold slightly earlier each afternoon, and those
crossings accumulate.

| Window | Layer | Spread across AOI | Spread across a typical route |
|---|---|---|---|
| Single hour, 16:00 | `tcm` | 0.380 °C | 0.181 °C |
| 30 days | `exceedance` @ 35 °C | **22.18 hours** | **10.51 hours** |

Measured Aug 24 over the same 4 km² Fresno transect, 1024 tiles at 60 m.

The 30-day exceedance spread is roughly 4.8× its own standard deviation
(4.64 h), so it separates segments rather than amplifying noise. And 35 °C was
**not** fitted to the data — it is a defensible threshold that happens to
discriminate once integrated. Both constraints from section 2 are satisfied
simultaneously, which at a single hour they could not be.

Nights need no special handling: they never approach 35 °C, contribute zero to
the count, and the result is effectively an accumulation over daylight hours —
which is the HEI definition in the spec.

**Consequence for interpretation.** HEI is therefore *not* "how hot was it
here" but "how many hours of dangerous heat accumulated here over a month".
That is the stronger claim for justifying public spending, and it is the claim
the write-up should make.

TODO — Minqi: confirm 35 °C against the pedestrian-heat literature. If the
sourced threshold differs, re-run `scripts/analyse_grid.py` at that value and
record here whether it still discriminates. If it does not, that conflict is a
finding to report, not a number to quietly adjust.

## 3. Data sources

| Source | Used for | Layer / query | Notes |
|---|---|---|---|
| FortyGuard `/v1/heatmap` | HEI | `analytic_type=exceedance` | Verified accessible Aug 24. US-only coverage |
| FortyGuard `/v1/satellite` | SVI | Segmentation class coverage | Premium endpoint, reachable on the Hackathon key — TODO confirm it returns real classes |
| OpenRouteService | Route geometry | Pedestrian profile | |
| OpenStreetMap (Overpass) | SVI, PSI context | 25 m radius per segment | Volunteer-tagged; completeness varies |

**Verified API contract** (docs-api.fortyguard.com, v1.0.0, checked Aug 24):
auth is an `api-key` request header; jobs are asynchronous — `POST /v1/heatmap`
returns an `activity_id`, then `GET /v1/status/{activity_id}` is polled until
`Completed`. The layer parameter is `analytic_type`, with `threshold` (°C) and
`direction` (`above`/`below`) applying only to `exceedance` and `persistence`.
Granularity is 60, 80, or 100 m. Plan: Hackathon tier, 2,000,000 credits,
roughly 4,220 per heatmap job.

**On preferring FortyGuard segmentation over OSM for SVI.** The spec favours it
because it is derived from imagery rather than volunteer tagging. If it proves
usable, say so here; if not, state plainly that OSM is the fallback and that
tag completeness is a limitation.

**Why not a snapshot.** A single-timestamp reading tells you it was hot at 2pm
last Tuesday, which is weather. Exceedance (how often a location exceeds the
threshold) or persistence (how long it stays above it) tells you a location is
*reliably* dangerous — which is what justifies spending public money.

## 4. Segmentation

Routes are split into fixed 50 m segments. TODO — justify 50 m: short enough to
be actionable for a planner, long enough that the heat grid resolution supports
a distinct value per segment.

## 5. The Heat Priority Score

```
HPS = 100 * (w1*HEI + w2*DTF + w3*SVI + w4*PSI)
defaults: w1 = 0.40, w2 = 0.20, w3 = 0.20, w4 = 0.20
```

### 5.1 Weight justification

TODO — one paragraph per weight. Why is HEI worth double the others?

### 5.2 HEI — Heat Exposure Index (0–1)

Normalised from the FortyGuard layer. **Normalised within the route, not
globally**, so the ranking stays meaningful in a uniformly hot city.

TODO — state the normalisation formula and what happens when all segments are
near-identical.

### 5.3 DTF — Dwell Time Factor (0–1)

`segment_length_m / 1.3 m/s`, then normalised across the route.

- **Walking speed source:** TODO — 1.3 m/s needs a citation
- Longer unbroken exposure is worse than the same temperature crossed quickly.
  This is a large part of what separates Ambient Ops from a plain heat map.

### 5.4 SVI — Surface Vulnerability Index (0–1)

| Condition | Value |
|---|---|
| Bare asphalt or concrete, no canopy, no shelter | 1.0 |
| Paved, some adjacent building shade | 0.7 |
| Paved with scattered trees | 0.5 |
| Continuous tree canopy | 0.2 |
| Adjacent to water or park | 0.1 |

TODO — define the exact OSM tag combinations that map to each row, and what
happens when tags are absent (missing data is not the same as bare asphalt).

### 5.5 PSI — Population Sensitivity Index (0–1)

| Condition | Value |
|---|---|
| Within 100 m of school, clinic, hospital, or elderly facility | 1.0 |
| Within 100 m of a transit stop | 0.7 |
| Otherwise | 0.4 |

**This is a proxy.** No pedestrian count data is available. Stated here rather
than left for a judge to discover.

## 6. Intervention rules

The agent selects from a fixed table. Its job is to choose and justify, not to
invent.

| Segment condition | Intervention | Cost tier | Time to effect | Cooling estimate | Source |
|---|---|---|---|---|---|
| Unsheltered transit stop, high HEI | Shaded shelter with seating | Medium | Immediate | TODO | TODO |
| Wide bare pavement, no adjacent planting space | Cool pavement coating | Medium | Immediate | TODO | TODO |
| Bare pavement with verge or setback | Street tree planting | Low | Years | TODO | TODO |
| Long exposed stretch, no water within 300 m | Drinking water point | Low | Immediate | n/a | n/a |
| Building-adjacent walkway, no canopy | Awning or shade sail | Low | Immediate | TODO | TODO |
| Multiple adjacent high-score segments | Continuous shaded corridor | High | Mixed | TODO | TODO |

> **Hard rule: do not fabricate cooling effect numbers.** Every figure is either
> cited or explicitly labelled illustrative. Ameera's citation list feeds this
> table; it is the input, and the table cannot be finished without it.

## 7. Simulation

`simulate_intervention` applies a proposed intervention to a segment and
re-scores the route.

TODO — state exactly which factor each intervention modifies and by how much,
and label the magnitude as literature-derived or illustrative.

## 8. Validation

TODO — there is no ground truth to validate against. Describe what was done
instead: sanity checks, hand-worked examples, cases where the ranking looked
wrong and what was found.

## 9. Limitations

- Population sensitivity uses amenity proximity, not actual pedestrian counts.
  Real deployment would require footfall data.
- No ground truth exists to validate the ranking against. This is decision
  support with a transparent model, not a prediction.
- Cooling effect estimates are published literature averages, not site-specific
  thermal modelling.
- Two routes in one city is a demonstration, not evidence of generalisation.
- The weights are a starting position, not an empirically derived optimum. They
  are exposed as sliders precisely because they are debatable.
- TODO — anything found during validation that belongs on this list.

## 10. References

TODO — Ameera's sourced list, one entry per cooling estimate and the heat
threshold.
