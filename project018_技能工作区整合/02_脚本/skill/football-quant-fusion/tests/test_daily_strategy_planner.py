from __future__ import annotations

import importlib
import sys
from datetime import datetime
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_daily_strategy_planner_module_is_available():
    """Catches removal of the auditable daily strategy planner entrypoint."""
    try:
        module = importlib.import_module("daily_strategy_planner")
    except ModuleNotFoundError:
        module = None

    assert module is not None


import daily_strategy_planner as dsp


def _job(match_id="sporttery-1"):
    return {
        "identity": {
            "match_id": match_id,
            "match_num": "周六001",
            "home": "主队",
            "away": "客队",
            "competition": "测试联赛",
            "kickoff": "2026-08-23T18:00:00+08:00",
        },
        "input": {
            "odds": [4.65, 3.45, 1.60],
            "ttg": {"odds": [10.5, 4.7, 3.0, 3.55, 6.85, 13.5, 26.0, 45.0]},
            "hafu": {"odds": [8.75, 17.0, 26.0, 10.5, 5.15, 4.2, 45.0, 17.0, 2.6]},
            "crs": {"0-0": 10.5, "0-1": 6.5, "1-1": 6.5, "1-2": 7.75},
        },
        "outputs": [{
            "track": "quant",
            "evidence_audit": {"evidence_gap": False, "evidence_status": "OK", "evidence_gap_reasons": []},
            "final_1x2_pct": [17.3, 24.3, 58.4],
            "status": "MARKET_BASELINE",
            "market_dependency_pct": 100,
            "mode": "market_only",
            "market_forecasts": {
                "TTG": {
                    "model_prob_pct": [8.0, 20.0, 26.0, 22.0, 13.0, 6.0, 3.0, 2.0],
                    "probability_source": "market_conditioned_model",
                    "independent_from_same_pool": False,
                },
                "HAFU": {
                    "model_prob_pct": [10.0, 5.0, 2.0, 8.0, 15.0, 19.0, 1.0, 5.0, 35.0],
                    "probability_source": "market_conditioned_model",
                    "independent_from_same_pool": False,
                },
                "CRS": {
                    "top_scores": [{"score": "0-1", "prob_pct": 12.0}],
                    "probability_source": "market_conditioned_model",
                    "independent_from_same_pool": False,
                },
            },
        }],
        "research": {
            "hybrid": {
                "research_only": True,
                "status": "ok",
                "final_1x2_pct": [19.2, 23.5, 57.3],
                "market_dependency_pct": 60.0,
            }
        },
    }


def _disabled_policy():
    return {
        "production_recommendations_enabled": False,
        "calibration_status": "LEGACY_RESEARCH_ONLY",
        "hhad_calibration_status": "UNFITTED",
        "production_recommendations_disabled_reason": "校准门禁未通过",
    }


def test_disabled_gate_preserves_the_entire_daily_budget():
    """Catches any branch that spends money while production is disabled."""
    plan = dsp.build_daily_strategy([_job()], _disabled_policy(), bankroll=100)

    assert plan["decision"]["action"] == "preserve_bankroll"
    assert plan["budget"] == {
        "daily_budget_amount": 100.0,
        "allocated_amount": 0.0,
        "preserved_amount": 100.0,
        "currency": "CNY",
    }
    assert plan["single_purchase_recommendations"] == []
    assert plan["combo_purchase_recommendations"] == []


def test_each_market_is_audited_against_its_own_official_odds():
    """Catches regression to deriving TTG/HAFU/CRS baselines from HAD odds."""
    plan = dsp.build_daily_strategy([_job()], _disabled_policy(), bankroll=100)
    by_market = {row["market"]: row for row in plan["market_audit"]}

    assert set(by_market) == {"HAD", "TTG", "HAFU", "CRS"}
    assert by_market["HAD"]["market_top_selection"] == "负"
    assert by_market["HAD"]["market_top_odds"] == 1.6
    assert by_market["TTG"]["market_top_selection"] == "2球"
    assert by_market["TTG"]["market_top_odds"] == 3.0
    assert by_market["HAFU"]["market_top_selection"] == "负负"
    assert by_market["HAFU"]["market_top_odds"] == 2.6
    assert by_market["CRS"]["market_top_odds"] == 6.5
    assert all(row["official_pool_used"] is True for row in by_market.values())


def test_market_conditioned_model_directions_are_visible_but_not_independent():
    """Catches model distributions being hidden or promoted to independent edge."""
    plan = dsp.build_daily_strategy([_job()], _disabled_policy(), bankroll=100)
    by_market = {row["market"]: row for row in plan["market_audit"]}

    assert by_market["HAD"]["model_top_selection"] == "负"
    assert by_market["TTG"]["model_top_selection"] == "2球"
    assert by_market["HAFU"]["model_top_selection"] == "负负"
    assert by_market["CRS"]["model_top_selection"] == "0-1"
    assert by_market["TTG"]["model_probability_source"] == "market_conditioned_model"
    assert by_market["TTG"]["independent_model_probability_pct"] is None
    assert "MARKET_CONDITIONED_MODEL" in by_market["TTG"]["block_reasons"]


