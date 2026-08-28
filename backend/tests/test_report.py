"""The evidence report and its sensitivity analysis."""

import pytest
from fastapi.testclient import TestClient

from backend import report as reporting
from backend.main import app
from backend.scoring import model

client = TestClient(app)


def _seg(i, heat, tree=5.0, amenities=None, transit=False):
    return {
        "id": f"s{i}", "index": i, "length_m": 50.0, "heat_value": heat,
        "midpoint": {"lon": -119.8 + i * 0.001, "lat": 36.75},
        "heat_tile_distance_m": 12.0,
        "landcover": {"tree": tree, "building": 70.0, "road, route": 15.0,
                      "grass": 2.0, "sidewalk, pavement": 3.0,
                      "earth, ground": 1.0},
        "context": {
            "surface": "asphalt",
            "canopy": {"tree_count": 0},
            "shelter": False,
            "building_count": 2,
            "transit_within_100m": transit,
            "water_within_m": None,
            "nearby_amenities": amenities or [],
        },
    }


def _run(segments, weights=None):
    """A completed run record, shaped as the orchestrator leaves it."""
    weights = weights or {"HEI": 0.4, "DTF": 0.2, "SVI": 0.2, "PSI": 0.2}
    scored = model.score_segments(segments, weights=weights)
    return {
        "run_id": "testrun0001",
        "status": "completed",
        "route_id": "route_a",
        "model": "groq/openai/gpt-oss-120b",
        "trace": [{"seq": 1, "tool": "get_route", "arguments": {},
                   "ok": True, "result_summary": "ok", "duration_ms": 2,
                   "cache_hit": True}],
        "segments": segments,
        "weights": scored["weights"],
        "started_at": 1000.0,
        "finished_at": 1042.0,
        "result": {
            "route": {"name": "test", "coordinates": []},
            "segments": scored["segments"],
            "degenerate_factors": scored["degenerate_factors"],
            "hps_spread": scored["hps_spread"],
            "heat_spread": scored["heat_spread"],
            "svi_source": scored["svi_source"],
            "heat_layer": {"layer": "exceedance", "units": "hour",
                           "threshold_c": 35.0},
            "brief": "…",
        },
    }


# --- sensitivity ----------------------------------------------------------

def test_sensitivity_perturbs_every_factor_both_ways():
    segs = [_seg(i, 260.0 + i, tree=float(i)) for i in range(6)]
    s = reporting.sensitivity(segs, {"HEI": 0.4, "DTF": 0.2, "SVI": 0.2, "PSI": 0.2})
    combos = {(p["factor"], p["change"]) for p in s["perturbations"]}
    assert combos == {(f, c) for f in reporting.FACTORS
                      for c in ("zeroed", "doubled")}


def test_sensitivity_reports_the_margin_to_second():
    segs = [_seg(i, 260.0 + i * 5) for i in range(4)]
    s = reporting.sensitivity(segs, {"HEI": 0.4, "DTF": 0.2, "SVI": 0.2, "PSI": 0.2})
    assert s["margin_to_second"] >= 0
    assert s["segments_within_2_HPS_of_top"] >= 1


def test_a_ranking_driven_by_one_factor_is_flagged_weight_dependent():
    """If only heat separates the segments, zeroing heat must change the
    leader — and the report has to say the order depends on the weighting."""
    segs = [_seg(i, 260.0 + i * 10) for i in range(5)]
    s = reporting.sensitivity(segs, {"HEI": 0.9, "DTF": 0.05,
                                     "SVI": 0.03, "PSI": 0.02})
    assert s["top_segment_flips"] >= 1
    assert "HEI zeroed" in s["flipped_by"]
    # The verdict must name what caused the flip, so a reader can check it.
    assert "HEI zeroed" in s["verdict"]
    assert s["verdict"].lower().startswith(("weight-dependent", "fragile"))


def test_verdict_is_always_a_sentence():
    for segs in ([_seg(i, 264.0) for i in range(4)],
                 [_seg(i, 260.0 + i * 7, tree=float(i * 3)) for i in range(6)]):
        s = reporting.sensitivity(segs, {"HEI": 0.4, "DTF": 0.2,
                                         "SVI": 0.2, "PSI": 0.2})
        assert s["verdict"].endswith(".")
        assert len(s["verdict"]) > 40


def test_zero_total_weight_perturbation_is_skipped_not_crashed():
    """Zeroing the only non-zero weight would leave nothing to normalise."""
    segs = [_seg(i, 260.0 + i) for i in range(3)]
    s = reporting.sensitivity(segs, {"HEI": 1.0, "DTF": 0.0,
                                     "SVI": 0.0, "PSI": 0.0})
    assert not any(p["factor"] == "HEI" and p["change"] == "zeroed"
                   for p in s["perturbations"])


# --- report body ----------------------------------------------------------

