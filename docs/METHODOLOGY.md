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
  Selected from OSM data rather than by eye — `scripts/find_routes.py` pairs
  real bus stops with schools and clinics and measures the walking distance
  with OpenRouteService, producing 19 candidates in band.
  - **Route A:** SW Wishon–McKinley bus stop → Heaton Elementary School,
    862 m, 17 segments.
  - **Route B:** UMC (Outpatient Services) transit stop → DBH Asian Pacific
    Islander / Latino Team clinic, 780 m, 16 segments.
- **Why these routes:** non-discretionary journeys — walked by people with the
  least ability to choose an alternative.
- **Route selection evidence:** CalEnviroScreen](https://oehha.ca.gov/calenviroscreen?page=1)
  is an official OEHHA screening
  tool that ranks California census tracts using pollution burden,
  environmental conditions, socioeconomic factors, and health indicators, and is
  used by CalEPA to identify communities facing combined pollution and
  socioeconomic disadvantage, as described in the
  [CalEnviroScreen FAQs](https://oehha.ca.gov/calenviroscreen/calenviroscreen-faqs).
  For the MVP, the routes are not claimed to be the only vulnerable corridors in
  Fresno; they are fixed representative routes connecting transit to essential
  destinations, selected from OSM candidates so the demo tests a repeatable
  route-finding process rather than a hand-picked map view.

## 2. Heat threshold

What temperature counts as dangerous for a pedestrian, and on whose authority.

- **Threshold:** 35 °C dry-bulb air temperature at 2 m above ground, used as an
  operational threshold for FortyGuard exceedance.
- **Source:** A 2026 pedestrian thermal-comfort study uses daily maximum air
  temperature at or above 35 °C for at least three consecutive days to define
  extreme-heat walking-route conditions.
  Separately,
  epidemiological threshold studies show that heat-health thresholds vary by
  place and outcome; one warm-season mortality study found a 35 °C daily-maximum
  threshold for respiratory deaths
  ([Chen et al., 2017](https://www.sciencedirect.com/science/article/pii/S001393511631221X)).
- **Rationale:** Ambient Ops uses 35 °C dry-bulb exceedance as an operational
  way to count repeated dangerous-heat exposure. The threshold is high enough to
  represent serious pedestrian heat, simple enough to audit, and usable with the
  FortyGuard exceedance API. It is not a claim that every person becomes unsafe
  at exactly 35 °C, and it should be recalibrated for deployments with local
  heat-health trigger data.

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

LARGE TEMPERATURE MODELS (LTMs)'outputs are probabilistic — each value is paired with its uncertainty, which downstream stages carry through analytics and insights rather than drop at the model boundary.

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

We confirmed the 35°C dry-bulb threshold against pedestrian heat literature. Zhang et al. (2026), a route-scale pedestrian thermal-comfort study, defines extreme heat as daily maximum air temperature at or above 35°C for at least three consecutive days. This supports 35°C as a defensible operational threshold for pedestrian walking-route exposure. Ambient Ops uses it to count exceedance hours, not as a universal physiological cutoff.


## 3. Data sources

| Source | Used for | Layer / query | Notes |
|---|---|---|---|
| FortyGuard `/v1/heatmap` | HEI | `analytic_type=exceedance` | Verified accessible Aug 24. US-only coverage |
| FortyGuard `/v1/satellite` | SVI | Segmentation class coverage | Verified Aug 25: 7 classes, one call per segment, ~14,400 credits each |
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
because it is derived from imagery rather than volunteer tagging. It is used,
and on these routes it is not merely preferable but necessary: OSM returns
0 trees and no surface tags along either route, while imagery gives
0.0–15.3% canopy varying per segment. The two agree on the substance — the
corridor really is near-treeless — but only one of them can rank it.

Land cover is a **point sample at each segment midpoint**, not a polygon
average. The endpoint takes a point. State this as a limitation.

**Why not a snapshot.** A single-timestamp reading tells you it was hot at 2pm
last Tuesday, which is weather. Exceedance (how often a location exceeds the
threshold) or persistence (how long it stays above it) tells you a location is
*reliably* dangerous — which is what justifies spending public money.

### 2.3 Measured on the real routes — three of four factors do not vary

Run on the two selected Fresno routes, Aug 25. This is the most important
result in this document and it changes the scoring model.

| Route | Length | Segments | AOI grid spread | Within-route spread |
|---|---|---|---|---|
| A — bus stop to Heaton Elementary | 862 m | 17 | 1.279 h | **0.629 h** |
| B — transit stop to DBH clinic | 780 m | 16 | **0.000 h** | **0.000 h** |

Route B's entire area of interest returns 264.000 hours on all 87 tiles, with
a standard deviation of exactly zero. This is not a sampling artefact —
sampling resolves 13 distinct tiles on route A at 6–57 m from each midpoint.

**FortyGuard's exceedance field varies at neighbourhood scale, not street
scale.** Across a 4 km² transect the spread is 22.2 hours; across an 800 m
route it is between 0.6 and 0.0. HEI therefore separates *routes* from each
other, but cannot separate segments *within* a route.

Taking the four factors as the spec defines them, on route B:

| Factor | Varies within route? | Why |
|---|---|---|
| HEI | **No** — spread 0.000 | Grid is uniform at this scale |
| DTF | **No** — constant by construction | Segments are equal length, so length/1.3 is identical for every one |
| SVI | **No** — no data | OSM has 0 trees and 0 surface tags along the route |
| PSI | Yes | Distance to school/clinic changes along the route |

So the published ranking would be driven **entirely by proximity to the
destination** — which is not a heat analysis. The map would still render, the
scores would still differ, and nothing in the output would reveal it.

**Two concrete consequences:**

1. **Min-max normalisation divides by zero when spread is 0.** The scoring
   implementation must handle a constant factor explicitly and say what it
   does — returning a constant 0, or 0.5, or excluding the factor — rather
   than producing a NaN or an accidental ordering.

2. **DTF needs redefining or dropping.** With fixed-length segments,
   "segment length / 1.3 m/s" is the same number for every segment. A
   defensible alternative that matches the spec's stated intent ("longer
   unbroken exposure is worse") is the length of the *continuous unshaded run*
   a segment belongs to, not the segment's own length. That depends on SVI, so
   it must be computed after it. 

The implemented factor set keeps HEI, DTF, SVI, and PSI, but updates how they are interpreted after testing them on the real routes.

First, any factor that is constant across a route is marked as degenerate. A degenerate factor cannot explain why one segment ranks above another, so it is surfaced in the API and interface rather than hidden.

Second, DTF is redefined as continuous unshaded exposure instead of single-segment walking time. Since most segments are roughly 50 m, using only `segment_length / walking_speed` would give nearly the same value for every segment. Continuous exposed run length better matches the intended question: how long is a pedestrian stuck in heat without relief?

Third, SVI uses satellite land-cover data where available, because OSM tree and surface tags are sparse on the demo routes. Satellite segmentation provides varying tree, grass, pavement, and building context, while OSM remains useful for amenities, transit, shelter, water, and park context.

The default weights are retained as transparent planning assumptions, not empirically optimized coefficients. HEI keeps the largest starting weight because heat exposure is the core hazard, while DTF, SVI, and PSI capture exposure duration, built-environment vulnerability, and sensitive-destination context. Sensitivity analysis should be used to show whether the top-ranked segment is robust or policy-sensitive under alternative weight settings.

## 4. Segmentation

Routes are split into fixed 50 m segments. This is an operational planning
scale: short enough to identify a specific side of a block or transit-stop
approach for intervention, but not so short that the output pretends to exceed
the spatial support of the underlying heat layer. FortyGuard's finest available
granularity is 60 m, so a 50 m target segment keeps the map actionable while
remaining close to the heat-grid resolution. The final segment may be shorter
depending on route length.

Recent pedestrian thermal-comfort route research also supports this
street-segment scale. Zhang et al. (2026) found that daytime Tmrt/PET responded
most strongly to streetscape view factors within roughly 20-30 m, while
nighttime thermal comfort became more influenced by larger street-block
morphology around 50 m. Ambient Ops therefore treats 50 m as a practical
planning scale rather than a claim of metre-level thermal precision.

## 5. The Heat Priority Score

```
HPS = 100 * (w1*HEI + w2*DTF + w3*SVI + w4*PSI)
defaults: w1 = 0.40, w2 = 0.20, w3 = 0.20, w4 = 0.20
```

### 5.0 Implemented deviations from the specification

Three, all forced by section 2.3 and all visible in `backend/scoring/model.py`.
They are deviations, not silent fixes, and each is reversible.

**1. Constant factors resolve to a neutral 0.5 and are reported.** Route B's
heat grid is literally constant, so min-max normalisation would divide by
zero. A constant factor cannot rank anything; it now returns 0.5 for every
segment and appears in `degenerate_factors`, which the interface surfaces
rather than hides. On route B the published output states that HEI
contributed nothing.

**2. DTF is the continuous exposed run, not the segment's own length.**
Segments are equal by construction, so `length / 1.3` is identical for all of
them and ranks nothing. DTF is now the length of the unbroken exposed stretch
a segment belongs to — a segment in a 254 m run of unshaded pavement scores
far above an isolated one. This preserves the spec's stated intent ("longer
unbroken exposure is worse than the same temperature crossed quickly") which
the literal formula does not.

**3. SVI is computed from imagery, not OSM tags.** OSM yields 0 trees and
almost no surface tags on these routes; FortyGuard's satellite layer gives
0–15.3% tree cover that varies per segment. Spec section 5 prefers imagery
anyway. Both a continuous form (default) and the spec's discrete five-row
table are implemented — the table collapses the measured 0–15% range into two
or three buckets, discarding most of the only signal that varies. State in the
final write-up which produced the published ranking.

### 5.0.1 Result

With those three changes, all four factors vary on route A and three of four
on route B:

| | Route A | Route B |
|---|---|---|
| Heat spread (raw) | 0.63 h | 0.00 h |
| **HPS spread** | **48.4** | **25.8** |
| Degenerate factors | none | HEI |
| Segments with no intervention | 1 of 17 | 5 of 16 |

The segments with no matching intervention are the best-shaded ones, where
"nothing needed here" is the correct answer rather than a gap.

### 5.1 Weight justification

The default weights are a transparent starting position, not an empirically
optimised coefficient set.

**HEI = 0.40.** Heat exposure is the primary hazard the project is built around,
so it receives the largest starting weight. WHO identifies heat as a major
environmental and occupational health hazard and notes that health impacts
depend on exposure intensity, duration, timing, vulnerability, and local
adaptation. HEI is therefore the anchor factor: it measures accumulated
dangerous-heat exposure before the model adds walking exposure, street
vulnerability, and sensitive-destination context. However, HEI is allowed to
matter only when it varies within the route. If the heat layer is constant, the
model marks HEI as degenerate and the agent must not cite it as the reason one
segment outranks another.

**DTF = 0.20.** Exposure duration matters because the same heat condition is
more consequential when a pedestrian remains in an unshaded run for longer.
DTF therefore captures walking-exposure continuity rather than duplicating the
fixed segment length.

**SVI = 0.20.** Surface vulnerability represents the built environment: canopy,
shelter, paved surface, building shade, and nearby green or water context.
Pedestrian-thermal-comfort reviews consistently identify shade, vegetation, and
street geometry as major determinants of outdoor comfort.
Route-scale field measurements using 360-degree street view factors also find
that building exposure is a dominant warming contributor, while tree and
grass-shrub view factors provide consistent cooling during extreme-heat walking
conditions.

**PSI = 0.20.** Population sensitivity is an equity and use-context proxy. It
does not measure heat physics; it asks whether the segment is near a school,
clinic, hospital, elderly facility, or transit stop, where walking may be more
necessary or where exposed people may be more sensitive.

These weights should be tested with sensitivity analysis. A stable top segment
across weight scenarios can be described as robust; a changing top segment is a
policy-sensitive decision, not a model failure.

**This now needs revisiting rather than justifying as written.** HEI carries
the heaviest weight (0.40) but cannot separate segments within a route — on
route B it separates nothing at all. Either the weight drops, or HEI is
reframed as a route-level severity multiplier rather than a segment-level
factor. Both are defensible; the sliders make the choice arguable in public,
which is where it belongs.

### 5.2 HEI — Heat Exposure Index (0–1)

Normalised from the FortyGuard layer. **Normalised within the route, not
globally**, so the ranking stays meaningful in a uniformly hot city.

When every segment has the same heat value, min-max normalisation would divide
by zero. Ambient Ops resolves that case to a neutral 0.5 for every segment and
adds `HEI` to `degenerate_factors`. A degenerate factor shifts every segment
equally and contributes no ordering information.

### 5.3 DTF — Dwell Time Factor (0–1)

`segment_length_m / 1.3 m/s`, then normalised across the route.

- **Walking speed source:** TODO — 1.3 m/s needs a citation
- Longer unbroken exposure is worse than the same temperature crossed quickly.
  This is a large part of what separates Ambient Ops from a plain heat map.

  The 1.3 m/s value is close to common pedestrian-design walking-speed guidance:
[FHWA training material](https://www.fhwa.dot.gov/publications/research/safety/pedbike/05085/chapt8.cfm)
cites the MUTCD pedestrian clearance speed of 1.2 m/s (4.0 ft/s). Ambient Ops
uses 1.3 m/s as an average adult walking speed for route exposure, while
recognising that older adults, children, disabled pedestrians, and people
walking in extreme heat may move more slowly.

Longer unbroken exposure is worse than the same temperature crossed quickly.
This is a large part of what separates Ambient Ops from a plain heat map.

### 5.4 SVI — Surface Vulnerability Index (0–1)

| Condition | Value |
|---|---|
| Bare asphalt or concrete, no canopy, no shelter | 1.0 |
| Paved, some adjacent building shade | 0.7 |
| Paved with scattered trees | 0.5 |
| Continuous tree canopy | 0.2 |
| Adjacent to water or park | 0.1 |

The implemented score uses FortyGuard satellite land-cover percentages where
available, rather than relying only on OSM tags. OSM is still used for shelter,
amenities, transit proximity, and water/park context. If imagery is unavailable,
SVI falls back to OSM canopy context: segments with observed trees receive a
moderate value, while segments with no tree signal receive a conservative high
vulnerability value. Missing data is therefore handled as a data-quality caveat,
not as proof that bare asphalt is present.

For comparison and auditability, the five-row table remains the discrete
interpretation of the factor. The published ranking uses the continuous
satellite-derived SVI because measured canopy on these routes varies only from
0.0% to 15.3%, and the discrete table would discard much of that limited signal.

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

There is no ground-truth intervention outcome during the hackathon. The
validation target is therefore transparency and face validity: the ranking
should be traceable, numerically stable, and honest about when a factor cannot
support segment-level ordering.

Validation checks used:

- **Formula checks:** unit tests verify weight normalisation, HPS bounds,
  degenerate-factor handling, SVI/PSI behaviour, and intervention simulation
  effects.
- **Constant-factor checks:** Route B's heat layer is constant, so HEI is
  reported as degenerate. The interface greys it out and the agent is instructed
  not to cite it as an explanation.
- **Manual review:** top segments are inspected against their raw heat, exposed
  run, tree cover, nearby amenities, and recommended intervention.
- **Temperature-only baseline:** the ranking is compared against a heat-only
  interpretation to confirm the product is prioritising actionable planning
  segments, not simply the hottest tile.
- **Sensitivity analysis:** the same segments should be re-scored under default,
  no-heat, shade-priority, and equity-priority weights. If the same segment
  stays near the top, the recommendation is robust; if not, the decision is
  policy-sensitive and should be treated as a planner choice.

  Recommended sensitivity scenarios:

| Scenario | HEI | DTF | SVI | PSI |
|---|---:|---:|---:|---:|
| Default | 0.40 | 0.20 | 0.20 | 0.20 |
| No heat variation | 0.00 | 0.34 | 0.33 | 0.33 |
| Shade priority | 0.25 | 0.20 | 0.40 | 0.15 |
| Equity priority | 0.25 | 0.15 | 0.20 | 0.40 |

This validates model behaviour rather than claiming empirical optimality.


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
