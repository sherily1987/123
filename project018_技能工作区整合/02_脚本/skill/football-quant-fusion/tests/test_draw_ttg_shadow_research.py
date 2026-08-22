from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


MODULE = Path(__file__).parents[1] / "scripts" / "draw_ttg_shadow_research.py"


def load_research():
    assert MODULE.exists(), "TTG draw-shadow research module is missing"
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("draw_ttg_shadow_research", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_reweight_draw_preserves_home_away_ratio():
    """候选只能改变平局相对权重，不能扭转主客方向。"""
    research = load_research()

    adjusted = research.reweight_draw([0.4, 0.3, 0.3], 1.25)

    assert sum(adjusted) == pytest.approx(1.0)
    assert adjusted[1] > 0.3
    assert adjusted[0] / adjusted[2] == pytest.approx(0.4 / 0.3)


def test_admission_requires_all_paired_intervals_to_improve():
    """1X2、logloss、平局 Brier 任一不确定，都不能升级影子候选。"""
    research = load_research()
    paired = {
        "one_x2_brier": {"ci95_high": -0.001},
        "one_x2_logloss": {"ci95_high": -0.001},
        "draw_brier": {"ci95_high": 0.001},
    }

    decision = research.admission_decision(paired, test_n=300)

    assert decision["decision"] == "hold"
    assert decision["reason_code"] == "PAIRED_INTERVAL_NOT_DECISIVE"
