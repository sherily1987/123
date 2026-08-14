#!/usr/bin/env python3
"""由射门位置回归代理 xG。

模型形式（加性、identity link，因为 xG 在射门之间可加）：

    E[进球数] = a x 禁区内射门 + b x 禁区外射门

系数**必须从本仓库样本回归得到**，不得抄用网上常见常数（0.11 / 0.03 之类
是别的联赛别的年份算的）。用泊松对数似然 + scipy L-BFGS-B，环境无 statsmodels。

用法：
  python proxy_xg.py fit   --stats <a_match_stats.jsonl> [...] --events <a_events.jsonl> [...] \
                           --train-until 2025-01-01 --output coeffs.json
  python proxy_xg.py apply --stats <slug_match_stats.jsonl> --coeffs coeffs.json --output <slug>_xg.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _inside_outside(row, side):
    """字段缺失时返回 None 而非抛错——不同源的统计字段集不同
    （football-data.co.uk 完全没有禁区内外切分）。"""
    inside = (row.get("shots_inside_box") or [None, None])[side]
    outside = (row.get("shots_outside_box") or [None, None])[side]
    return inside, outside


def _inside_outside_no_pen(row, side):
    """禁区内射门剔除点球。点球只占禁区内射门约 1.8%，却按 79% 转化，
    留在样本里会系统性抬高系数 a，使运动战射门的价值被高估。"""
    taken = (row.get("penalties_taken") or [None, None])[side]
    inside = row["shots_inside_box"][side]
    if taken is None or inside is None:
        return None, None
    return max(inside - taken, 0.0), row["shots_outside_box"][side]


def _on_target(row, side):
    """射正 / 非射正（射偏+被封堵）。只有射正能进球，故 a 应远大于 b。

    两个源的字段名不同：apifootball 叫 `shots_on_goal`，
    football-data.co.uk 叫 `shots_on_target`，都要认。
    """
    on_field = row.get("shots_on_target") or row.get("shots_on_goal")
    total = (row.get("shots_total") or [None, None])[side]
    on = (on_field or [None, None])[side]
    if total is None or on is None:
        return None, None
    return on, max(total - on, 0.0)


# 口径 -> (取值函数, 两个自变量的名字)。**不同口径的系数不可互换**，
# 故 fit 会把口径写进系数文件，apply 只按文件里的口径计算。
BASES = {
    "inside_outside": (_inside_outside, ("shots_inside_box", "shots_outside_box")),
    "inside_outside_no_pen": (_inside_outside_no_pen, ("shots_inside_box_excl_penalty", "shots_outside_box")),
    "shots_on_target": (_on_target, ("shots_on_target", "shots_off_target_or_blocked")),
}
# 剔除点球的口径下，目标进球数也必须扣掉点球进球，否则两边不对齐
PENALTY_AWARE = {"inside_outside_no_pen"}
# `xg_usable` 标记是按**禁区内外切分**定义的（含 inside+outside==total 的一致性校验），
# 射正口径不依赖该切分，若沿用此过滤会把本可用的场次全部丢掉
# （实测乌超禁区切分仅 0.5% 可用，射正 92% 可用）。
BOX_SPLIT_BASES = {"inside_outside", "inside_outside_no_pen"}


def build_samples(stats_paths: list[Path], events_paths: list[Path], train_until: str | None,
                  basis: str = "inside_outside"):
    """每场比赛产出两行样本（主队一行、客队一行），主客合并拟合。"""
    goals: dict[int, list[int]] = {}
    for p in events_paths:
        for row in read_jsonl(p):
            if row.get("actual") and row.get("match_id") is not None:
                goals[row["match_id"]] = row["actual"]
    extract, _ = BASES[basis]
    inside, outside, scored, used_matches = [], [], [], set()
    needs_flag = basis in BOX_SPLIT_BASES
    for p in stats_paths:
        for row in read_jsonl(p):
            if needs_flag and not row.get("xg_usable"):
                continue
            mid = row.get("match_id")
            if mid not in goals:
                continue
            if train_until and row.get("kickoff", "")[:10] >= train_until:
                continue
            pair = [extract(row, side) for side in (0, 1)]
            if any(x is None or y is None for x, y in pair):
                continue
            pen_scored = row.get("penalties_scored") or [0, 0]
            if basis in PENALTY_AWARE and any(v is None for v in pen_scored):
                continue
            used_matches.add(mid)
            for side in (0, 1):
                inside.append(pair[side][0])
                outside.append(pair[side][1])
                goal = goals[mid][side]
                if basis in PENALTY_AWARE:
                    goal = max(goal - (pen_scored[side] or 0), 0)
                scored.append(goal)
    return (np.array(inside, dtype=float), np.array(outside, dtype=float),
            np.array(scored, dtype=float), len(used_matches))


def fit_coefficients(inside, outside, scored):
    """泊松似然下拟合 λ = a*inside + b*outside，a、b 均为正。"""
    def neg_ll(params):
        lam = np.maximum(params[0] * inside + params[1] * outside, 1e-9)
        return float(-np.sum(scored * np.log(lam) - lam))

    def grad(params):
        lam = np.maximum(params[0] * inside + params[1] * outside, 1e-9)
        common = scored / lam - 1.0
        return np.array([-np.sum(common * inside), -np.sum(common * outside)])

    res = minimize(neg_ll, np.array([0.10, 0.03]), jac=grad, method="L-BFGS-B",
                   bounds=[(1e-4, None), (1e-4, None)])
    return float(res.x[0]), float(res.x[1]), bool(res.success)


def self_check(a, b, inside, outside, scored) -> dict[str, Any]:
    """自检，任一不过要停下报告问题，不得调参硬凑。

    ⚠️ `total_conserved` **不是对模型好坏的独立检验**：identity link 且无截距时，
    一阶条件 Σ(y/λ-1)·x=0 对两个自变量各成立一次，加权相加即得 Σy=Σλ。
    也就是说总量守恒在最优解处是恒等式。它能查出的只有"优化没收敛"或
    "解被卡在边界上"，不能用来说明代理 xG 拟合得好。
    """
    predicted = float(np.sum(a * inside + b * outside))
    actual = float(np.sum(scored))
    return {
        "total_predicted": round(predicted, 1), "total_actual": round(actual, 1),
        "total_deviation_pct": round((predicted - actual) / actual * 100, 3) if actual else None,
        "total_conserved": abs(predicted - actual) / actual <= 0.02 if actual else False,
        "primary_gt_secondary": a > b,
        "primary_secondary_ratio": round(a / b, 2) if b else None,
    }


def cmd_fit(args) -> None:
    inside, outside, scored, n_matches = build_samples(args.stats, args.events, args.train_until, args.basis)
    if len(inside) < 200:
        raise SystemExit(f"样本不足（{len(inside)} 行），拒绝拟合")
    a, b, converged = fit_coefficients(inside, outside, scored)
    checks = self_check(a, b, inside, outside, scored)
    pen_rate = None
    if args.basis in PENALTY_AWARE:
        taken = won = 0
        for path in args.stats:
            for row in read_jsonl(path):
                if args.train_until and row.get("kickoff", "")[:10] >= args.train_until:
                    continue
                for i in (0, 1):
                    t_i = (row.get("penalties_taken") or [None, None])[i]
                    s_i = (row.get("penalties_scored") or [None, None])[i]
                    if t_i is not None and s_i is not None:
                        taken += t_i; won += s_i
        pen_rate = round(won / taken, 6) if taken else None
    out = {
        "model": "poisson_identity_link", "basis": args.basis,
        "formula": f"xg = a*{BASES[args.basis][1][0]} + b*{BASES[args.basis][1][1]}",
        "a_inside_box": round(a, 6), "b_outside_box": round(b, 6), "converged": converged,
        "n_rows": int(len(inside)), "n_matches": n_matches, "train_until": args.train_until,
        "sources": [p.name for p in args.stats], "self_check": checks,
        "penalty_conversion": pen_rate, "penalties_excluded": args.basis in PENALTY_AWARE,
        "note": ("系数由本仓库样本回归得到；已剔除点球，apply 时按实测转化率补回点球期望进球"
                 if args.basis in PENALTY_AWARE else
                 "系数由本仓库样本回归得到；未剔除点球，会系统性抬高 a"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not (checks["total_conserved"] and checks["primary_gt_secondary"]):
        raise SystemExit("自检未通过：总量守恒或 a>b 不成立，先查字段映射与主客方向")


def cmd_apply(args) -> None:
    coeffs = json.loads(args.coeffs.read_text(encoding="utf-8"))
    a, b = coeffs["a_inside_box"], coeffs["b_outside_box"]
    basis = coeffs.get("basis", "inside_outside")
    extract, _ = BASES[basis]
    rows = []
    needs_flag = basis in BOX_SPLIT_BASES
    for row in read_jsonl(args.stats):
        if needs_flag and not row.get("xg_usable"):
            continue
        pair = [extract(row, i) for i in (0, 1)]
        if any(x is None or y is None for x, y in pair):
            continue
        pen_rate = coeffs.get("penalty_conversion") or 0.0
        taken = row.get("penalties_taken") or [0, 0]
        xg = []
        for i in (0, 1):
            value = a * pair[i][0] + b * pair[i][1]
            if basis in PENALTY_AWARE:
                # 运动战 xG 之外，按联赛实测转化率补回点球的期望进球
                value += pen_rate * (taken[i] or 0)
            xg.append(round(value, 4))
        rows.append({
            "match_id": row["match_id"], "kickoff": row["kickoff"], "league_id": row.get("league_id"),
            "xg": xg, "coeff_source": str(args.coeffs.name), "xg_basis": basis,
            "data_class": "POST_MATCH",
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(json.dumps({"status": "ok", "count": len(rows), "output": str(args.output)}, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("--stats", type=Path, nargs="+", required=True)
    f.add_argument("--events", type=Path, nargs="+", required=True)
    f.add_argument("--train-until", help="只用该日期之前的比赛拟合，避免用到测试期信息")
    f.add_argument("--basis", choices=sorted(BASES), default="inside_outside",
                   help="射门口径。inside_outside 需禁区内外切分；shots_on_target 用于只有射正的源")
    f.add_argument("--output", type=Path, required=True)
    f.set_defaults(fn=cmd_fit)
    p = sub.add_parser("apply")
    p.add_argument("--stats", type=Path, required=True)
    p.add_argument("--coeffs", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(fn=cmd_apply)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
