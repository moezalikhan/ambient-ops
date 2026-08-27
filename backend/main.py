"""Ambient Ops API.

Endpoint surface is fixed by spec section 9. The agent orchestrator, not this
module, decides how an analysis is performed — these handlers start a run and
report on it.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import config
from backend import report as reporting
from backend.agent import orchestrator
from backend.cache import store
from backend.models import AnalyzeRequest, Route, SimulateRequest
from backend.scoring import simulate as sim


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    yield


app = FastAPI(
    title="Ambient Ops",
    description="Heat-aware route prioritisation for urban planners",
    version="0.5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _not_yet(step: int, what: str) -> HTTPException:
    return HTTPException(
        status_code=501,
        detail=f"{what} lands in Step {step}. Endpoint shape is final; handler is not.",
    )


@app.get("/api/health")
def health() -> dict:
    """Which integrations are wired. Checked before every demo run."""
    return {
        "status": "ok",
        "missing_keys": config.missing_keys(),
        "agent_model": f"{config.LLM_PROVIDER}/{config.LLM_MODEL}",
        "heat_layer": config.FORTYGUARD_ANALYTIC_TYPE,
        "heat_threshold_c": config.HEAT_THRESHOLD_C,
        "cache": store.stats(),
    }


@app.get("/api/routes", response_model=list[Route])
def list_routes() -> list[Route]:
    """The fixed demo routes. No arbitrary user routes — spec section 3."""
    with open(config.DEMO_ROUTES_PATH) as f:
        payload = json.load(f)
    return [Route(**r) for r in payload["routes"]]


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    """Start an agent run. Returns a run_id to poll.

    Asynchronous because the agent's own tools are: a cold FortyGuard job takes
    minutes. With a pre-cached route the run settles in seconds, which is what
    the demo relies on (spec section 13).
    """
    routes = {r["id"] for r in json.loads(config.DEMO_ROUTES_PATH.read_text())["routes"]}
    if req.route_id not in routes:
        raise HTTPException(404, f"unknown route_id {req.route_id!r}. Have: {sorted(routes)}")
    if config.missing_keys():
        raise HTTPException(503, f"unconfigured: {', '.join(config.missing_keys())}")

    weights = req.weights.normalised().model_dump()
    run_id = orchestrator.start_run(req.route_id, weights)
    return {"run_id": run_id, "status": "running", "poll": f"/api/analyze/{run_id}"}


@app.get("/api/analyze/{run_id}")
def analyze_result(run_id: str) -> dict:
    """Poll a run. `status` is running, completed, or failed."""
    run = orchestrator.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"unknown run_id {run_id!r}")
    return {
        "run_id": run_id,
        "status": run["status"],
        "route_id": run["route_id"],
        "model": run["model"],
        "tool_calls_so_far": len(run["trace"]),
        "error": run["error"],
        "result": run["result"],
    }


@app.get("/api/agent-trace/{run_id}")
def agent_trace(run_id: str) -> dict:
    """The tool calls the agent made, in order.

    Exists so the agent's reasoning can be shown during judging — spec section
    9 says explicitly not to skip it.
    """
    trace = orchestrator.get_trace(run_id)
    if trace is None:
        raise HTTPException(404, f"unknown run_id {run_id!r}")
    return trace


@app.get("/api/report/{run_id}")
def report(run_id: str, download: bool = True) -> JSONResponse:
    """The full evidence record behind a ranking.

    A ranked list is a claim; this is the working behind it — every factor
    value, every raw measurement, the weights used, which factors carried no
    information, how far the ranking moves when those weights change, and what
    each simulated intervention assumes.

    Deliberately not rendered in the interface: it is the artefact you attach
    to a decision or hand to someone who wants to check the arithmetic.
    """
    run = orchestrator.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"unknown run_id {run_id!r}")
    if run["status"] != "completed":
        raise HTTPException(409, f"run {run_id} is {run['status']}")

    body = reporting.build_report(run)
    headers = (
        {"Content-Disposition":
         f'attachment; filename="ambient-ops-{run["route_id"]}-{run_id}.json"'}
        if download else {}
    )
    return JSONResponse(content=body, headers=headers)


# --- static interface -----------------------------------------------------
# Serving the built frontend from the API makes this a single process on a
# single origin: one URL to share through a tunnel, one service to deploy, and
# no CORS. `npm run build` first; in development use the Vite dev server on
# 5173 instead, which proxies /api here.
_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_DIST / "index.html")


@app.post("/api/simulate")
def simulate(req: SimulateRequest) -> dict:
    """Apply an intervention to a segment and re-score the route.

    Costs nothing and touches no external API — it re-runs the scoring model
    over the run's stored segments, so a planner can move through what-ifs at
    interactive speed.
    """
    run = orchestrator.get_run(req.run_id)
    if run is None:
        raise HTTPException(404, f"unknown run_id {req.run_id!r}")
    if run["status"] != "completed":
        raise HTTPException(409, f"run {req.run_id} is {run['status']}")
    if not run.get("segments"):
        raise HTTPException(409, "this run produced no scored segments")

    weights = req.weights.normalised().model_dump() if req.weights else run.get("weights")
    try:
        return sim.simulate_intervention(
            run["segments"], req.segment_id, req.intervention, weights=weights
        )
    except sim.SimulationError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/interventions")
def interventions() -> dict:
    """The intervention table, for the what-if picker in the interface."""
    return {
        "interventions": [
            {"id": k, "label": v["label"], "assumption": v["assumption"],
             "sourced": v["sourced"], "caveat": v["caveat"]}
            for k, v in sim.EFFECTS.items()
        ]
    }
