#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据驱动比赛模拟器 (Dixon-Coles 引擎)
=====================================
输入: 采集器raw json(官方赔率 HAD/TTG/CRS/HHAD)
过程: 官方赔率去水 → 反推λ → Dixon-Coles比分矩阵 → 4玩法概率 + Monte Carlo模拟
输出: 胜平负/让球/总进球/半全场概率 + 模拟N场比分统计

用法:
  python simulate_from_odds.py --input data/raw_2026-08-05.json
  python simulate_from_odds.py --input data/raw_2026-08-05.json --sim 10000 --match-id 2040727

引擎来源: Codex技能 zu-yu-dashi-3 (Dixon-Coles, 已回测校准), 直接复用不重复建设。
"""

import argparse
import json
import os
import random
import sys

# 复用 zu-yu-dashi-3 的 Dixon-Coles 引擎
ENGINE_DIR = os.path.expanduser(
    r"~/.codex/skills/zu-yu-dashi-3/scripts")
sys.path.insert(0, ENGINE_DIR)
import predict as dc  # noqa: E402  (pmf/matrix/one/devig/market_lam/settle)


def devig_probs(odds):
    """赔率列表 → 去水概率。"""
    probs, _ = dc.devig(odds)
    return probs


def ttg_expected(ttg):
    """官方总进球赔率 → 期望总进球数(7+按7.5)。"""
    keys = ["0", "1", "2", "3", "4", "5", "6", "7+"]
    vals = [0, 1, 2, 3, 4, 5, 6, 7.5]
    odds = [ttg[k] for k in keys if k in ttg]
    if len(odds) < 4:
        return 2.45  # 缺数据用默认
    probs, _ = dc.devig(odds)
    return sum(p * v for p, v in zip(probs, vals))


def score_matrix(lh, la):
    """λ → Dixon-Coles 比分分布(0-7+)。"""
    return dc.matrix(lh, la, rho=-0.08, n=9)


def ttg_probs(m):
    """比分分布 → 总进球概率(0-7+)。"""
    out = {}
    for (i, j), v in m.items():
        t = i + j
        k = "7+" if t >= 7 else str(t)
        out[k] = out.get(k, 0) + v
    return out


def hafu_probs(m, lh, la):
    """半全场九宫格概率(泊松增量近似: 半场λ=45%, 剩余55%独立)。"""
    ht = dc.matrix(lh * 0.45, la * 0.45, rho=-0.04, n=5)
    rem = dc.matrix(lh * 0.55, la * 0.55, rho=-0.04, n=5)
    names = {"hh": "胜胜", "hd": "胜平", "ha": "胜负", "dh": "平胜",
             "dd": "平平", "da": "平负", "ah": "负胜", "ad": "负平",
             "aa": "负负"}
    out = {k: 0.0 for k in names}
    for (hi, hj), ph in ht.items():
        h_out = "主胜" if hi > hj else "客胜" if hi < hj else "平局"
        for (ri, rj), pr in rem.items():
            fi, fj = hi + ri, hj + rj
            f_out = "主胜" if fi > fj else "客胜" if fi < fj else "平局"
            combo = {"主胜": {"主胜": "hh", "平局": "hd", "客胜": "ha"},
                     "平局": {"主胜": "dh", "平局": "dd", "客胜": "da"},
                     "客胜": {"主胜": "ah", "平局": "ad", "客胜": "aa"}}[h_out][f_out]
            out[combo] += ph * pr
    s = sum(out.values())
    return {names[k]: v / s for k, v in out.items()}


def monte_carlo(m, n, hhad_line=0):
    """从比分分布采样模拟n场比赛。"""
    pairs = list(m.keys())
    weights = list(m.values())
    sim = {"home_w": 0, "draw": 0, "away_w": 0, "scores": {}}
    hh = {"hhad_home": 0, "hhad_draw": 0, "hhad_away": 0, "total": {k: 0 for k in
          ("0", "1", "2", "3", "4", "5", "6", "7+")}}
    for _ in range(n):
        i, j = random.choices(pairs, weights=weights, k=1)[0]
        if i > j:
            sim["home_w"] += 1
        elif i < j:
            sim["away_w"] += 1
        else:
            sim["draw"] += 1
        key = f"{i}-{j}"
        sim["scores"][key] = sim["scores"].get(key, 0) + 1
        z = i - j + hhad_line
        if z > 0:
            hh["hhad_home"] += 1
        elif z < 0:
            hh["hhad_away"] += 1
        else:
            hh["hhad_draw"] += 1
        t = "7+" if i + j >= 7 else str(i + j)
        hh["total"][t] += 1
    return sim, hh


def analyze_match(m, verbose=True):
    """单场比赛: 赔率 → 完整分析。"""
    mo = m.get("model_odds") or []
    hhad = m.get("model_hhad") or {}
    ttg = m.get("ttg") or {}
    if len(mo) < 3:
        return None

    p1x2 = devig_probs(mo)                    # 官方去水概率
    total = ttg_expected(ttg) if ttg else 2.45
    lh, la = dc.market_lam(p1x2, total)       # 反推λ
    mat = score_matrix(lh, la)                # Dixon-Coles 矩阵
    model_1x2 = dc.one(mat)                   # 引擎1X2
    top_scores = dc.top(mat, 6)
    line = hhad.get("line", 0) if hhad else 0
    hhad_p = list(dc.settle(mat, float(line)))[:3] if hhad else None
    ttgp = ttg_probs(mat)
    hafu = hafu_probs(mat, lh, la)

    return {"match_num": m.get("match_num"), "home": m["home"], "away": m["away"],
            "lambda": [round(lh, 3), round(la, 3)], "goal_total": round(total, 2),
            "market_1x2": [round(x * 100, 1) for x in p1x2],
            "model_1x2": [round(x * 100, 1) for x in model_1x2],
            "top_scores": top_scores, "hhad": {"line": line,
            "probs": [round(x * 100, 1) for x in hhad_p]} if hhad_p else None,
            "ttg": {k: round(v * 100, 1) for k, v in
                    sorted(ttgp.items(), key=lambda x: x[0])},
            "hafu_top": sorted(hafu.items(), key=lambda x: -x[1])[:5],
            "mat": mat,
            "model": m}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--sim", type=int, default=10000, help="Monte Carlo 次数")
    ap.add_argument("--match-id", type=int, default=None)
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    matches = data["matches"]
    if args.match_id:
        matches = [m for m in matches if m["match_id"] == args.match_id]

    for i, m in enumerate(matches, 1):
        r = analyze_match(m)
        if not r:
            print(f"跳过 {m.get('home')} vs {m.get('away')}: 缺赔率")
            continue
        print("=" * 66)
        print(f"⚽ [{r['match_num']}] {r['home']} VS {r['away']}")
        print(f"   λ主={r['lambda'][0]} λ客={r['lambda'][1]} 期望总进球={r['goal_total']}")
        print(f"   官方1X2: 主{r['market_1x2'][0]}% 平{r['market_1x2'][1]}% "
              f"客{r['market_1x2'][2]}%  | 引擎: 主{r['model_1x2'][0]}% "
              f"平{r['model_1x2'][1]}% 客{r['model_1x2'][2]}%")
        print(f"   引擎Top比分: " + " ".join(
            f"{s['score']}({s['prob_pct']}%)" for s in r["top_scores"]))
        if r["hhad"]:
            print(f"   让球({r['hhad']['line']:+g}): 主{r['hhad']['probs'][0]}% "
                  f"平{r['hhad']['probs'][1]}% 客{r['hhad']['probs'][2]}%")
        tg = r["ttg"]
        best = max(tg, key=lambda k: tg[k])
        print(f"   总进球: " + " ".join(f"{k}球:{v}%" for k, v in tg.items()) +
              f"  | 最可能:{best}球")
        print(f"   半全场Top5: " + " | ".join(
            f"{k}:{v*100:.1f}%" for k, v in r["hafu_top"]))
        # Monte Carlo
        sim, hh = monte_carlo(r["mat"], args.sim,
                              r["hhad"]["line"] if r["hhad"] else 0)
        print(f"   [模拟{args.sim}场] 主胜{sim['home_w']/args.sim*100:.1f}% "
              f"平{sim['draw']/args.sim*100:.1f}% "
              f"客胜{sim['away_w']/args.sim*100:.1f}% | "
              f"模拟比分Top5: " + " ".join(
                  f"{k}({v/args.sim*100:.1f}%)"
                  for k, v in sorted(sim['scores'].items(),
                                     key=lambda x: -x[1])[:5]))


if __name__ == "__main__":
    main()
