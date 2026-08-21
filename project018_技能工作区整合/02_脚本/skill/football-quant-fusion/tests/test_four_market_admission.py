from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "four_market_admission.py"
SPEC = importlib.util.spec_from_file_location("four_market_admission", MODULE)
admission = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(admission)


def test_gate_holds_parameter_changes_when_each_family_lacks_its_own_evidence():
    report = admission.admission_report(
        {"calibration_gate": {"current_version_n": 64}},
        {"ou_2_5": {"n": 167}, "ou_3_5": {"n": 167},
         "hafu": {"n": 0, "excluded_unfitted_prediction": 157}},
        {"big5_candidate": {"n": 7, "score_matrix": {
            "delta_log_loss_candidate_minus_baseline": -0.00421,
        }}},
    )

    assert report["production_change_allowed"] is False
    assert report["families"]["wdl"]["decision"] == "hold"
    assert report["families"]["score"]["decision"] == "hold"
    assert report["families"]["ou"]["decision"] == "hold"
    assert report["families"]["hafu"]["decision"] == "hold"


def test_same_source_score_and_ou_time_split_can_reach_manual_review_only():
    score_time_split = {
        "schema": "sporttery-score-lambda3-1.0",
        "research_only": True,
        "test_n": 401,
        "candidate": {"lambda3": 0.2},
        "test": {
            "delta_log_loss_candidate_minus_baseline": -0.025081,
            "ou_non_regression_passed": True,
            "baseline": {"ou_2_5": {"n": 401}, "ou_3_5": {"n": 401}},
            "candidate": {"ou_2_5": {"n": 401}, "ou_3_5": {"n": 401}},
        },
    }

    report = admission.admission_report(
        {"calibration_gate": {"current_version_n": 64}},
        {"ou_2_5": {"n": 167}, "ou_3_5": {"n": 167},
         "hafu": {"n": 0, "excluded_unfitted_prediction": 157}},
        {"big5_candidate": {"n": 7, "score_matrix": {
            "delta_log_loss_candidate_minus_baseline": 0.05}}},
        score_time_split,
    )

    assert report["production_change_allowed"] is False
    assert report["families"]["score"]["decision"] == "review_required"
    assert report["families"]["ou"]["decision"] == "review_required"
