from __future__ import annotations

import recommendation_policy as rp


def _core(hhad_probs, final_1x2=(37.2, 30.3, 32.5), status="MARKET_BASELINE"):
    return {
        "final_1x2_pct": list(final_1x2),
        "fusion_decision": {"status": status, "market_dependency_pct": 100,
                             "edge_significant_vs_sensitivity": True},
        "sporttery_hhad_3way": {"line": -1.0, "model_prob_pct": list(hhad_probs)},
        "reliability_flags": [],
    }


def test_hhad_recommendation_stays_shadow_without_independent_calibration():
    result = rp.evaluate(_core([16.8, 20.7, 62.6]))
    rec = result["hhad_recommendation"]
    assert rec["available"] is True
    assert rec["primary_pick"] == "让负"
    assert rec["banker_allowed"] is False
    assert rec["confidence_pct"] is None
    assert rec["raw_primary_probability"] == 0.626
    assert "HHAD_UNCALIBRATED" in rec["reasons"]
    assert "ONE_GOAL_RISK_BLOCK" in rec["reasons"]


def test_hhad_recommendation_withheld_below_threshold():
    rec = rp.evaluate(_core([34.0, 33.0, 33.0]))["hhad_recommendation"]
    assert rec["banker_allowed"] is False
    assert rec["confidence_pct"] is None


def test_hhad_recommendation_unavailable_without_hhad_data():
    core = _core([16.8, 20.7, 62.6])
    core["sporttery_hhad_3way"] = {}
    rec = rp.evaluate(core)["hhad_recommendation"]
    assert rec["available"] is False
    assert rec["primary_pick"] is None


def test_hhad_recommendation_blocked_when_status_unfitted():
    rec = rp.evaluate(_core([16.8, 20.7, 62.6], status="UNFITTED_NO_VALUE"))["hhad_recommendation"]
    assert rec["banker_allowed"] is False


def test_market_baseline_never_promotes_raw_probability_to_banker():
    result = rp.evaluate(_core([12.0, 20.0, 68.0], final_1x2=(60.0, 22.0, 18.0)))
    assert result["banker_allowed"] is False
    assert result["raw_primary_probability"] == 0.6
    assert result["confidence_pct"] is None
    assert "STATUS_NOT_REVIEWABLE:MARKET_BASELINE" in result["reasons"]


def test_avoid_data_risk_fails_closed_even_above_threshold():
    result = rp.evaluate(_core([12.0, 20.0, 68.0], final_1x2=(60.0, 22.0, 18.0),
                               status="AVOID_DATA_RISK"))
    assert result["banker_allowed"] is False
    assert "STATUS_NOT_REVIEWABLE:AVOID_DATA_RISK" in result["reasons"]


def test_global_recommendation_switch_fails_closed():
    core = _core([30.0, 32.0, 38.0], final_1x2=(55.0, 25.0, 20.0), status="EDGE_REVIEWABLE")
    core["fusion_decision"]["market_dependency_pct"] = 50
    result = rp.evaluate(core)
    assert result["banker_allowed"] is False
    assert result["production_recommendations_enabled"] is False
    assert "PRODUCTION_RECOMMENDATIONS_DISABLED" in result["reasons"]


def test_no_significant_edge_and_high_market_dependency_fail_closed():
    core = _core([30.0, 32.0, 38.0], final_1x2=(55.0, 25.0, 20.0), status="EDGE_REVIEWABLE")
    core["fusion_decision"].update(edge_significant_vs_sensitivity=False, market_dependency_pct=90)
    result = rp.evaluate(core)
    assert result["banker_allowed"] is False
    assert "EDGE_NOT_SIGNIFICANT" in result["reasons"]
    assert "MARKET_DEPENDENCY_TOO_HIGH" in result["reasons"]
