# Ambient Ops

**Heat-aware route prioritisation for urban planners.**

An AI agent that analyses an essential walking route using hyperlocal temperature
data, ranks which segments of that route are most dangerous to pedestrians, and
recommends which cooling intervention to build first.

> FortyGuard Hackathon'26 — Track 06, Agentic AI

---

## The problem

Cities already know they are hot. What they do not know is which fifty metres of
which street to spend money on first.

A conventional heat map shows a red blob over a neighbourhood. A planner with a
limited budget needs a ranked list of specific points, each with a defensible
reason attached. Ambient Ops closes the gap between "this area is hot" and
"fix this corner first".

The routes that matter most are the ones people cannot avoid walking — a transit
stop to a school, a bus stop to a clinic. Non-discretionary journeys, often made
by people least able to choose an alternative.

## How it works

The agent is not a chatbot bolted onto a dashboard. It is the thing that runs the
analysis: the user picks a route, the agent decides which tools to call in which
order, and the interface renders what the agent produced.

```
React frontend (map + panel)
        |
        v
FastAPI backend
        |
        +--> Agent orchestrator (tool-calling loop)
        |         +--> get_route              (OpenRouteService)
        |         +--> get_heat_grid          (FortyGuard)
        |         +--> segment_route
        |         +--> get_segment_context    (OpenStreetMap / Overpass)
        |         +--> score_segments
        |         +--> recommend_intervention
        |         +--> simulate_intervention
        |
        +--> SQLite cache (heat grids, OSM lookups)
```

## The Heat Priority Score

Each ~50m segment receives an HPS from 0 to 100:

```
HPS = 100 * (w1*HEI + w2*DTF + w3*SVI + w4*PSI)
defaults: w1 = 0.40, w2 = 0.20, w3 = 0.20, w4 = 0.20
```

| Factor | Meaning |
|---|---|
| **HEI** | Heat Exposure Index — from the FortyGuard exceedance/persistence layer |
| **DTF** | Dwell Time Factor — how long a walker is exposed, at 1.3 m/s |
| **SVI** | Surface Vulnerability Index — canopy, shelter, surface type |
| **PSI** | Population Sensitivity Index — proximity to schools, clinics, transit |

The weights are exposed as sliders in the interface because they are debatable.
Full derivation, sources, and limitations live in [docs/METHODOLOGY.md](docs/METHODOLOGY.md).

## Quickstart

Requires Miniconda/Anaconda and Node 20+.

```bash
# 1. Configure — three free keys
cp .env.example .env
#   FORTYGUARD_API_KEY   hackathon key
#   ORS_API_KEY          openrouteservice.org/dev/#/signup
#   GROQ_API_KEY         console.groq.com/keys

# 2. Backend
conda env create -f environment.yml     # creates the `ambient-ops` env
conda activate ambient-ops
uvicorn backend.main:app --port 8000

# 3. Interface (separate terminal)
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173** — `localhost`, not `127.0.0.1`: Vite binds IPv6
only. Check `http://localhost:8000/api/health` first; `missing_keys` must be
empty.

```bash
pytest backend/tests -q          # 103 tests, no network needed
ruff check backend scripts
```

**Before a demo**, warm the caches and prove they are warm:

```bash
python scripts/precache_demo.py
```

It fills the cache, then re-runs both routes with `socket.connect` patched to
raise — so a cache miss cannot hide. Both must report **OFFLINE OK**. The full
runbook is [docs/DEMO.md](docs/DEMO.md).

## Endpoints

| | |
|---|---|
| `GET /api/health` | Integrations, model, cache state |
| `GET /api/routes` | The two fixed demo routes |
| `POST /api/analyze` | Start an agent run, returns `run_id` |
| `GET /api/analyze/{run_id}` | Poll: running, completed, failed |
| `GET /api/agent-trace/{run_id}` | Tool calls in order, with durations |
| `POST /api/simulate` | Apply an intervention, re-score |
| `GET /api/interventions` | The rules table, with sourcing flags |
| `GET /api/report/{run_id}` | Evidence record as PDF; `?format=json` for the data |

## Scripts

| | |
|---|---|
| `verify_fortyguard.py` | Which layers and cities the key unlocks |
| `find_routes.py` | Pair real OSM transit stops with schools/clinics |
| `preview_route.py` | Run the data pipeline for one route |
| `score_route.py` | Score and rank, no network, no cost |
| `run_agent.py` | The demo in text form |
| `fetch_segmentation.py` | Pre-fetch satellite land cover |
| `analyse_grid.py` | Does a heat grid vary enough to rank anything? |
| `precache_demo.py` | Warm the demo caches and verify offline |
| `debug_fortyguard_raw.py` | Raw API response inspection |

## Build status

| Step | Scope | State |
|---|---|---|
| 1 | Repo, scaffold, CI, API contract | ✅ done |
| 2 | FortyGuard service — submit, poll, cache, layer verification | ✅ done |
| 3 | Routing, segmentation, OSM context | ✅ done |
| 4 | Scoring model, intervention rules | ✅ done |
| 5 | Agent orchestrator, tools, endpoints | ✅ done |
| 6 | Map, route colouring, segment panel | ✅ done |
| 7 | Weight sliders, simulate mode, agent trace | ✅ done |
| 8 | Freeze, pre-cache, demo runbook, methodology | ✅ done |

## What we found that the spec did not anticipate

Three results changed the build. All are documented with measurements in
[docs/METHODOLOGY.md](docs/METHODOLOGY.md).

**FortyGuard coverage is US-only.** Abu Dhabi returns zero tiles on every
analytic layer. The city choice was settled by data, not preference.

**A single-hour heat reading cannot rank a street.** At any one hour a
literature-defensible 35 °C threshold is exceeded by every tile in Fresno, so
HEI flattens to a constant. Counting threshold crossings over 30 days turns
0.18 °C of temperature difference into 10.5 hours of accumulated exposure.

**Heat varies at neighbourhood scale, not street scale.** Across a 4 km²
transect the spread is 22.2 hours; across an 800 m route it is 0.63 — and on
route B, exactly zero, on all 87 tiles. So HEI separates routes but not
segments within a route. Rather than hide that, a constant factor is detected,
neutralised, flagged in the API, greyed in the interface, and stated by the
agent in its brief.

## Known limitations

Stated openly, as they should be:

- The population sensitivity proxy uses amenity proximity, **not actual pedestrian
  counts**. Real deployment would require footfall data.
- **No ground truth** exists to validate the ranking against. This is decision
  support with a transparent model, not a prediction.
- Cooling effect estimates come from published literature averages, not
  site-specific thermal modelling.
- Two routes in one city is a demonstration, not evidence of generalisation.
- The scoring weights are a starting position, not an empirically derived optimum.
- Satellite land cover is one point sample per segment, not a full polygon.
- The canopy threshold in the intervention rules is calibrated to the observed
  local range and still wants a citation.
- **No cooling figures are stated anywhere.** Every `cooling_estimate` is null
  pending sourced literature, the agent is forbidden from inventing one, and a
  test fails if a figure appears without a citation beside it.

## Team

| | |
|---|---|
| **Moez** | Engineering, team lead — backend, agent loop, integrations, frontend, deployment, submission |
| **Minqi** | Data science — scoring model, context data quality, validation, methodology |
| **Ameera** | Research and presentation — narrative, literature sourcing, slides, demo script |
