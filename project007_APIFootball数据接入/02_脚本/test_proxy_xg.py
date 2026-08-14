from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

MODULE = Path(__file__).with_name("proxy_xg.py")
SPEC = importlib.util.spec_from_file_location("proxy_xg", MODULE)
proxy_xg = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(proxy_xg)


def test_fit_recovers_known_coefficients():
    """构造数据由已知 a、b 生成，回归应能还原。"""
    rng = np.random.default_rng(42)
    inside = rng.integers(0, 20, 4000).astype(float)
    outside = rng.integers(0, 12, 4000).astype(float)
    true_a, true_b = 0.12, 0.035
    scored = rng.poisson(true_a * inside + true_b * outside).astype(float)

    a, b, converged = proxy_xg.fit_coefficients(inside, outside, scored)

    assert converged
    assert abs(a - true_a) < 0.01
    assert abs(b - true_b) < 0.01


def test_self_check_flags_total_conservation():
    inside = np.array([10.0, 10.0])
    outside = np.array([5.0, 5.0])
    scored = np.array([1.0, 1.0])
    ok = proxy_xg.self_check(0.09, 0.02, inside, outside, scored)   # 预测 2.0 实际 2.0
    bad = proxy_xg.self_check(0.30, 0.02, inside, outside, scored)  # 预测 6.2 实际 2.0
    assert ok["total_conserved"] is True
    assert bad["total_conserved"] is False


def test_self_check_flags_inside_not_greater_than_outside():
    """b>a 几乎一定是主客方向或字段映射搞反了。"""
    arr = np.array([1.0, 1.0])
    assert proxy_xg.self_check(0.02, 0.09, arr, arr, np.array([0.11, 0.11]))["primary_gt_secondary"] is False


def _write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return p


STAT_ROW = {"match_id": 1, "kickoff": "2024-03-02T20:00:00", "league_id": 152,
            "shots_inside_box": [10.0, 4.0], "shots_outside_box": [5.0, 3.0], "xg_usable": True}


def test_build_samples_skips_unusable_and_respects_train_until(tmp_path):
    stats = _write(tmp_path, "s.jsonl", [
        STAT_ROW,
        {**STAT_ROW, "match_id": 2, "xg_usable": False},                       # 切分不全，跳过
        {**STAT_ROW, "match_id": 3, "kickoff": "2025-06-01T20:00:00"},         # 超过 train_until，跳过
        {**STAT_ROW, "match_id": 4},                                           # 无对应赛果，跳过
    ])
    events = _write(tmp_path, "e.jsonl", [
        {"match_id": 1, "actual": [2, 1]}, {"match_id": 2, "actual": [0, 0]}, {"match_id": 3, "actual": [1, 1]},
    ])

    inside, outside, scored, n = proxy_xg.build_samples([stats], [events], "2025-01-01")

    assert n == 1                       # 只有 match_id=1 入选
    assert len(inside) == 2             # 一场两行（主、客）
    assert list(scored) == [2.0, 1.0]
    assert list(inside) == [10.0, 4.0]


def test_apply_writes_per_side_xg(tmp_path):
    stats = _write(tmp_path, "s.jsonl", [STAT_ROW, {**STAT_ROW, "match_id": 9, "xg_usable": False}])
    coeffs = tmp_path / "c.json"
    coeffs.write_text(json.dumps({"a_inside_box": 0.1, "b_outside_box": 0.03}), encoding="utf-8")
    out = tmp_path / "xg.jsonl"

    args = type("A", (), {"stats": stats, "coeffs": coeffs, "output": out})()
    proxy_xg.cmd_apply(args)

    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1                                   # 不可用的场次不写
    assert rows[0]["xg"] == [pytest.approx(1.15), pytest.approx(0.49)]
    assert rows[0]["data_class"] == "POST_MATCH"


def test_inside_outside_returns_none_when_fields_absent():
    """football-data.co.uk 的统计行没有禁区内外切分字段，
    取值函数必须返回 None 让上游跳过，而不是 KeyError。"""
    row = {"shots_total": [10.0, 8.0], "shots_on_target": [4.0, 3.0]}
    assert proxy_xg._inside_outside(row, 0) == (None, None)


def test_on_target_accepts_both_field_names():
    """apifootball 叫 shots_on_goal，football-data 叫 shots_on_target。"""
    a = proxy_xg._on_target({"shots_total": [10.0, 8.0], "shots_on_goal": [4.0, 3.0]}, 0)
    b = proxy_xg._on_target({"shots_total": [10.0, 8.0], "shots_on_target": [4.0, 3.0]}, 0)
    assert a == b == (4.0, 6.0)
