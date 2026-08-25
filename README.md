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
# 1. Configure
cp .env.example .env      # FORTYGUARD_API_KEY, ORS_API_KEY, GROQ_API_KEY

# 2. Backend
conda env create -f environment.yml     # creates the `ambient-ops` env
conda activate ambient-ops
uvicorn backend.main:app --reload
# -> http://127.0.0.1:8000/docs

# 3. Frontend (separate terminal)
cd frontend && npm install && npm run dev
# -> http://127.0.0.1:5173
```

Check `GET /api/health` to see which integrations are still unconfigured.

```bash
conda activate ambient-ops
pytest backend/tests -q
```

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
| 8 | Freeze, pre-cache, deploy, methodology | ⬜ |

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

## Team

| | |
|---|---|
| **Moez** | Engineering, team lead — backend, agent loop, integrations, frontend, deployment, submission |
| **Minqi** | Data science — scoring model, context data quality, validation, methodology |
| **Ameera** | Research and presentation — narrative, literature sourcing, slides, demo script |