def test_report_carries_factors_raw_values_and_provenance():
    r = reporting.build_report(_run([_seg(i, 260.0 + i) for i in range(4)]))
    seg = r["segments"][0]
    assert set(seg["factors"]) == set(reporting.FACTORS)
    assert seg["raw"]["heat_hours"] is not None
    assert seg["raw"]["exposed_run_m"] is not None
    assert seg["land_cover_percent"]["tree"] == 5.0
    assert r["data_provenance"]["heat"]["layer"] == "exceedance"
    assert r["scoring"]["weights_used"]


def test_report_is_ordered_by_rank():
    r = reporting.build_report(_run([_seg(i, 260.0 + i * 3) for i in range(6)]))
    assert [s["rank"] for s in r["segments"]] == [1, 2, 3, 4, 5, 6]


def test_report_explains_degenerate_factors_in_words():
    r = reporting.build_report(_run([_seg(i, 264.0) for i in range(4)]))
    assert "HEI" in r["degenerate_factors"]["factors"]
    assert "no ranking information" in r["degenerate_factors"]["meaning"]


def test_report_states_that_no_cooling_figure_exists():
    """The report is the artefact a judge reads offline; it must carry the
    same claim the interface does."""
    r = reporting.build_report(_run([_seg(0, 260.0)]))
    assert r["cooling_estimates"]["stated"] is False
    assert all(i["magnitude_sourced"] in (True, False)
               for i in r["intervention_assumptions"])
    unsourced = [i for i in r["intervention_assumptions"]
                 if not i["magnitude_sourced"]]
    assert unsourced, "unsourced magnitudes must be listed, not hidden"


def test_report_lists_limitations():
    r = reporting.build_report(_run([_seg(0, 260.0)]))
    joined = " ".join(r["limitations"]).lower()
    assert "pedestrian" in joined
    assert "ground truth" in joined
    assert "point sample" in joined


def test_report_is_json_serialisable():
    import json
    r = reporting.build_report(_run([_seg(i, 260.0 + i) for i in range(3)]))
    json.dumps(r)


# --- endpoint -------------------------------------------------------------

def test_report_endpoint_404s_for_an_unknown_run():
    assert client.get("/api/report/deadbeef").status_code == 404


def test_report_endpoint_downloads_by_default(monkeypatch):
    from backend.agent import orchestrator
    run = _run([_seg(i, 260.0 + i) for i in range(3)])
    monkeypatch.setattr(orchestrator, "get_run", lambda rid: run)

    r = client.get("/api/report/testrun0001")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert ".pdf" in r.headers["content-disposition"]


def test_report_endpoint_can_render_inline(monkeypatch):
    """download=false is for viewing in a browser tab rather than saving."""
    from backend.agent import orchestrator
    run = _run([_seg(i, 260.0 + i) for i in range(3)])
    monkeypatch.setattr(orchestrator, "get_run", lambda rid: run)

    assert "inline" in client.get(
        "/api/report/testrun0001?download=false").headers["content-disposition"]
    assert "content-disposition" not in client.get(
        "/api/report/testrun0001?format=json&download=false").headers


def test_report_endpoint_refuses_an_unfinished_run(monkeypatch):
    from backend.agent import orchestrator
    monkeypatch.setattr(orchestrator, "get_run",
                        lambda rid: {"status": "running", "run_id": rid})
    assert client.get("/api/report/x").status_code == 409


@pytest.mark.parametrize("missing", ["segments", "result"])
def test_report_survives_a_sparse_run(missing, monkeypatch):
    """A failed-then-recovered run may lack pieces; the report must not 500."""
    run = _run([_seg(0, 260.0)])
    run[missing] = [] if missing == "segments" else {}
    body = reporting.build_report(run)
    assert body["run"]["run_id"] == "testrun0001"


# --- PDF ------------------------------------------------------------------

def test_pdf_renders_from_the_same_dict_as_the_json():
    """One is a rendering of the other, so they cannot disagree."""
    from backend import report_pdf
    body = reporting.build_report(_run([_seg(i, 260.0 + i) for i in range(4)]))
    pdf = report_pdf.render_pdf(body)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 4000


def test_pdf_survives_a_degenerate_route():
    from backend import report_pdf
    body = reporting.build_report(_run([_seg(i, 264.0) for i in range(4)]))
    assert report_pdf.render_pdf(body)[:5] == b"%PDF-"


def test_pdf_survives_a_single_segment_route():
    """One segment means no margin-to-second and no meaningful perturbation."""
    from backend import report_pdf
    assert report_pdf.render_pdf(
        reporting.build_report(_run([_seg(0, 260.0)])))[:5] == b"%PDF-"


def test_pdf_endpoint_is_the_default(monkeypatch):
    from backend.agent import orchestrator
    run = _run([_seg(i, 260.0 + i) for i in range(3)])
    monkeypatch.setattr(orchestrator, "get_run", lambda rid: run)

    r = client.get("/api/report/testrun0001")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert ".pdf" in r.headers["content-disposition"]
    assert r.content[:5] == b"%PDF-"


