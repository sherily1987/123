from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "tune_score_sporttery.py"
SPEC = importlib.util.spec_from_file_location("tune_score_sporttery", MODULE)
tune = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(tune)


def test_full_matrix_candidate_uses_raw_matrix_and_separate_rank_metrics():
    rows = [
        {"day": "2026-01-01" if index <= 8 else f"2026-01-{index - 6:02d}",
         "lambdas": (1.5, 0.8), "actual_score": "1-0"}
        for index in range(1, 12)
    ]

    report = tune.fit_report(rows, lambda_grid=(0.05, 0.15), min_test_n=2)

    assert report["production_unchanged"] is True
    assert report["baseline"]["lambda3"] == 0.05
    assert report["baseline"]["score_matrix_temperature"] == 1.0
    assert report["candidate"]["score_matrix_temperature"] == 1.0
    assert report["candidate"]["top_scores_temperature"] is None
    assert report["train_end"] < report["test_start"]
    assert report["test"]["baseline"]["score_matrix"]["n"] == 3
    assert report["test"]["candidate"]["score_matrix"]["n"] == 3
    assert report["test"]["baseline"]["ou_2_5"]["n"] == 3
    assert report["test"]["candidate"]["ou_3_5"]["n"] == 3


def test_default_lambda3_grid_does_not_stop_at_current_release_value():
    """研究网格不能把当前 λ3=0.20 人为当成可搜索上限。"""
    assert 0.20 in tune.LAMBDA3_GRID
    assert max(tune.LAMBDA3_GRID) > 0.20


def test_time_split_report_includes_paired_score_and_ou_uncertainty():
    """比分/大小球候选必须在同场配对差异上报告不确定性。"""
    rows = [
        {"day": f"2026-02-{index:02d}", "lambdas": (1.5, 0.8), "actual_score": "1-0"}
        for index in range(1, 11)
    ]

    report = tune.fit_report(
        rows, lambda_grid=(0.05, 0.15), min_test_n=2, bootstrap_draws=100, bootstrap_seed=7,
    )

    paired = report["test"]["paired_bootstrap"]
    assert paired["score_log_loss"]["draws"] == 100
    assert set(paired) == {"score_log_loss", "ou_2_5_brier", "ou_3_5_brier"}


def test_paired_ci_gate_rejects_candidate_when_one_ou_interval_crosses_zero():
    """共享 λ3 影响两条大小球线，任一线不确定就不能宣称整体提升。"""
    paired = {
        "score_log_loss": {"ci95_high": -0.001},
        "ou_2_5_brier": {"ci95_high": -0.002},
        "ou_3_5_brier": {"ci95_high": 0.001},
    }

    assert tune.paired_ci_supports_full_candidate(paired) is False