def test_market_implied_probability_never_becomes_a_purchase_candidate():
    """Catches same-book implied probability being mislabeled as independent edge."""
    plan = dsp.build_daily_strategy([_job()], _disabled_policy(), bankroll=100)

    assert all(row["strategy_eligible"] is False for row in plan["market_audit"])
    ttg = next(row for row in plan["market_audit"] if row["market"] == "TTG")
    assert "MARKET_DERIVED_ONLY" in ttg["block_reasons"]
    assert ttg["independent_model_probability_pct"] is None


def test_combos_use_distinct_matches_and_only_individually_eligible_legs():
    """Catches same-match correlated legs or blocked legs entering a combo."""
    legs = [
        {"candidate_id": "a", "match_id": "m1", "strategy_eligible": True},
        {"candidate_id": "b", "match_id": "m2", "strategy_eligible": True},
        {"candidate_id": "c", "match_id": "m3", "strategy_eligible": True},
        {"candidate_id": "d", "match_id": "m1", "strategy_eligible": True},
        {"candidate_id": "x", "match_id": "m4", "strategy_eligible": False},
    ]

    combos = dsp.build_combinations(legs)

    assert {row["legs_count"] for row in combos} == {2, 3}
    assert all(len({leg["match_id"] for leg in row["legs"]}) == row["legs_count"] for row in combos)
    assert all(all(leg["strategy_eligible"] for leg in row["legs"]) for row in combos)
    assert all("x" not in {leg["candidate_id"] for leg in row["legs"]} for row in combos)


def test_production_mode_refuses_to_run_when_policy_is_disabled():
    """Catches a CLI caller forcing production output past the global gate."""
    with pytest.raises(dsp.StrategyGateError, match="production recommendations are disabled"):
        dsp.build_daily_strategy(
            [_job()], _disabled_policy(), bankroll=100, execution_mode="production"
        )


def test_independent_shadow_candidate_is_visible_but_blocked_until_calibrated():
    """Catches an unfitted independent EV candidate being hidden or made purchasable."""
    shadow = {
        "pending_paper_candidates": [{
            "match_id": "sporttery-1",
            "market": "TTG",
            "selection": "2球",
            "model_probability": 0.30,
            "decimal_ev": 0.20,
            "probability_source": "independent_prematch_lambda",
            "calibration_status": "UNFITTED_SHADOW",
            "purchase_authorized": False,
        }]
    }

    plan = dsp.build_daily_strategy(
        [_job()], _disabled_policy(), bankroll=100, independent_shadow=shadow
    )
    ttg = next(row for row in plan["market_audit"] if row["market"] == "TTG")

    assert ttg["independent_model_probability_pct"] == 30.0
    assert ttg["independent_raw_ev_pct"] == 20.0
    assert "INDEPENDENT_MODEL_UNCALIBRATED" in ttg["block_reasons"]
    assert ttg["strategy_eligible"] is False
    assert plan["budget"]["allocated_amount"] == 0.0


def test_budgeted_action_mode_spends_exactly_100_without_claiming_edge():
    jobs = [_job(f"sporttery-{index}") for index in range(1, 9)]
    plan = dsp.build_daily_strategy(
        jobs,
        _disabled_policy(),
        bankroll=100,
        execution_mode="budgeted_action",
        as_of=datetime.fromisoformat("2026-08-23T08:00:00+08:00"),
    )

    assert plan["decision"]["action"] == "purchase_recreational_budget"
    assert plan["budget"]["allocated_amount"] == 100.0
    assert plan["budget"]["preserved_amount"] == 0.0
    assert sum(row["stake_amount"] for row in plan["single_purchase_recommendations"]) == 76.0
    assert sum(row["stake_amount"] for row in plan["combo_purchase_recommendations"]) == 24.0
    assert {row["legs_count"] for row in plan["combo_purchase_recommendations"]} == {2, 3}
    assert len({row["match_id"] for row in plan["single_purchase_recommendations"]}) == 7
    assert all(row["edge_claim"] is False for row in plan["single_purchase_recommendations"])
    assert all(row["expected_value_status"] == "NOT_VALIDATED" for row in plan["single_purchase_recommendations"])
    assert plan["risk_disclosure"]["maximum_loss_amount"] == 100.0


def test_budgeted_action_mode_never_selects_started_matches():
    started = _job("sporttery-started")
    future_jobs = [_job(f"sporttery-future-{index}") for index in range(8)]
    started["identity"]["kickoff"] = "2026-08-23T07:59:00+08:00"

    plan = dsp.build_daily_strategy(
        [started, *future_jobs],
        _disabled_policy(),
        bankroll=100,
        execution_mode="budgeted_action",
        as_of=datetime.fromisoformat("2026-08-23T08:00:00+08:00"),
    )

    selected_ids = {
        row["match_id"] for row in plan["single_purchase_recommendations"]
    } | {
        leg["match_id"]
        for combo in plan["combo_purchase_recommendations"]
        for leg in combo["legs"]
    }
    assert "sporttery-started" not in selected_ids
