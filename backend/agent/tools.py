"""Agent tools (spec section 8).

Each tool is a JSON-schema function definition plus a dispatcher onto the
service layer. The agent chooses which to call and in what order; nothing here
sequences them.

State is per-run. `segment_route` produces the segment ids that
`get_segment_context` and `recommend_intervention` later refer to, so a run
carries its intermediate results in a RunContext rather than recomputing them.

One deviation from the spec's signatures: `get_route` takes `route_id` rather
than (origin_name, destination_name). The demo routes are a fixed set (spec
section 3), so an id is unambiguous where a name is not — the names are
returned in the payload.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from backend import config
from backend.scoring import interventions as iv
from backend.scoring import model
from backend.services import fortyguard as fg
from backend.services import osm, routing, segmentation


class ToolError(RuntimeError):
    """A tool failed in a way the agent should see and can react to."""


@dataclass
class RunContext:
    """Everything one analysis run accumulates."""

    route_id: str | None = None
    weights: dict[str, float] | None = None
    meta: dict[str, Any] | None = None
    route: dict[str, Any] | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    grid: dict[str, Any] | None = None
    features: list[dict[str, Any]] = field(default_factory=list)
    scored: dict[str, Any] | None = None
    recommendations: dict[str, Any] = field(default_factory=dict)

    def segment(self, segment_id: str) -> dict[str, Any]:
        source = (self.scored or {}).get("segments") or self.segments
        for s in source:
            if s["id"] == segment_id:
                return s
        raise ToolError(
            f"unknown segment_id {segment_id!r}. Call segment_route first, then use "
            f"the ids it returned."
        )


def load_routes() -> list[dict[str, Any]]:
    return json.loads(config.DEMO_ROUTES_PATH.read_text())["routes"]


# --- tool implementations -------------------------------------------------

def _get_route(ctx: RunContext, route_id: str) -> dict[str, Any]:
    routes = load_routes()
    meta = next((r for r in routes if r["id"] == route_id), None)
    if meta is None:
        raise ToolError(
            f"unknown route_id {route_id!r}. Available: {[r['id'] for r in routes]}"
        )
    route = routing.get_route(
        (meta["origin"]["lon"], meta["origin"]["lat"]),
        (meta["destination"]["lon"], meta["destination"]["lat"]),
    )
    ctx.route_id, ctx.meta, ctx.route = route_id, meta, route
    return {
        "route_id": route_id,
        "name": meta["name"],
        "origin_name": meta["origin_name"],
        "destination_name": meta["destination_name"],
        "city": meta.get("city"),
        "distance_m": round(route["distance_m"], 1),
        "duration_s": round(route["duration_s"], 1),
        "point_count": len(route["coordinates"]),
        "provider": route["provider"],
    }


def _segment_route(ctx: RunContext, segment_length_m: float | None = None
                   ) -> dict[str, Any]:
    if not ctx.route:
        raise ToolError("call get_route before segment_route")
    segs = segmentation.segment_route(
        ctx.route["coordinates"], route_id=ctx.route_id,
        segment_length_m=segment_length_m,
    )
    ctx.segments = segs
    return {
        "segment_count": len(segs),
        "segment_length_m": segs[0]["length_m"],
        "segments": [
            {"id": s["id"], "index": s["index"], "midpoint": s["midpoint"]}
            for s in segs
        ],
    }


def _get_heat_grid(ctx: RunContext) -> dict[str, Any]:
    if not ctx.route:
        raise ToolError("call get_route before get_heat_grid")
    grid = fg.get_heat_grid_for_route(ctx.route["coordinates"])
    ctx.grid = grid
    if ctx.segments:
        ctx.segments = segmentation.sample_heat_onto_segments(ctx.segments, grid["grid"])

    values = [g["value"] for g in grid["grid"]]
    spread = round(max(values) - min(values), 4)
    return {
        "layer": grid["layer"],
        "units": grid["units"],
        "threshold_c": grid["threshold_c"],
        "resolution_m": grid["resolution_m"],
        "tile_count": grid["tile_count"],
        "value_min": min(values),
        "value_max": max(values),
        "spread": spread,
        "window": grid["date_time"],
        # The agent is told plainly when the layer cannot rank anything, so it
        # does not narrate heat as the reason for a ranking heat did not drive.
        "note": (
            "This layer is CONSTANT across the route — it cannot distinguish "
            "segments and must not be cited as the reason one segment outranks "
            "another." if spread == 0 else
            f"Spread across the route is {spread} {grid['units']}."
        ),
    }


def _get_segment_context(ctx: RunContext, segment_id: str) -> dict[str, Any]:
    if not ctx.route:
        raise ToolError("call get_route before get_segment_context")
    if not ctx.features:
        ctx.features = osm.fetch_route_features(ctx.route["coordinates"])
        ctx.segments = segmentation.attach_context(ctx.segments, ctx.features)
        ctx.segments = segmentation.attach_landcover(ctx.segments)

    seg = ctx.segment(segment_id)
    landcover = seg.get("landcover")
    return {
        "segment_id": segment_id,
        "context": seg.get("context"),
        "land_cover_percent_of_image": landcover,
        "units_note": (
            "Land-cover values are already percentages. 0.9 means 0.9 percent, "
            "not 90 percent."
        ),
        "land_cover_source": "FortyGuard satellite" if landcover else "unavailable",
    }


def _score_segments(ctx: RunContext, weights: dict[str, float] | None = None
                    ) -> dict[str, Any]:
    if not ctx.segments:
        raise ToolError("call segment_route before score_segments")
    if "heat_value" not in ctx.segments[0]:
        raise ToolError("call get_heat_grid before score_segments")
    if not ctx.features:
        ctx.features = osm.fetch_route_features(ctx.route["coordinates"])
        ctx.segments = segmentation.attach_context(ctx.segments, ctx.features)
        ctx.segments = segmentation.attach_landcover(ctx.segments)

    weights = weights or ctx.weights
    result = model.score_segments(ctx.segments, weights=weights)
    ctx.scored = result

    ranked = sorted(result["segments"], key=lambda s: s["rank"])
    return {
        "factor_glossary": {
            "HEI": "Heat Exposure Index — normalised 30-day count of hours above "
                   "the temperature threshold. Accumulated exposure, not a "
                   "surface temperature.",
            "DTF": "Dwell Time Factor — length of the unbroken unshaded run this "
                   "segment sits in, over walking speed.",
            "SVI": "Surface Vulnerability Index — canopy, paving, and built "
                   "surface. High means hard and unshaded.",
            "PSI": "Population Sensitivity Index — proximity to schools, clinics "
                   "and transit. A proxy for who is exposed.",
        },
        "weights": result["weights"],
        "degenerate_factors": result["degenerate_factors"],
        "heat_spread": result["heat_spread"],
        "hps_spread": result["hps_spread"],
        "svi_source": result["svi_source"],
        "segments": [
            {"id": s["id"], "index": s["index"], "rank": s["rank"], "HPS": s["HPS"],
             "HEI": s["HEI"], "DTF": s["DTF"], "SVI": s["SVI"], "PSI": s["PSI"],
             "exposed_run_m": s.get("raw", {}).get("exposed_run_m"),
             "length_m": s.get("length_m")}
            for s in ranked
        ],
        "note": (
            f"Factors {result['degenerate_factors']} are constant across this "
            "route and contributed nothing to the ranking. Say so when "
            "explaining the result."
            if result["degenerate_factors"] else
            "All four factors vary across this route."
        ),
    }


def _recommend_intervention(ctx: RunContext, segment_id: str) -> dict[str, Any]:
    if not ctx.scored:
        raise ToolError("call score_segments before recommend_intervention")
    seg = ctx.segment(segment_id)
    return iv.format_for_agent(seg)


TOOL_IMPLS = {
    "get_route": _get_route,
    "segment_route": _segment_route,
    "get_heat_grid": _get_heat_grid,
    "get_segment_context": _get_segment_context,
    "score_segments": _score_segments,
    "recommend_intervention": _recommend_intervention,
}


# --- schemas --------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_route",
            "description": (
                "Fetch the walking geometry for one of the fixed demo routes. "
                "Call this first — every other tool depends on it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "route_id": {"type": "string",
                                 "description": "e.g. 'route_a' or 'route_b'"}
                },
                "required": ["route_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "segment_route",
            "description": (
                "Split the loaded route into equal-length segments and return "
                "their ids. Those ids are what the other tools accept."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_length_m": {
                        "type": "number",
                        "description": "Target segment length in metres. Default 50.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_heat_grid",
            "description": (
                "Fetch the FortyGuard heat layer covering the route and attach "
                "it to the segments. Returns the layer, its units, and the "
                "spread across the route — check the spread before attributing "
                "any ranking to heat."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_segment_context",
            "description": (
                "What is physically present at a segment: land-cover "
                "percentages from satellite imagery, trees, shelter, surface, "
                "and nearby amenities."
            ),
            "parameters": {
                "type": "object",
                "properties": {"segment_id": {"type": "string"}},
                "required": ["segment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_segments",
            "description": (
                "Compute the Heat Priority Score for every segment and rank "
                "them. Reports which factors are constant and therefore "
                "contributed nothing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "weights": {
                        "type": "object",
                        "description": "Optional HEI/DTF/SVI/PSI weights.",
                        "properties": {
                            "HEI": {"type": "number"}, "DTF": {"type": "number"},
                            "SVI": {"type": "number"}, "PSI": {"type": "number"},
                        },
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_intervention",
            "description": (
                "Get the permitted interventions for a segment, with the "
                "evidence behind them. You must choose from the candidates "
                "returned; do not invent an intervention and do not state any "
                "cooling figure."
            ),
            "parameters": {
                "type": "object",
                "properties": {"segment_id": {"type": "string"}},
                "required": ["segment_id"],
            },
        },
    },
]


def summarise_result(name: str, result: Any) -> str:
    """One line for the trace panel."""
    if not isinstance(result, dict):
        return str(result)[:120]
    if name == "get_route":
        return f"{result.get('name')} — {result.get('distance_m')} m"
    if name == "segment_route":
        return f"{result.get('segment_count')} segments"
    if name == "get_heat_grid":
        return (f"{result.get('tile_count')} tiles, spread "
                f"{result.get('spread')} {result.get('units')}")
    if name == "get_segment_context":
        lc = result.get("land_cover_pct") or {}
        return f"tree {lc.get('tree', 0):.1f}%, building {lc.get('building', 0):.1f}%"
    if name == "score_segments":
        segs = result.get("segments") or []
        top = segs[0] if segs else {}
        deg = result.get("degenerate_factors") or []
        return (f"top {top.get('id')} HPS {top.get('HPS')}"
                + (f"; constant: {','.join(deg)}" if deg else ""))
    if name == "recommend_intervention":
        return f"{len(result.get('candidates') or [])} candidate interventions"
    return "ok"
