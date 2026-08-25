"""Heat Priority Score and intervention rules."""

import pytest

from backend.scoring import interventions, model


def _seg(i, heat, tree=5.0, building=70.0, road=15.0, grass=2.0,
         amenities=None, transit=False, shelter=False, water=None, length=50.0):
    return {
        "id": f"s{i}", "index": i, "length_m": length, "heat_value": heat,
        "landcover": {"tree": tree, "building": building, "road, route": road,
                      "grass": grass, "sidewalk, pavement": 3.0,
                      "earth, ground": 1.0},
        "context": {
            "nearby_amenities": amenities or [],
            "transit_within_100m": transit,
            "shelter": shelter,
            "water_within_m": water,
            "canopy": {"tree_count": 0},
        },
    }


# --- normalisation --------------------------------------------------------

def test_normalise_spreads_onto_zero_one():
    vals, degenerate = model.normalise([10.0, 20.0, 30.0])
    assert vals == [0.0, 0.5, 1.0]
    assert degenerate is False


def test_constant_factor_is_neutral_and_flagged():
    """Route B's heat grid is literally constant — min-max would divide by
    zero. A constant factor cannot rank anything, and the flag says so."""
    vals, degenerate = model.normalise([264.0, 264.0, 264.0])
    assert vals == [0.5, 0.5, 0.5]
    assert degenerate is True


def test_normalise_handles_empty():
    assert model.normalise([]) == ([], True)


# --- DTF ------------------------------------------------------------------

def test_exposed_run_spans_consecutive_exposed_segments():
    """The spec's intent is 'how long am I stuck in the sun', which per-segment
    length cannot express when segments are equal by construction."""
    svi = [0.9, 0.9, 0.9, 0.1, 0.9]
    runs = model.exposed_runs(svi, [50.0] * 5)
    assert runs[:3] == [150.0, 150.0, 150.0]
    assert runs[3] == 50.0      # shaded: only itself
    assert runs[4] == 50.0      # isolated exposed segment


def test_fully_shaded_route_gives_each_segment_its_own_length():
    runs = model.exposed_runs([0.1, 0.2, 0.1], [50.0] * 3)
    assert runs == [50.0, 50.0, 50.0]


def test_equal_length_segments_would_make_naive_dtf_useless():
    """Guards the reason DTF was redefined: identical lengths carry no signal."""
    lengths = [50.0] * 6
    naive, degenerate = model.normalise([x / 1.3 for x in lengths])
    assert degenerate is True
    runs = model.exposed_runs([0.9, 0.9, 0.1, 0.1, 0.9, 0.9], lengths)
    _, run_degenerate = model.normalise(runs)
    assert run_degenerate is False, "redefined DTF must actually vary"


# --- SVI ------------------------------------------------------------------

def test_more_canopy_lowers_svi():
    bare = model.svi_from_landcover({"tree": 0.0, "building": 80.0, "road, route": 20.0})
    treed = model.svi_from_landcover({"tree": 30.0, "building": 60.0, "road, route": 10.0})
    assert treed < bare


def test_svi_is_bounded():
    for classes in ({"tree": 100.0}, {"road, route": 100.0}, {}):
        v = model.svi_from_landcover(classes)
        assert 0.0 <= v <= 1.0


def test_shelter_reduces_svi():
    c = {"tree": 0.0, "building": 80.0, "road, route": 20.0}
    assert model.svi_from_landcover(c, shelter=True) < model.svi_from_landcover(c)


def test_svi_table_matches_the_spec_rows():
    assert model.svi_table({"tree": 50.0, "grass": 5.0}, {}) == 0.1   # park-like
    assert model.svi_table({"tree": 30.0}, {}) == 0.2                 # continuous canopy
    assert model.svi_table({"tree": 10.0}, {}) == 0.5                 # scattered trees
    assert model.svi_table({"tree": 1.0, "building": 70.0}, {}) == 0.7  # building shade
    assert model.svi_table({"tree": 0.0, "building": 10.0}, {}) == 1.0  # bare


# --- PSI ------------------------------------------------------------------

def test_psi_follows_the_spec_tiers():
    assert model.psi_from_context({"nearby_amenities": [{"type": "school"}]}) == 1.0
    assert model.psi_from_context({"transit_within_100m": True}) == 0.7
    assert model.psi_from_context({}) == 0.4


# --- scoring --------------------------------------------------------------

def test_scoring_ranks_and_bounds():
    segs = [_seg(i, 260.0 + i) for i in range(5)]
    out = model.score_segments(segs)
    ranks = sorted(s["rank"] for s in out["segments"])
    assert ranks == [1, 2, 3, 4, 5]
    assert all(0 <= s["HPS"] <= 100 for s in out["segments"])
    top = min(out["segments"], key=lambda s: s["rank"])
    assert top["HPS"] == max(s["HPS"] for s in out["segments"])


