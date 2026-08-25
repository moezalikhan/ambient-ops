"""Agent tools and the orchestration loop. The model is mocked throughout."""

import json
from types import SimpleNamespace

import pytest

from backend.agent import orchestrator, prompts, tools
from backend.agent.tools import RunContext, ToolError

# --- tool ordering --------------------------------------------------------

def test_tools_refuse_to_run_out_of_order():
    """A tool called too early must say what to call first, so the agent can
    recover instead of the run dying."""
    ctx = RunContext()
    with pytest.raises(ToolError, match="call get_route"):
        tools._segment_route(ctx)
    with pytest.raises(ToolError, match="call get_route"):
        tools._get_heat_grid(ctx)
    with pytest.raises(ToolError, match="call segment_route"):
        tools._score_segments(ctx)


def test_unknown_route_id_lists_the_valid_ones():
    with pytest.raises(ToolError, match="route_a"):
        tools._get_route(RunContext(), "not_a_route")


def test_unknown_segment_id_explains_how_to_get_one():
    ctx = RunContext(segments=[{"id": "route_a_seg_00"}])
    with pytest.raises(ToolError, match="segment_route"):
        ctx.segment("nope")


def test_recommend_requires_scores_first():
    ctx = RunContext(segments=[{"id": "s0"}])
    with pytest.raises(ToolError, match="score_segments"):
        tools._recommend_intervention(ctx, "s0")


# --- schemas --------------------------------------------------------------

def test_every_schema_has_an_implementation():
    named = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    assert named == set(tools.TOOL_IMPLS)


def test_schemas_are_json_serialisable():
    json.dumps(tools.TOOL_SCHEMAS)


def test_required_params_are_declared():
    by_name = {s["function"]["name"]: s["function"] for s in tools.TOOL_SCHEMAS}
    assert by_name["get_route"]["parameters"]["required"] == ["route_id"]
    assert by_name["get_segment_context"]["parameters"]["required"] == ["segment_id"]


# --- prompt guardrails ----------------------------------------------------

def test_prompt_defines_every_acronym():
    """A run once invented 'social vulnerability' and 'pedestrian safety'
    because the prompt never said what the letters meant."""
    p = prompts.SYSTEM_PROMPT
    for expansion in ("Heat Exposure Index", "Dwell Time Factor",
                      "Surface Vulnerability Index", "Population Sensitivity Index"):
        assert expansion in p


def test_prompt_forbids_inventing_cooling_figures_and_weights():
    p = prompts.SYSTEM_PROMPT
    assert "Never state a cooling figure" in p
    assert "weights" in p and "planner" in p


def test_prompt_requires_reporting_constant_factors():
    assert "constant" in prompts.SYSTEM_PROMPT.lower()


# --- summaries ------------------------------------------------------------

def test_summary_flags_constant_factors():
    out = tools.summarise_result("score_segments", {
        "segments": [{"id": "s0", "HPS": 61.6}],
        "degenerate_factors": ["HEI"],
    })
    assert "s0" in out and "HEI" in out


def test_summary_survives_unexpected_shapes():
    assert tools.summarise_result("get_route", "not a dict")
    assert tools.summarise_result("nonexistent_tool", {}) == "ok"


# --- the loop -------------------------------------------------------------

def _msg(content="", calls=None):
    tool_calls = [
        SimpleNamespace(
            id=f"c{i}", type="function",
            function=SimpleNamespace(name=n, arguments=json.dumps(a)))
        for i, (n, a) in enumerate(calls or [])
    ] or None
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content=content, tool_calls=tool_calls))])


class _FakeClient:
    """Replays a scripted sequence of model responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _run_to_completion(monkeypatch, responses, route_id="route_a", timeout=10.0):
    import time as _t
    client = _FakeClient(responses)
    monkeypatch.setattr(orchestrator, "_client", lambda: client)
    run_id = orchestrator.start_run(route_id)
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        run = orchestrator.get_run(run_id)
        if run["status"] != "running":
            return run, client
        _t.sleep(0.05)
    raise AssertionError(f"run did not settle: {orchestrator.get_run(run_id)}")


def test_loop_records_a_trace_and_finishes(monkeypatch):
    run, client = _run_to_completion(monkeypatch, [
        _msg(calls=[("get_route", {"route_id": "route_a"})]),
        _msg(calls=[("segment_route", {})]),
        _msg(content="Segment 3 ranks first."),
    ])
    assert run["status"] == "completed", run.get("error")
    assert [t["tool"] for t in run["trace"]] == ["get_route", "segment_route"]
    assert all(t["ok"] for t in run["trace"])
    assert run["result"]["brief"] == "Segment 3 ranks first."
    # The model is given the tool schemas every turn.
    assert client.calls[0]["tools"] == tools.TOOL_SCHEMAS


def test_tool_error_is_handed_back_not_fatal(monkeypatch):
    """A wrong id should let the agent correct itself, not kill the run."""
    run, _ = _run_to_completion(monkeypatch, [
        _msg(calls=[("get_route", {"route_id": "bogus"})]),
        _msg(calls=[("get_route", {"route_id": "route_a"})]),
        _msg(content="Recovered."),
    ])
    assert run["status"] == "completed"
    assert run["trace"][0]["ok"] is False
    assert "bogus" in run["trace"][0]["result_summary"]
    assert run["trace"][1]["ok"] is True


def test_runaway_loop_is_stopped(monkeypatch):
    """Never let a model spin forever against a paid or rate-limited API."""
    forever = [_msg(calls=[("segment_route", {})])
               for _ in range(orchestrator.MAX_ITERATIONS + 2)]
    run, _ = _run_to_completion(monkeypatch, forever, timeout=20.0)
    assert run["status"] == "failed"
    assert "iterations" in run["error"]


def test_trace_endpoint_shape(monkeypatch):
    run, _ = _run_to_completion(monkeypatch, [
        _msg(calls=[("get_route", {"route_id": "route_a"})]),
        _msg(content="done"),
    ])
    trace = orchestrator.get_trace(run["run_id"])
    assert trace["status"] == "completed"
    assert trace["tool_calls"][0]["tool"] == "get_route"
    for key in ("seq", "arguments", "duration_ms", "cache_hit", "result_summary"):
        assert key in trace["tool_calls"][0]


def test_missing_key_fails_the_run_with_a_useful_message(monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    run_id = orchestrator.start_run("route_a")
    import time as _t
    deadline = _t.time() + 5
    while _t.time() < deadline and orchestrator.get_run(run_id)["status"] == "running":
        _t.sleep(0.05)
    run = orchestrator.get_run(run_id)
    assert run["status"] == "failed"
    assert "API key" in run["error"]


def test_unknown_run_id_returns_none():
    assert orchestrator.get_run("nope") is None
    assert orchestrator.get_trace("nope") is None
