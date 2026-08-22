"""Draw focus is an observational layer, never a probability adjustment."""
from __future__ import annotations

import os
import sys
from pathlib import Path


os.environ.setdefault(
    "FUSION_CORE_DIR",
    r"F:/HM足球比赛预测/project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/scripts",
)
SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fusion_predict_core as fusion
import fusion_cli


def _input(include_ttg: bool) -> dict:
    payload = {
        "home": "Home", "away": "Away", "competition": "Test", "stage": "Test",
        "kickoff": "2026-08-25T20:00:00+08:00",
        "prediction_as_of": "2026-08-22T12:00:00+08:00",
        "mode": "market_only", "odds": [2.5, 3.2, 2.8],
        "field_meta": {"odds": {
            "freshness": 100, "collected_at": "2026-08-22T12:00:00+08:00",
            "source_updated_at": "2026-08-22T12:00:00+08:00",
        }},
    }
    if include_ttg:
        payload["ttg"] = {"odds": [2.0, 4.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0]}
    return payload


def test_ttg_draw_focus_is_post_prediction_research_only_and_keeps_1x2_identical():
    """TTG 标签属于预测后观察层，不能进入概率签名路径或修改 1X2。"""
    core, version = fusion.load_core()
    without_ttg = fusion.predict_one(core, version, _input(False))
    with_ttg = fusion.predict_one(core, version, _input(True))

    assert without_ttg["fusion_status"] == with_ttg["fusion_status"] == "ok"
    assert without_ttg["forecast"]["final_1x2_pct"] == with_ttg["forecast"]["final_1x2_pct"]
    assert "draw_research" not in with_ttg["forecast"]
    annotated = fusion_cli.attach_draw_research(with_ttg, _input(True))
    watch = annotated["forecast"]["draw_research"]
    assert watch["research_only"] is True
    assert watch["action"] == "observe"
    assert watch["tier"] == "focus"
    assert watch["probability_adjustment_applied"] is False
    shadow = annotated["forecast"]["draw_calibration_shadow"]
    assert shadow["research_only"] is True
    assert shadow["calibration_status"] == "UNFITTED_SHADOW"
    assert shadow["production_probability_adjustment_applied"] is False
