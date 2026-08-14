from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE = (Path(__file__).parents[2] / "project018_技能工作区整合" / "02_脚本" / "skill" /
          "football-quant-fusion" / "scripts" / "backtest_dual_track.py")
sys.path.insert(0, str(MODULE.parent))
SPEC = importlib.util.spec_from_file_location("bd", MODULE)
bd = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(bd)

TRIAL = {
    "schema": "llm-band-trial-1.0",
    "records": [
        {"match_num": "周四002", "match_id": 1001,
         "direction": {"probability_bands": {"H": "中高", "D": "中低", "A": "偏低"}},
         "prior_exposure_to_quant_model": False},
        {"match_num": "周四008", "match_id": 1002,
         "direction": {"probability_bands": {"H": "很低", "D": "偏低", "A": "很高"}},
         "prior_exposure_to_quant_model": True},
    ],
}


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_trial_format_is_loaded_with_bands_and_taint_flag(tmp_path):
    _write(tmp_path, "llm_bands_trial.json", TRIAL)
    out = bd.load_llm(tmp_path)
    # match_id 统一转字符串，与量化侧 index.json 的 "sporttery-<id>" 字符串键一致
    # （否则混入同一个 sorted(set(...)) 会因 str/int 不可比崩溃，2026-08-12 实测触发过）。
    assert set(out) == {"1001", "1002"}
    assert out["1001"]["record_format"] == "llm-band-trial-1.0"
    assert out["1001"]["tainted"] is False
    assert out["1002"]["tainted"] is True          # 登记前看过量化输出
    assert out["1001"]["bands"]["probs_1x2"][0] > out["1001"]["bands"]["probs_1x2"][2]


def test_wrong_schema_is_rejected_not_guessed(tmp_path):
    """多认一种格式的代价是契约变松；补偿是识别必须严格——
    schema 不对就报错，绝不按字段形状猜测。"""
    _write(tmp_path, "llm_bands_trial.json", {**TRIAL, "schema": "llm-band-trial-9.9"})
    with pytest.raises(ValueError, match="schema 不匹配"):
        bd.load_llm(tmp_path)


def test_missing_schema_is_rejected(tmp_path):
    _write(tmp_path, "llm_bands_trial.json", {"records": TRIAL["records"]})
    with pytest.raises(ValueError, match="schema 不匹配"):
        bd.load_llm(tmp_path)


def test_absent_trial_file_falls_back_to_standard_format(tmp_path):
    """没有试跑文件时行为与改动前完全一致。"""
    assert bd.load_llm(tmp_path) == {}


def test_standard_format_records_are_marked_and_never_tainted(tmp_path):
    _write(tmp_path, "index_llm.json",
           {"records": [{"match_id": 2001, "match_num": "周三001",
                         "llm_pick": "双选 主胜/平局（H/D）"}]})
    out = bd.load_llm(tmp_path)
    assert out["2001"]["record_format"] == "index_llm-1.0"
    assert out["2001"]["tainted"] is False
    assert out["2001"]["bands"] is None            # 旧记录无档位，按缺失处理


def test_both_formats_coexist_without_collision(tmp_path):
    _write(tmp_path, "llm_bands_trial.json", TRIAL)
    _write(tmp_path, "index_llm.json",
           {"records": [{"match_id": 2001, "match_num": "周三001", "llm_pick": "双选 主胜/平局（H/D）"}]})
    out = bd.load_llm(tmp_path)
    assert set(out) == {"1001", "1002", "2001"}
    assert {out[k]["record_format"] for k in out} == {"llm-band-trial-1.0", "index_llm-1.0"}


def test_malformed_bands_do_not_crash_the_whole_backtest(tmp_path):
    bad = {"schema": "llm-band-trial-1.0",
           "records": [{"match_id": 3001, "match_num": "X",
                        "direction": {"probability_bands": {"H": "超高", "D": "中低", "A": "很低"}}}]}
    _write(tmp_path, "llm_bands_trial.json", bad)
    out = bd.load_llm(tmp_path)
    assert "error" in out["3001"]["bands"]         # 记录错误而非抛出
    assert "未知档位" in out["3001"]["bands"]["error"]