def test_weights_are_renormalised():
    segs = [_seg(i, 260.0 + i) for i in range(3)]
    out = model.score_segments(segs, weights={"HEI": 2, "DTF": 2, "SVI": 2, "PSI": 2})
    assert pytest.approx(sum(out["weights"].values())) == 1.0
    assert pytest.approx(out["weights"]["HEI"]) == 0.25


def test_constant_heat_is_reported_not_hidden():
    """The whole failure mode: a flat factor still produces a plausible map."""
    segs = [_seg(i, 264.0) for i in range(4)]
    out = model.score_segments(segs)
    assert "HEI" in out["degenerate_factors"]
    assert out["heat_spread"] == 0.0
    assert all(s["HEI"] == 0.5 for s in out["segments"])


def test_zero_weights_are_rejected():
    with pytest.raises(ValueError, match="more than zero"):
        model.score_segments([_seg(0, 1.0)],
                             weights={"HEI": 0, "DTF": 0, "SVI": 0, "PSI": 0})


def test_empty_route_is_rejected():
    with pytest.raises(ValueError, match="no segments"):
        model.score_segments([])


def test_svi_source_is_reported():
    with_lc = model.score_segments([_seg(i, 260.0 + i) for i in range(3)])
    assert with_lc["svi_source"] == "satellite"
    bare = [{**_seg(i, 260.0 + i), "landcover": None} for i in range(3)]
    assert model.score_segments(bare)["svi_source"] == "osm"


def test_amenity_proximity_raises_psi_and_score():
    near = _seg(0, 260.0, amenities=[{"type": "school", "distance_m": 20}])
    far = _seg(1, 260.0)
    out = model.score_segments([near, far])
    a, b = out["segments"]
    assert a["PSI"] == 1.0 and b["PSI"] == 0.4
    assert a["HPS"] > b["HPS"]


# --- interventions --------------------------------------------------------

def test_no_intervention_states_a_cooling_figure():
    """Spec section 6: an invented number is the fastest way to lose a judge.
    Every estimate stays null until Ameera's citation lands."""
    for rule in interventions.INTERVENTIONS:
        assert rule["cooling_estimate"] is None, rule["id"]
        assert rule["source"] is None, rule["id"]


def test_every_row_has_cost_tier_time_and_trade_off():
    for rule in interventions.INTERVENTIONS:
        assert rule["cost_tier"] in ("Low", "Medium", "High")
        assert rule["time_to_effect"]
        assert rule["trade_off"], f"{rule['id']} must name its trade-off"


def test_unsheltered_transit_stop_gets_a_shelter():
    seg = {**_seg(0, 260.0, transit=True, shelter=False), "SVI": 0.7}
    ids = [c["id"] for c in interventions.candidates_for(seg)]
    assert "shaded_shelter" in ids


def test_sheltered_stop_does_not_get_another_shelter():
    seg = {**_seg(0, 260.0, transit=True, shelter=True), "SVI": 0.7}
    assert "shaded_shelter" not in [c["id"] for c in interventions.candidates_for(seg)]


def test_long_exposed_run_without_water_gets_a_water_point():
    seg = {**_seg(0, 260.0, water=None), "SVI": 0.8, "raw": {"exposed_run_m": 250.0}}
    assert "drinking_water" in [c["id"] for c in interventions.candidates_for(seg)]


def test_water_nearby_removes_the_water_recommendation():
    seg = {**_seg(0, 260.0, water=100.0), "SVI": 0.8, "raw": {"exposed_run_m": 250.0}}
    assert "drinking_water" not in [c["id"] for c in interventions.candidates_for(seg)]


def test_well_treed_segment_is_not_told_to_plant_trees():
    seg = {**_seg(0, 260.0, tree=20.0), "SVI": 0.3, "raw": {"exposed_run_m": 50.0}}
    assert "street_trees" not in [c["id"] for c in interventions.candidates_for(seg)]


def test_agent_payload_carries_evidence_and_forbids_invention():
    seg = {**_seg(0, 260.0, transit=True), "SVI": 0.7, "HPS": 61.2, "rank": 1,
           "HEI": 1.0, "DTF": 0.5, "PSI": 0.7, "raw": {"exposed_run_m": 50.0}}
    payload = interventions.format_for_agent(seg)
    assert payload["evidence"]["tree_percent_of_image"] == 5.0
    assert "0.9%" in payload["evidence"]["units_note"]
    assert payload["factors"]["HEI"] == 1.0
    assert "Do not state any cooling figure" in payload["rules"]
    assert "inventing" in payload["rules"] or "say so" in payload["rules"]
