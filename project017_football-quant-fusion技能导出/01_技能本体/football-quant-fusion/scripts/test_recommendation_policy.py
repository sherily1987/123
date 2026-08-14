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


def test_hhad_recommendation_picks_argmax_above_threshold():
    result = rp.evaluate(_core([16.8, 20.7, 62.6]))
    rec = result["hhad_recommendation"]
    assert rec["available"] is True
    assert rec["primary_pick"] == "让负"
    assert rec["banker_allowed"] is True
    assert rec["confidence_pct"] == 0.626


def test_hhad_recommendation_withheld_below_threshold():
    # 三项都在50%以下，不出胆
    result = rp.evaluate(_core([34.0, 33.0, 33.0]))
    rec = result["hhad_recommendation"]
    assert rec["banker_allowed"] is False
    assert rec["confidence_pct"] is None


def test_hhad_recommendation_unavailable_without_hhad_data():
    core = _core([16.8, 20.7, 62.6])
    core["sporttery_hhad_3way"] = {}
    result = rp.evaluate(core)
    rec = result["hhad_recommendation"]
    assert rec["available"] is False
    assert rec["primary_pick"] is None


def test_hhad_recommendation_blocked_when_status_unfitted():
    result = rp.evaluate(_core([16.8, 20.7, 62.6], status="UNFITTED_NO_VALUE"))
    rec = result["hhad_recommendation"]
    assert rec["banker_allowed"] is False


def test_hhad_recommendation_is_independent_field_not_overwriting_1x2():
    # 让球推荐是独立字段，不应该覆盖原有1X2出胆逻辑（顶层 banker_allowed 仍是1X2的）。
    # 1X2主胜37.2%<50%阈值，1X2本身不出胆；但让负62.6%>=50%，让球轨可以独立出胆——
    # 两者用同一阈值但分别判定，互不覆盖。
    result = rp.evaluate(_core([16.8, 20.7, 62.6]))
    assert result["banker_allowed"] is False
    assert result["hhad_recommendation"]["banker_allowed"] is True
