# Demo runbook

The three-minute story: route selection, agent trace, ranked output, one
intervention explanation, one simulation. That is the whole thing.

---

## The day before

```bash
conda activate ambient-ops
python scripts/precache_demo.py
```

Both routes must end with **OFFLINE OK**. That means the whole data pipeline —
routing, heat grids, OSM context, satellite land cover — runs from the local
SQLite cache with the network blocked. The script proves it by monkeypatching
`socket.connect` to raise, so a cache miss cannot hide behind a fast response.

What is *not* cached: the agent's calls to the model. Those still go out. If
the venue's network is unreliable, that is the single point of failure, so
record the fallback video (spec section 13).

## Starting it

Two terminals.

```bash
# 1 — API
conda activate ambient-ops
uvicorn backend.main:app --port 8000

# 2 — interface
cd frontend && npm run dev
```

Open **http://localhost:5173**.

> Use `localhost`, not `127.0.0.1`. Vite binds IPv6 only, so `127.0.0.1:5173`
> refuses the connection while `localhost:5173` works. The API is fine on
> either.

Check `http://localhost:8000/api/health` first — `missing_keys` must be empty.

## The three minutes

**1. Pick a route.** Two fixed routes, each a transit stop to a school or
clinic. Say why these: non-discretionary journeys, walked by people least able
to choose an alternative.

**2. Run analysis, and talk over the trace.** The trace panel fills in as the
agent works. The point to make: nothing in the code sequences this. The agent
chose to call `get_route`, then `segment_route`, then `get_heat_grid`, then
`score_segments`, then `recommend_intervention`. Durations near zero are cache
hits — the wall-clock time is the model deciding what to call next.

**3. The ranked output.** Seventeen segments, coloured on the map, ranked in
the panel. Click the top one; the map highlights it.

**4. Move a slider.** Drag HEI to zero. The route re-ranks live — on route A
the start segment falls from rank 2 to rank 13, because its score was
heat-driven. This is the moment that shows the model is transparent rather
than a black box, and it costs no API call because re-weighting happens in the
browser.

**5. Simulate.** Pick the top segment, choose *Street tree planting*, hit
Simulate. Score drops 68.3 to 39.7, rank 1 to 9. Then read the line underneath
out loud: **magnitude sourced — no, illustrative**, and the trade-off, that
trees deliver nothing for about a decade.

## If a judge pushes

**"Where does the cooling number come from?"** There isn't one. Every
`cooling_estimate` in the intervention table is null, the agent is forbidden
from stating one, and a test fails if a figure ever appears without a citation
beside it. What the simulation changes is stated as an assumption and labelled
as unsourced in the interface.

**"How do you know the ranking is right?"** We don't. There is no ground truth
to validate against. It is decision support with a transparent model, which is
why every weight is adjustable and every factor is shown separately.

**"Is heat actually driving this?"** On route A, partly — the within-route
spread is 0.63 hours. On route B it is **exactly zero**: the heat layer returns
the same value on all 87 tiles, so HEI is flagged degenerate, greyed in the
interface, and contributes nothing. Run route B and show it. FortyGuard's
exceedance field varies at neighbourhood scale, not street scale, and saying so
is stronger than pretending otherwise.

**"Why 35 °C and 30 days?"** Because a defensible threshold at a single hour is
exceeded by every tile in Fresno, which flattens HEI to nothing. Integrating
over 30 days turns 0.18 °C of temperature difference into 10.5 hours of
accumulated exposure. METHODOLOGY 2.2 has the measurements.

## Known weak points — say them before you are asked

- Population sensitivity is amenity proximity, not footfall.
- Two routes in one city is a demonstration, not evidence of generalisation.
- The satellite land cover is one point sample per segment, not a full
  polygon.
- The canopy threshold in the intervention rules is calibrated to the observed
  local range and still needs a citation.
- The agent's model is a free-tier hosted model; tool-calling reliability is
  good but not guaranteed, which is what the fallback video is for.
