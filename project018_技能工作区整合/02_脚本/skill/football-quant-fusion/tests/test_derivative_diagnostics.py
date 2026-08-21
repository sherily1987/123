from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "derivative_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("derivative_diagnostics", MODULE)
diagnostics = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(diagnostics)


def test_hafu_metrics_only_score_verified_half_time_evidence():
    rows = [
        {"match_id": "m1", "actual_score": "2-0", "actual_idx": 0, "probs": [0.6, 0.2, 0.2],
         "top_scores": {"top1": 1, "top3": 1}, "score_matrix": {"2-0": 0.3},
         "ou25": {"over": 0.7, "actual": 0}, "ou35": {"over": 0.2, "actual": 0},
         "hafu_probs": [0.5, 0.1, 0.0, 0.1, 0.1, 0.0, 0.1, 0.05, 0.05]},
        {"match_id": "m2", "actual_score": "0-0", "actual_idx": 1, "probs": [0.3, 0.4, 0.3],
         "top_scores": {"top1": 1, "top3": 1}, "score_matrix": {"0-0": 0.4},
         "ou25": {"over": 0.2, "actual": 0}, "ou35": {"over": 0.1, "actual": 0},
         "hafu_probs": [0.1] * 9},
    ]
    evidence = {
        "m1": {"status": "verified", "score_ht": {"home": 1, "away": 0}},
        "m2": {"status": "missing_half_time_score"},
    }

    report = diagnostics.evaluate_derivatives(rows, evidence)

    assert report["hafu"] == {"n": 1, "accuracy_pct": 100.0, "brier": 0.295,
                               "log_loss": 0.693147, "excluded_unverified_evidence": 1,
                               "excluded_unfitted_prediction": 0}
    assert report["ou_2_5"] == {"n": 2, "brier": 0.265, "accuracy_pct": 50.0}
    assert report["ou_3_5"] == {"n": 2, "brier": 0.025, "accuracy_pct": 100.0}


def test_row_from_prediction_preserves_unfitted_hafu_status():
    prediction = {
        "match_id": "m1",
        "output": {"forecast": {
            "hafu_model": {"prob_pct": [20, 10, 5, 10, 15, 10, 5, 10, 15],
                           "calibration_status": "UNFITTED"},
            "ou_2_5": {"over_pct": 60}, "ou_3_5": {"over_pct": 35},
        }},
    }
    settled = {"score_90": {"home": 2, "away": 1}}

    assert diagnostics.row_from_prediction(prediction, settled) == {
        "match_id": "m1", "actual_score": "2-1", "hafu_probs": [0.2, 0.1, 0.05, 0.1, 0.15, 0.1, 0.05, 0.1, 0.15],
        "hafu_status": "UNFITTED", "ou25": {"over": 0.6, "actual": 1},
        "ou35": {"over": 0.35, "actual": 0},
    }


def test_row_from_prediction_reads_legacy_top_level_derivatives():
    prediction = {
        "match_id": "m2",
        "output": {"hafu_model": {"prob_pct": [20, 10, 5, 10, 15, 10, 5, 10, 15]},
                   "ou_2_5": {"over_pct": 55}, "ou_3_5": {"over_pct": 45}},
    }
    settled = {"score_90": {"home": 0, "away": 0}}

    row = diagnostics.row_from_prediction(prediction, settled)

    assert row["hafu_status"] == "UNFITTED"
    assert row["hafu_probs"] == [0.2, 0.1, 0.05, 0.1, 0.15, 0.1, 0.05, 0.1, 0.15]
    assert row["ou25"] == {"over": 0.55, "actual": 0}
    assert row["ou35"] == {"over": 0.45, "actual": 0}


def test_ou_calibration_comparison_uses_only_same_rows():
    comparison = diagnostics.ou_calibration_comparison([
        {"ou25": {"over": 0.6, "actual": 1}, "ou25_raw": {"over": 0.5, "actual": 1}},
        {"ou25": {"over": 0.4, "actual": 0}, "ou25_raw": {"over": 0.7, "actual": 0}},
    ], "ou25")

    assert comparison == {
        "n": 2, "calibrated_brier": 0.16, "raw_brier": 0.37,
        "delta_calibrated_minus_raw": -0.21,
    }


def test_hafu_temperature_shadow_keeps_one_verified_sample_set():
    rows = [{"match_id": "m1", "actual_score": "1-0",
             "hafu_probs": [0.4, 0.1, 0.05, 0.1, 0.1, 0.05, 0.1, 0.05, 0.05]}]
    evidence = {"m1": {"status": "verified", "score_ht": {"home": 1, "away": 0}}}

    report = diagnostics.hafu_temperature_shadow(rows, evidence, temperature=1.2)

    assert report["n"] == 1
    assert report["temperature"] == 1.2
    assert report["raw"]["accuracy_pct"] == 100.0
    assert report["candidate"]["accuracy_pct"] == 100.0
