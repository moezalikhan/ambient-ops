"""Ambient Ops API.

Endpoint surface is fixed here (spec section 9) so the frontend can be built
against it. Handlers that depend on later steps return 501 with the step that
fills them in, rather than silently returning fake data.
"""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend import config
from backend.cache import store
from backend.models import AnalyzeRequest, Route, SimulateRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    yield


app = FastAPI(
    title="Ambient Ops",
    description="Heat-aware route prioritisation for urban planners",
    version="0.1.0",
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
    raise _not_yet(5, "The agent orchestrator run")


@app.get("/api/analyze/{run_id}")
def analyze_result(run_id: str) -> dict:
    raise _not_yet(5, "Analysis result polling")


@app.post("/api/simulate")
def simulate(req: SimulateRequest) -> dict:
    raise _not_yet(7, "What-if intervention simulation")


@app.get("/api/agent-trace/{run_id}")
def agent_trace(run_id: str) -> dict:
    raise _not_yet(5, "The agent tool-call trace")
