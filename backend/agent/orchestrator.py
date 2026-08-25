"""The tool-calling loop.

The agent decides which tools to call and in what order; this module executes
those calls, records a trace, and keeps the run's state. That distinction is
the reason this project belongs in Track 06, so the trace is a first-class
output rather than debug logging (spec section 4).

Runs execute on a background thread so the HTTP layer can poll, which matches
the async shape of the FortyGuard API underneath.
"""

import json
import threading
import time
import traceback
import uuid
from typing import Any

from backend import config
from backend.agent import prompts
from backend.agent.tools import (
    TOOL_IMPLS,
    TOOL_SCHEMAS,
    RunContext,
    ToolError,
    summarise_result,
)

# A run that has not settled by here is stuck. Each tool is cached after the
# first call, so a pre-cached demo route completes in seconds.
MAX_ITERATIONS = 16
MAX_TOOL_CALLS = 40

_RUNS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


class AgentError(RuntimeError):
    pass


def _client():
    if not config.LLM_API_KEY:
        raise AgentError(
            f"No API key for the agent model. Set {config.LLM_PROVIDER.upper()}"
            f"_API_KEY in .env, or switch LLM_PROVIDER."
        )
    from openai import OpenAI

    return OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)


def _record(run: dict, entry: dict) -> None:
    with _LOCK:
        run["trace"].append(entry)


def _execute_tool(ctx: RunContext, name: str, args: dict) -> tuple[Any, bool]:
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        raise ToolError(f"unknown tool {name!r}")
    before = ctx.grid.get("cache_hit") if ctx.grid else None
    result = impl(ctx, **args)
    after = ctx.grid.get("cache_hit") if ctx.grid else None
    cache_hit = bool(after) if before != after else bool(after)
    return result, cache_hit


def _run_loop(run_id: str, route_id: str, weights: dict | None) -> None:
    run = _RUNS[run_id]
    ctx = RunContext(route_id=route_id, weights=weights)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompts.SYSTEM_PROMPT},
        {"role": "user", "content": prompts.user_prompt(route_id, weights)},
    ]

    try:
        client = _client()
        seq = 0
        for _ in range(MAX_ITERATIONS):
            response = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
                temperature=0.2,
            )
            message = response.choices[0].message
            calls = message.tool_calls or []

            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name,
                                  "arguments": c.function.arguments}}
                    for c in calls
                ] or None,
            })

            if not calls:
                run["answer"] = message.content or ""
                break

            if seq + len(calls) > MAX_TOOL_CALLS:
                raise AgentError(f"exceeded {MAX_TOOL_CALLS} tool calls")

            for call in calls:
                seq += 1
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                started = time.monotonic()
                try:
                    result, cache_hit = _execute_tool(ctx, name, args)
                    ok, payload = True, result
                except ToolError as e:
                    # A tool error is information the agent can act on — a
                    # wrong segment id, or a tool called out of order. Hand it
                    # back rather than failing the run.
                    ok, payload, cache_hit = False, {"error": str(e)}, False
                except Exception as e:  # noqa: BLE001 — surfaced to the agent
                    ok, payload, cache_hit = False, {"error": f"{type(e).__name__}: {e}"}, False

                duration_ms = int((time.monotonic() - started) * 1000)
                _record(run, {
                    "seq": seq,
                    "tool": name,
                    "arguments": args,
                    "ok": ok,
                    "result_summary": (summarise_result(name, payload) if ok
                                       else str(payload.get("error"))[:160]),
                    "duration_ms": duration_ms,
                    "cache_hit": cache_hit,
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(payload, default=str)[:20000],
                })
        else:
            raise AgentError(f"did not finish within {MAX_ITERATIONS} iterations")

        with _LOCK:
            run["status"] = "completed"
            run["result"] = _final_result(ctx, run.get("answer", ""))
            run["finished_at"] = time.time()

    except Exception as e:  # noqa: BLE001 — recorded, then polled by the client
        with _LOCK:
            run["status"] = "failed"
            run["error"] = f"{type(e).__name__}: {e}"
            run["traceback"] = traceback.format_exc()[-2000:]
            run["finished_at"] = time.time()


def _final_result(ctx: RunContext, answer: str) -> dict[str, Any]:
    scored = ctx.scored or {}
    segments = scored.get("segments") or []
    return {
        "route_id": ctx.route_id,
        "route": {
            "name": (ctx.meta or {}).get("name"),
            "origin_name": (ctx.meta or {}).get("origin_name"),
            "destination_name": (ctx.meta or {}).get("destination_name"),
            "distance_m": round((ctx.route or {}).get("distance_m", 0), 1),
            "coordinates": (ctx.route or {}).get("coordinates", []),
        },
        "weights": scored.get("weights"),
        "degenerate_factors": scored.get("degenerate_factors", []),
        "heat_spread": scored.get("heat_spread"),
        "hps_spread": scored.get("hps_spread"),
        "svi_source": scored.get("svi_source"),
        "heat_layer": {
            "layer": (ctx.grid or {}).get("layer"),
            "units": (ctx.grid or {}).get("units"),
            "threshold_c": (ctx.grid or {}).get("threshold_c"),
        },
        "segments": sorted(segments, key=lambda s: s.get("rank", 999)),
        "brief": answer,
    }


def start_run(route_id: str, weights: dict | None = None) -> str:
    run_id = uuid.uuid4().hex[:12]
    _RUNS[run_id] = {
        "run_id": run_id,
        "route_id": route_id,
        "status": "running",
        "trace": [],
        "result": None,
        "error": None,
        "answer": "",
        "started_at": time.time(),
        "finished_at": None,
        "model": f"{config.LLM_PROVIDER}/{config.LLM_MODEL}",
    }
    threading.Thread(
        target=_run_loop, args=(run_id, route_id, weights), daemon=True
    ).start()
    return run_id


def get_run(run_id: str) -> dict[str, Any] | None:
    return _RUNS.get(run_id)


def get_trace(run_id: str) -> dict[str, Any] | None:
    run = _RUNS.get(run_id)
    if run is None:
        return None
    return {
        "run_id": run_id,
        "status": run["status"],
        "model": run["model"],
        "elapsed_s": round((run["finished_at"] or time.time()) - run["started_at"], 2),
        "tool_calls": run["trace"],
    }
