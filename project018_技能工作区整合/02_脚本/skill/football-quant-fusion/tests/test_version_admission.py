from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("version_admission", SCRIPTS / "version_admission.py")
admission = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(admission)


def _backtest(n=100, brier_ci=(-0.02, -0.001), logloss_ci=(-0.02, -0.001)):
    return {
        "calibration_gate": {"current_version_n": n},
        "current_paired_market": {
            "n": n,
            "brier_delta_model_minus_market": -0.01,
            "brier_delta_95ci": list(brier_ci),
            "log_loss_delta_model_minus_market": -0.01,
            "log_loss_delta_95ci": list(logloss_ci),
        },
        "current_by_league": {"英超": {"n": 12}},
        "current_identity": {"model_version": "m4", "probability_signature": "a" * 64},
    }


def test_version_admission_holds_before_one_hundred_current_samples():
    report = admission.admission_report(_backtest(n=99))

    assert report["status"] == "HOLD"
    assert "current_sample_below_minimum" in report["reasons"]
    assert report["automatic_weight_change"] is False
    assert report["production_recommendations_enabled"] is False


def test_version_admission_holds_if_either_paired_interval_crosses_zero():
    report = admission.admission_report(_backtest(logloss_ci=(-0.02, 0.001)))

    assert report["status"] == "HOLD"
    assert "logloss_ci_not_strictly_below_zero" in report["reasons"]


def test_version_admission_refuses_to_use_all_history_market_comparison():
    backtest = _backtest()
    backtest["paired_market"] = backtest.pop("current_paired_market")
    report = admission.admission_report(backtest)

    assert report["status"] == "HOLD"
    assert "current_paired_market_missing" in report["reasons"]


def test_version_admission_only_allows_human_review_after_both_metrics_clear_gate():
    report = admission.admission_report(_backtest())

    assert report["status"] == "ELIGIBLE_FOR_HUMAN_REVIEW"
    assert report["automatic_weight_change"] is False
    assert report["production_recommendations_enabled"] is False
    assert report["league_review"]["英超"]["status"] == "INSUFFICIENT"
