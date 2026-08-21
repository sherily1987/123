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
