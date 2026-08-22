from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "draw_policy_research.py"


def load_module():
    assert MODULE.exists(), "draw-policy research module is missing"
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("draw_policy_research", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_draw_override_selects_draw_only_within_margin():
    """距离胜/负最高概率太远时，研究标签不得强行改为平局。"""
    research = load_module()

    assert research.choose_label((0.45, 0.40, 0.15), draw_margin=0.05) == 1
    assert research.choose_label((0.45, 0.39, 0.16), draw_margin=0.05) == 0


def test_margin_selection_is_training_only_and_preserves_research_boundary():
    """阈值只能按训练期选取，且输出必须明确不改变生产概率。"""
    research = load_module()
    rows = [
        {"probabilities": (0.45, 0.40, 0.15), "actual": 1},
        {"probabilities": (0.45, 0.39, 0.16), "actual": 0},
        {"probabilities": (0.40, 0.38, 0.22), "actual": 1},
        {"probabilities": (0.40, 0.36, 0.24), "actual": 2},
    ]

    selected = research.select_margin(
        rows,
        margins=(0.0, 0.05),
        max_overall_accuracy_loss=0.005,
        min_draw_precision=0.30,
    )

    assert selected["margin"] == 0.05
    assert selected["research_only"] is True
    assert selected["production_probabilities_changed"] is False
    assert selected["metrics"]["draw_precision"] == 2 / 3
