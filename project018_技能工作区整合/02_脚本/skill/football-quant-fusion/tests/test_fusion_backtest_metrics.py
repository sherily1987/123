from __future__ import annotations

import importlib.util
import math
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "fusion_backtest.py"
SPEC = importlib.util.spec_from_file_location("fusion_backtest_metrics", SCRIPT)
backtest = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(backtest)


def test_summary_uses_full_score_matrix_and_reports_both_total_lines():
    rows = [{
        "probs": [0.5, 0.3, 0.2], "actual_idx": 0, "actual_score": "4-0",
        # 实际比分不在展示 Top3 内；旧实现会用 1e-6 作为假概率。
        "top_scores": {"top1": 0, "top3": 0, "top5": 1},
        "score_matrix": {"1-0": 0.30, "1-1": 0.25, "0-0": 0.20, "3-0": 0.23, "4-0": 0.02},
        "ou25": {"over": 0.7, "actual": 1},
        "ou35": {"over": 0.4, "actual": 1},
        "btts": None, "clv_pp": None,
    }]

    report = backtest.summarize(rows)

    assert report["score"]["full_matrix_n"] == 1
    assert report["score"]["score_log_loss"] == round(-math.log(0.02), 5)
    assert report["ou_2_5"] == {"n": 1, "brier": 0.09, "accuracy_pct": 100.0}
    assert report["ou_3_5"] == {"n": 1, "brier": 0.36, "accuracy_pct": 0.0}


def test_summary_does_not_invent_score_logloss_from_a_topk_list():
    rows = [{
        "probs": [0.5, 0.3, 0.2], "actual_idx": 0, "actual_score": "4-0",
        "top_scores": {"top1": 0, "top3": 0, "top5": 0},
        "score_matrix": None, "ou25": None, "ou35": None,
        "btts": None, "clv_pp": None,
    }]

    report = backtest.summarize(rows)

    assert report["score"]["full_matrix_n"] == 0
    assert report["score"]["score_log_loss"] is None


def test_route_stratification_keeps_market_only_and_hybrid_separate():
    rows = [
        {"mode": "market_only", "probs": [0.5, 0.3, 0.2], "actual_idx": 0,
         "actual_score": "1-0", "top_scores": None, "score_matrix": None,
         "ou25": None, "ou35": None, "btts": None, "clv_pp": None},
        {"mode": "hybrid", "probs": [0.5, 0.3, 0.2], "actual_idx": 1,
         "actual_score": "0-0", "top_scores": None, "score_matrix": None,
         "ou25": None, "ou35": None, "btts": None, "clv_pp": None},
    ]
    report = backtest.route_stratification(rows)
    assert set(report) == {"hybrid", "market_only"}
    assert report["hybrid"]["n"] == 1
    assert report["market_only"]["n"] == 1
