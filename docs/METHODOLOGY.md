# Ambient Ops — Methodology

> **Owner: Minqi.** Skeleton created by Moez in Step 1 so the sections are agreed
> up front. Every `TODO` below is a claim that needs a source or a decision.
> Due end of Step 8 (Aug 29) per the build plan.

---

## 1. Study area

- **City:** TODO — decision pending. Coverage must be verified against the
  FortyGuard grid before it is locked.
- **Routes:** two, each a transit stop to a school or clinic, 400–900 m.
  - Route A: TODO
  - Route B: TODO
- **Why these routes:** non-discretionary journeys — walked by people with the
  least ability to choose an alternative.

## 2. Heat threshold

What temperature counts as dangerous for a pedestrian, and on whose authority.

- **Threshold:** TODO °C at 2 m above ground
- **Source:** TODO — needs a citation, not a round number
- **Rationale:** TODO

## 3. Data sources

| Source | Used for | Layer / query | Notes |
|---|---|---|---|
| FortyGuard | HEI | TODO — exceedance or persistence | Verified accessible on TODO |
| OpenRouteService | Route geometry | Pedestrian profile | |
| OpenStreetMap (Overpass) | SVI, PSI context | 25 m radius per segment | Volunteer-tagged; completeness varies |

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
