# -*- coding: utf-8 -*-
"""EV 模块方法论闸门测试（2026-08-15 修复配套）。

核心断言：没有校准概率来源时不得产出 EV；票比不得冒充概率。
"""
import pytest

import ev_calculator as evc

ODDS = [1.73, 3.90, 4.50]
UNANIMOUS = {"主胜": 3.0, "平局": 0.0, "客胜": 0.0}
SPLIT = {"主胜": 1.0, "平局": 1.0, "客胜": 1.0}
CALIBRATED = {"主胜": 0.52, "平局": 0.26, "客胜": 0.22}


def test_votes_to_probabilities_is_removed_not_silently_reinterpreted():
    with pytest.raises(NotImplementedError):
        evc.votes_to_probabilities(UNANIMOUS)


def test_vote_share_is_available_but_named_as_share():
    share = evc.votes_to_vote_share(SPLIT)
    assert share == pytest.approx({"主胜": 1 / 3, "平局": 1 / 3, "客胜": 1 / 3})


def test_no_probability_source_fails_closed():
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=ODDS, strength=1.0)
    assert rec["action"] == "skip"
    assert "投票比例不是概率" in rec["reason"]
    assert rec["ev_analysis"] == {}
    assert rec["recommended_bets"] == []
    assert rec["probability_source"] is None


def test_unanimous_votes_no_longer_produce_inflated_ev():
    """3:0 一致票在旧实现里 = 概率 100%，主胜 EV 变成 +73%。现在不再产出任何 EV。"""
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=ODDS, strength=1.0)
    assert rec["ev_analysis"] == {}
    shares = rec["vote_share_analysis"]
    assert shares["主胜"]["vote_share"] == 1.0
    # 票比表刻意不带 ev 键，下游误用会 KeyError 而不是拿到假数字
    assert "ev" not in shares["主胜"]


def test_probability_source_must_accompany_probabilities():
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=ODDS, strength=1.0, calibrated_probs=CALIBRATED)
    assert rec["action"] == "skip"
    assert rec["ev_analysis"] == {}


def test_calibrated_source_enables_ev_and_records_provenance():
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=ODDS, strength=1.0,
        calibrated_probs=CALIBRATED, prob_source="fusion-m2-final_1x2_pct")
    assert rec["probability_source"] == "fusion-m2-final_1x2_pct"
    assert rec["ev_analysis"]["主胜"]["predicted_prob"] == 0.52
    assert rec["ev_analysis"]["主胜"]["ev"] == pytest.approx(0.52 * 1.73 - 1)


def test_existing_risk_gates_still_apply_with_calibrated_source():
    """概率来源合格时，原有的证据缺口 / 共识不足闸门照常生效。"""
    ok_source = {"calibrated_probs": CALIBRATED, "prob_source": "fusion-m2-final_1x2_pct",
                 "prob_calibration_status": "VALID", "market_derived": False}

    gap = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=ODDS, strength=1.0, evidence_gap=True, **ok_source)
    assert gap["action"] == "skip" and "证据存在缺口" in gap["reason"]
    assert gap["recommended_bets"] == []

    weak = evc.generate_betting_recommendation(
        votes=SPLIT, model_odds=ODDS, strength=0.33, **ok_source)
    assert weak["action"] == "skip" and "共识不足" in weak["reason"]


def test_skip_output_shows_verdict_and_never_lists_recommendations():
    text = evc.format_betting_advice(evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=ODDS, strength=1.0))
    assert "🚫 不下注" in text
    assert "投票比例（非概率，不可用于 EV）" in text
    assert "🎯" not in text


def test_missing_odds_still_skips():
    rec = evc.generate_betting_recommendation(votes=UNANIMOUS, model_odds=[], strength=1.0)
    assert rec["action"] == "skip" and "赔率" in rec["reason"]


def test_find_positive_ev_bets_no_longer_takes_dead_strength_param():
    with pytest.raises(TypeError):
        evc.find_positive_ev_bets({}, max_strength_threshold=0.6)


# ---- 2026-08-16：概率来源的校准状态与市场衍生闸门 ----

def test_uncalibrated_source_yields_numbers_but_no_recommendation():
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=ODDS, strength=1.0,
        calibrated_probs=CALIBRATED, prob_source="some-model",
        prob_calibration_status="UNFITTED")
    assert rec["action"] == "skip"
    assert "未校准" in rec["reason"]
    assert rec["ev_analysis"], "未校准也要给出 EV 数字供研究"
    assert rec["recommended_bets"] == []


def test_market_derived_probabilities_never_produce_a_bet():
    """market_only 概率由同一盘口去水而来，EV 量的是水位不是 edge。"""
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=ODDS, strength=1.0,
        calibrated_probs=CALIBRATED, prob_source="fusion-m2-final_1x2_pct",
        prob_calibration_status="VALID", market_derived=True)
    assert rec["action"] == "skip"
    assert "水位" in rec["reason"]
    assert rec["ev_analysis"]
    assert rec["market_derived"] is True


def test_calibrated_independent_source_can_still_bet():
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=[3.0, 3.9, 4.5], strength=1.0,
        calibrated_probs={"主胜": 0.52, "平局": 0.26, "客胜": 0.22},
        prob_source="fusion-m2-final_1x2_pct",
        prob_calibration_status="VALID", market_derived=False)
    assert rec["action"] == "bet"
    assert rec["recommended_bets"][0]["direction"] == "主胜"


def test_default_status_is_conservative():
    """不显式声明校准状态时按未校准处理，不得出胆。"""
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=[3.0, 3.9, 4.5], strength=1.0,
        calibrated_probs=CALIBRATED, prob_source="whatever")
    assert rec["action"] == "skip"
    assert rec["probability_calibration_status"] == "UNFITTED"


def test_advice_text_shows_calibration_status_and_market_flag():
    text = evc.format_betting_advice(evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=ODDS, strength=1.0,
        calibrated_probs=CALIBRATED, prob_source="fusion-m2-final_1x2_pct",
        prob_calibration_status="VALID", market_derived=True))
    assert "校准状态 VALID" in text
    assert "市场去水反解" in text
    assert "🎯" not in text
