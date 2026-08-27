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
    assert ".json" in r.headers["content-disposition"]
    assert r.json()["run"]["run_id"] == "testrun0001"


def test_report_endpoint_can_render_inline(monkeypatch):
    from backend.agent import orchestrator
    run = _run([_seg(i, 260.0 + i) for i in range(3)])
    monkeypatch.setattr(orchestrator, "get_run", lambda rid: run)

    r = client.get("/api/report/testrun0001?download=false")
    assert "content-disposition" not in r.headers


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