def test_json_is_still_available(monkeypatch):
    from backend.agent import orchestrator
    run = _run([_seg(i, 260.0 + i) for i in range(3)])
    monkeypatch.setattr(orchestrator, "get_run", lambda rid: run)

    r = client.get("/api/report/testrun0001?format=json")
    assert r.json()["run"]["run_id"] == "testrun0001"
    assert ".json" in r.headers["content-disposition"]


def test_unknown_format_is_rejected(monkeypatch):
    from backend.agent import orchestrator
    monkeypatch.setattr(orchestrator, "get_run",
                        lambda rid: _run([_seg(0, 260.0)]))
    assert client.get("/api/report/x?format=csv").status_code == 400


def test_the_trace_endpoint_still_exists():
    """The trace moved out of the interface panel, but spec section 9 requires
    the endpoint itself — it is how the agent's reasoning is shown live."""
    assert "/api/agent-trace/{run_id}" in {r.path for r in app.routes}


# --- structure: result, solution, conclusion ------------------------------

def test_report_names_a_solution_for_the_top_segment():
    """A ranking without a recommendation is only half an answer; the report
    has to say what to build, and from which rows of the table."""
    r = reporting.build_report(
        _run([_seg(i, 260.0 + i, transit=(i == 3)) for i in range(4)]))
    rec = r["recommendation"]

    assert rec["rank"] == 1
    assert rec["segment_id"] == r["segments"][0]["id"]
    assert rec["candidates"], "the fixture segments should match some rule"
    assert all(c["cooling_estimate"] is None for c in rec["candidates"])
    assert rec["why_this_segment"], "the choice has to show its measurements"


def test_solution_says_so_when_no_rule_applies():
    """Inventing an intervention outside the table would put an unsourced
    claim in front of a planner. Saying nothing applies is the honest output."""
    r = reporting.build_report(_run([_seg(0, 260.0, tree=20.0)]))
    rec = r["recommendation"]

    assert rec["candidates"] == []
    assert "No rule" in rec["note"]


def test_conclusion_restates_the_finding_and_its_limits():
    r = reporting.build_report(
        _run([_seg(i, 260.0 + i * 3) for i in range(5)]))
    text = " ".join(r["conclusion"])

    assert r["segments"][0]["id"] in text
    assert r["sensitivity"]["verdict"] in text
    assert "not a prediction" in text


def test_conclusion_survives_a_run_with_nothing_scored():
    r = reporting.build_report(_run_without_segments())
    assert r["conclusion"]
    assert r["recommendation"]["candidates"] == []


def _run_without_segments():
    run = _run([_seg(0, 260.0)])
    run["segments"], run["result"] = [], {}
    return run


# --- structure: the PDF's sections ----------------------------------------

def test_pdf_sections_are_numbered_and_listed_once_each():
    """The contents strip is built from the same counter as the headings, so
    a section that a run has no data for is never numbered or listed."""
    from backend.report_pdf import _Sections

    sec = _Sections()
    sec.heading("Result", "deck")
    sec.heading("Evidence — ranked segments", "deck", short="Ranked segments")
    sec.appendix("A", "what the agent did", "deck", short="Agent trace")

    assert sec.entries == ["1 Result", "2 Ranked segments", "A Agent trace"]
    assert "1 Result" in sec.strip().text


def test_pdf_gist_keeps_enough_of_a_terse_verdict():
    """"Fragile." is the whole first sentence of one verdict and tells a
    reader of the summary box nothing on its own."""
    from backend.report_pdf import _gist

    assert _gist("Fragile. The top two differ by 0.4 HPS and the leader "
                 "changes.").startswith("Fragile. The top two")
    assert _gist(None) == "—"


def test_pdf_escapes_the_agent_brief():
    """The brief is model-written prose dropped into a markup-aware renderer."""
    from backend import report_pdf

    run = _run([_seg(i, 260.0 + i) for i in range(3)])
    run["result"]["brief"] = "Trees & shade <are> the answer"
    assert report_pdf.render_pdf(reporting.build_report(run))[:5] == b"%PDF-"


def test_pdf_folds_punctuation_the_font_cannot_draw():
    """The standard PDF fonts are WinAnsi-encoded. A non-breaking hyphen — which
    the model writes constantly — has no glyph there and lands on the page as a
    black box, so it is folded to an ASCII hyphen before rendering."""
    from backend.report_pdf import _WINANSI_FALLBACK

    folded = "highest‑ranking 50‑metre​ stretch".translate(
        _WINANSI_FALLBACK)
    assert folded == "highest-ranking 50-metre stretch"
    folded.encode("cp1252")   # cp1252 is WinAnsi; nothing left the font lacks
