from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "draw_watch_evaluation.py"


def load_evaluation():
    assert MODULE.exists(), "draw-watch evaluation module is missing"
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("draw_watch_evaluation", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_focus_metrics_are_separate_from_broader_watch_metrics():
    """focus 是 watch 的子集，报告不能把两者混成一个虚高精确率。"""
    evaluation = load_evaluation()
    rows = [
        {"tier": "watch", "actual_idx": 1},
        {"tier": "watch", "actual_idx": 0},
        {"tier": "focus", "actual_idx": 1},
        {"tier": "focus", "actual_idx": 2},
        {"tier": "none", "actual_idx": 1},
    ]

    report = evaluation.summarize_rows(rows, minimum_focus_n=3)

    assert report["all_settled"]["n"] == 5
    assert report["watch_including_focus"]["n"] == 4
    assert report["watch_including_focus"]["draw_precision"] == 0.5
    assert report["focus_only"]["n"] == 2
    assert report["focus_only"]["draw_precision"] == 0.5
    assert report["admission"]["decision"] == "hold"
    assert report["admission"]["reason_code"] == "FOCUS_SAMPLE_BELOW_MINIMUM"


def test_shadow_metrics_compare_same_match_probability_losses():
    """影子概率必须与同一场的原始概率配对比较，不能借用不同比赛作基线。"""
    evaluation = load_evaluation()
    rows = [
        {"actual_idx": 1, "probs": [0.6, 0.2, 0.2], "shadow_probs": [0.5, 0.3, 0.2]},
        {"actual_idx": 0, "probs": [0.5, 0.3, 0.2], "shadow_probs": [0.45, 0.35, 0.2]},
    ]

    metrics = evaluation.paired_shadow_metrics(rows, bootstrap_draws=100, seed=7)

    assert metrics["n"] == 2
    assert metrics["one_x2_brier_delta_shadow_minus_base"] < 0
    assert metrics["one_x2_logloss_delta_shadow_minus_base"] < 0
