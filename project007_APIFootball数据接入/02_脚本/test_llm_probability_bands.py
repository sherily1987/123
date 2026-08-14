from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE = (Path(__file__).parents[2] / "project018_技能工作区整合" / "02_脚本" / "skill" /
          "football-quant-fusion" / "scripts" / "llm_probability_bands.py")
SPEC = importlib.util.spec_from_file_location("bands", MODULE)
bands = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(bands)


def test_normalize_produces_conserved_probabilities():
    out = bands.normalize({"H": "偏高", "D": "中低", "A": "很低"})
    assert abs(sum(out["probs_1x2"]) - 1.0) < 1e-12
    assert round(sum(out["probs_1x2"]), 6) == 1.0     # 引擎有概率守恒审计
    assert out["probs_1x2"][0] > out["probs_1x2"][1] > out["probs_1x2"][2]


def test_normalize_accepts_chinese_outcome_keys():
    a = bands.normalize({"主胜": "偏高", "平局": "中低", "客胜": "很低"})
    b = bands.normalize({"H": "偏高", "D": "中低", "A": "很低"})
    assert a["probs_1x2"] == b["probs_1x2"]


def test_incoherent_band_assignment_is_flagged_not_hidden():
    """三项都选「很高」是自相矛盾的档位分配。
    归一化会把它变成看似正常的概率——必须留下 coherent=False 的痕迹。"""
    out = bands.normalize({"H": "很高", "D": "很高", "A": "很高"})
    assert out["raw_sum_pct"] == pytest.approx(217.5)
    assert out["coherent"] is False
    assert abs(sum(out["probs_1x2"]) - 1.0) < 1e-12   # 仍可评分，但已标记


def test_coherent_assignment_passes():
    out = bands.normalize({"H": "中高", "D": "中低", "A": "偏低"})
    assert out["coherent"] is True
    assert bands.COHERENT_RANGE[0] <= out["raw_sum_pct"] <= bands.COHERENT_RANGE[1]


def test_rejects_unknown_band_and_incomplete_input():
    with pytest.raises(ValueError, match="未知档位"):
        bands.normalize({"H": "超高", "D": "中低", "A": "很低"})
    with pytest.raises(ValueError, match="档位不完整"):
        bands.normalize({"H": "偏高", "D": "中低"})
    with pytest.raises(ValueError, match="未知结果键"):
        bands.normalize({"X": "偏高", "D": "中低", "A": "很低"})


def test_scoring_rules_behave():
    probs = [0.6, 0.25, 0.15]
    assert bands.brier(probs, 0) < bands.brier(probs, 2)      # 猜中主胜比猜中客胜得分好
    assert bands.log_loss(probs, 0) < bands.log_loss(probs, 2)


def test_from_record_returns_none_for_legacy_records():
    """旧记录只有双选/单选，没有档位——必须返回 None 而非抛错，
    否则历史记录会让回测整体失败。"""
    legacy = {"direction": {"pick": "双选 主胜/平局（H/D）", "single_preference": "平局（D）"}}
    assert bands.from_record(legacy) is None
    new = {"direction": {"probability_bands": {"H": "偏高", "D": "中低", "A": "很低"}}}
    assert bands.from_record(new)["probs_1x2"][0] > 0.4
