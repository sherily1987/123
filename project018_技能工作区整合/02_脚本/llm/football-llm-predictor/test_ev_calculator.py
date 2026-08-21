# -*- coding: utf-8 -*-
"""EV 模块方法论闸门测试（2026-08-15 修复配套）。

核心断言：没有校准概率来源时不得产出 EV；票比不得冒充概率。
"""
import json
from pathlib import Path

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
    assert "同一盘口卫生" in text
    assert "非仓位" in text


# ---- 2026-08-18：路径 A 同一盘口卫生检查（不算仓位）----

FORBIDDEN_STAKE_KEYS = frozenset({
    "kelly_fraction", "f_star", "f*", "stake", "recommended_stake",
})

# sporttery-2040931 波特诺 vs 帕梅拉斯，fusion-1.5.0-core-3.4.4 market_only
PORTENO_ODDS = [5.05, 3.05, 1.66]
PORTENO_FINAL = {"主胜": 0.15759269792706065, "平局": 0.31024153543342214,
                 "客胜": 0.5321657666395173}


def _assert_no_stake_fields(blob):
    if isinstance(blob, dict):
        assert FORBIDDEN_STAKE_KEYS.isdisjoint(blob.keys())
        for value in blob.values():
            _assert_no_stake_fields(value)
    elif isinstance(blob, list):
        for value in blob:
            _assert_no_stake_fields(value)


def _proportional_probs(odds):
    implied = [1.0 / o for o in odds]
    total = sum(implied)
    return {d: implied[i] / total for i, d in enumerate(evc.DIRECTIONS)}


def test_implied_payout_and_proportional_benchmark_are_an_identity():
    payout = evc.implied_payout(PORTENO_ODDS)
    assert payout == pytest.approx(1.0 / sum(1.0 / o for o in PORTENO_ODDS))
    audit = evc.same_book_ev_audit(_proportional_probs(PORTENO_ODDS), PORTENO_ODDS)
    assert audit["research_only"] is True
    assert audit["ev_vs_payout"] == pytest.approx(payout - 1.0)
    for ev in audit["ev_same_book"].values():
        assert ev == pytest.approx(payout - 1.0)
    assert audit["kelly_sign"] is True
    assert audit["flags"] == []
    _assert_no_stake_fields(audit)


def test_porteno_calibrated_market_only_is_all_negative():
    """真实 market_only + 平局校准：EV 不等但必须全负，不得出仓位字段。"""
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=PORTENO_ODDS, strength=1.0,
        calibrated_probs=PORTENO_FINAL, prob_source="fusion-m3-final_1x2_pct",
        prob_calibration_status="VALID", market_derived=True)
    assert rec["action"] == "skip"
    assert rec["recommended_bets"] == []
    audit = rec["same_book_audit"]
    assert audit["kelly_sign"] is True
    assert "KELLY_SANITY_FAIL" not in audit["flags"]
    assert all(ev < 0 for ev in audit["ev_same_book"].values())
    # 校准后不再等于比例去水基准（平局没那么亏），但基准仍是负的抽水
    assert audit["ev_vs_payout"] < 0
    assert audit["ev_same_book"]["平局"] != pytest.approx(audit["ev_vs_payout"], abs=0.01)
    _assert_no_stake_fields(rec)
    text = evc.format_betting_advice(rec)
    assert "KELLY_SANITY_FAIL" not in text
    assert "注额" not in text and "仓位" in text


def test_market_derived_positive_ev_is_sanity_fail_not_a_bet():
    """同一盘口若被校准推出正 EV，只加 KELLY_SANITY_FAIL，仍 skip。"""
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=ODDS, strength=1.0,
        calibrated_probs=CALIBRATED, prob_source="fusion-m2-final_1x2_pct",
        prob_calibration_status="VALID", market_derived=True)
    assert rec["action"] == "skip"
    assert rec["recommended_bets"] == []
    assert "KELLY_SANITY_FAIL" in rec["same_book_audit"]["flags"]
    assert rec["same_book_audit"]["kelly_sign"] is False
    assert rec["same_book_audit"]["ev_same_book"]["平局"] > 0
    assert "KELLY_SANITY_FAIL" in rec["reason"]
    _assert_no_stake_fields(rec)
    text = evc.format_betting_advice(rec)
    assert "KELLY_SANITY_FAIL" in text
    assert "🎯" not in text


def test_independent_positive_ev_is_not_a_sanity_fail():
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=[3.0, 3.9, 4.5], strength=1.0,
        calibrated_probs={"主胜": 0.52, "平局": 0.26, "客胜": 0.22},
        prob_source="fusion-m2-final_1x2_pct",
        prob_calibration_status="VALID", market_derived=False)
    assert rec["action"] == "bet"
    assert "KELLY_SANITY_FAIL" not in rec["same_book_audit"]["flags"]
    assert rec["same_book_audit"]["kelly_sign"] is False
    _assert_no_stake_fields(rec)


def test_no_prob_source_still_has_empty_audit_and_no_stake():
    rec = evc.generate_betting_recommendation(
        votes=UNANIMOUS, model_odds=ODDS, strength=1.0)
    assert rec["same_book_audit"] == {}
    _assert_no_stake_fields(rec)


FUSION_AUG = Path(
    r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data"
    r"\football-quant-fusion\backtest\predictions\2026\08"
)


def test_registered_market_only_records_have_no_positive_same_book_ev():
    """回放本月已登记 market_only：同一盘口不得出现正 EV，也不得带仓位字段。"""
    if not FUSION_AUG.exists():
        pytest.skip("fusion 登记库不在本机")
    files = sorted(FUSION_AUG.glob("sporttery-*__prematch.json"))
    assert files, "本月应有已登记的 prematch 记录"
    checked = 0
    failures = []
    for path in files:
        record = json.loads(path.read_text(encoding="utf-8"))
        if str(record.get("mode") or "").lower() != "market_only":
            continue
        output = record.get("output") or {}
        pct = output.get("final_1x2_pct")
        odds = (record.get("input") or {}).get("odds")
        if not (isinstance(pct, list) and len(pct) == 3
                and isinstance(odds, list) and len(odds) >= 3):
            continue
        probs = {d: pct[i] / 100.0 for i, d in enumerate(evc.DIRECTIONS)}
        audit = evc.same_book_ev_audit(probs, odds, market_derived=True)
        _assert_no_stake_fields(audit)
        if "KELLY_SANITY_FAIL" in audit["flags"] or not audit["kelly_sign"]:
            failures.append(f"{path.name} ev={audit['ev_same_book']}")
        checked += 1
    assert checked > 0
    assert not failures, "market_only 同一盘口出现正 EV:\n" + "\n".join(failures)
