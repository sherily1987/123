from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE = Path(__file__).parents[1] / "scripts" / "draw_watch_signal.py"


def load_signal():
    assert MODULE.exists(), "draw-watch signal module is missing"
    spec = importlib.util.spec_from_file_location("draw_watch_signal", MODULE)
    signal = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(signal)
    return signal


def test_ttg_under2_uses_only_the_zero_to_two_goal_cells():
    """7+ 档不能误当作精确 7 球，0–2 概率只来自前三档。"""
    signal = load_signal()

    probability = signal.ttg_under2_probability({"odds": [2, 4, 8, 8, 8, 8, 8, 8]})

    assert probability == 7 / 12


def test_missing_ttg_keeps_watch_but_never_claims_focus():
    """TTG 缺失时可保留宽松观察，不能伪造高精度焦点标签。"""
    signal = load_signal()

    label = signal.build_draw_research([36.1, 31.8, 32.1], None)

    assert label["tier"] == "watch"
    assert label["action"] == "observe"
    assert label["ttg_under2_probability"] is None
    assert label["probability_adjustment_applied"] is False


def test_ttg_shadow_increases_only_draw_weight_and_preserves_home_away_ratio():
    """影子校准只能重权平局，主/客相对比例必须保持原样。"""
    signal = load_signal()

    shadow = signal.build_draw_calibration_shadow(
        [36.1, 31.8, 32.1], {"odds": [2, 4, 8, 8, 8, 8, 8, 8]},
    )

    probability = shadow["shadow_final_1x2_pct"]
    assert shadow["research_only"] is True
    assert shadow["calibration_status"] == "UNFITTED_SHADOW"
    assert probability[1] > 31.8
    assert probability[0] / probability[2] == pytest.approx(36.1 / 32.1)
    assert shadow["production_probability_adjustment_applied"] is False
