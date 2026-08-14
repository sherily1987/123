from __future__ import annotations

import importlib.util
import math
import random
from pathlib import Path

import pytest

MODULE = Path(__file__).with_name("cross_league_calibration.py")
SPEC = importlib.util.spec_from_file_location("cc", MODULE)
cc = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(cc)


def _synthetic(true_offsets, adv=0.2, n_per_pair=260, seed=7):
    """按已知偏移合成欧战比赛，检验能否反解出来。

    每个联赛给两支 α=β=0 的球队，于是进球差异**只来自联赛偏移**。
    """
    rng = random.Random(seed)
    leagues = sorted(true_offsets)
    table = {}
    for lg in leagues:
        for k in range(2):
            table[f"{lg}#{k}"] = (lg, 0.0, 0.0)
    rows = []
    teams = list(table)
    for _ in range(n_per_pair):
        h, a = rng.sample(teams, 2)
        sh, sa = true_offsets[table[h][0]], true_offsets[table[a][0]]
        lam_h = math.exp(adv + sh - sa)
        lam_a = math.exp(sa - sh)
        rows.append({"home": h, "away": a, "day": len(rows),
                     "gh": _poisson(rng, lam_h), "ga": _poisson(rng, lam_a),
                     "comp": "uefa_champions_league"})
    return table, rows, leagues


def _poisson(rng, lam):
    """Knuth 采样，避免引入 numpy 随机源。"""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def test_fit_offsets_recovers_known_league_strength_gaps():
    true = {"strong": 0.30, "mid": 0.00, "weak": -0.30}
    table, rows, leagues = _synthetic(true, n_per_pair=3000)

    fitted = cc.fit_offsets(rows, table, leagues, calibrate=True)

    assert fitted["converged"]
    # 排序必须还原，数值允许采样误差
    order = sorted(leagues, key=lambda lg: -fitted["offsets"][lg])
    assert order == ["strong", "mid", "weak"]
    for lg in leagues:
        assert fitted["offsets"][lg] == pytest.approx(true[lg], abs=0.06)


def test_offsets_sum_to_zero_by_construction():
    """Σs=0 是归一化约束；否则整体水平与 adv 不可辨识。"""
    table, rows, leagues = _synthetic({"a": 0.2, "b": -0.1, "c": -0.1}, n_per_pair=400)
    fitted = cc.fit_offsets(rows, table, leagues, calibrate=True)
    assert sum(fitted["offsets"].values()) == pytest.approx(0.0, abs=1e-8)


def test_naive_mode_keeps_all_offsets_zero_but_still_fits_home_adv():
    """对照组也必须拟合 adv，否则改善会被误归因到联赛偏移。"""
    table, rows, leagues = _synthetic({"a": 0.3, "b": -0.3}, n_per_pair=600)
    naive = cc.fit_offsets(rows, table, leagues, calibrate=False)
    assert set(naive["offsets"].values()) == {0.0}
    assert naive["home_adv"] != 0.0


def test_calibrated_beats_naive_on_synthetic_data():
    """联赛间确有强弱差时，校准版的似然必须更好。"""
    true = {"strong": 0.35, "weak": -0.35}
    table, rows, leagues = _synthetic(true, n_per_pair=1500)
    naive = cc.fit_offsets(rows, table, leagues, calibrate=False)
    calib = cc.fit_offsets(rows, table, leagues, calibrate=True)

    def brier(params):
        scored = cc.evaluate(rows, table, params)
        return sum(sum((r["model"][i] - (1 if i == r["actual_idx"] else 0)) ** 2
                       for i in range(3)) for r in scored) / len(scored)

    assert brier(calib) < brier(naive)


def test_evaluate_carries_market_baseline_through():
    table, rows, leagues = _synthetic({"a": 0.1, "b": -0.1}, n_per_pair=40)
    rows[0]["provider_market"] = [0.5, 0.3, 0.2]
    params = cc.fit_offsets(rows, table, leagues, calibrate=True)
    scored = cc.evaluate(rows, table, params)
    assert scored[0]["provider_market"] == [0.5, 0.3, 0.2]
    assert "provider_market" not in scored[1]


def test_league_groups_pools_leagues_with_too_few_uefa_matches():
    """欧战只有个位数场次的联赛不能各占一个自由参数——实测波黑 2 场、拉脱维亚 4 场，
    那样估出来的是任意值，且 Σs=0 会让噪声参数污染其余联赛。"""
    table, rows, _ = _synthetic({"big": 0.2, "tiny": -0.2}, n_per_pair=60)
    # 人为把 tiny 的出场压到阈值以下
    rows = [r for r in rows if not (table[r["home"]][0] == "tiny" and table[r["away"]][0] == "tiny")][:80]
    counts = {}
    for r in rows:
        for side in ("home", "away"):
            counts[table[r[side]][0]] = counts.get(table[r[side]][0], 0) + 1

    mapping, groups, got = cc.league_groups(rows, table, min_matches=10 ** 6)

    assert set(mapping.values()) == {cc.POOLED}      # 全部低于阈值 -> 全部并池
    assert groups == [cc.POOLED]
    assert got == counts


def test_pooled_leagues_share_one_offset():
    table, rows, _ = _synthetic({"a": 0.3, "b": -0.15, "c": -0.15}, n_per_pair=900)
    mapping = {"a": "a", "b": cc.POOLED, "c": cc.POOLED}
    groups = sorted(set(mapping.values()))

    fitted = cc.fit_offsets(rows, table, groups, calibrate=True, mapping=mapping)

    # 逐联赛视图里 b、c 取同一个值；组视图只有两个参数
    assert fitted["offsets"]["b"] == fitted["offsets"]["c"]
    assert set(fitted["group_offsets"]) == {"a", cc.POOLED}
    assert fitted["offsets"]["a"] > fitted["offsets"]["b"]
