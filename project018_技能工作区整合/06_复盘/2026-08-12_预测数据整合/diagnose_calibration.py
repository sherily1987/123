# -*- coding: utf-8 -*-
"""P0-2 诊断：基于修复后数据的 1X2 校准分箱（一次性诊断工具）。

读 rebuilt_map.json 映射，把占位记录替换为修复后概率，重新计算：
- 各概率段 avg_prob vs actual_rate（过自信检测）
- 分联赛对比
- ECE 汇总
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")
INT_DIR = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\06_复盘\2026-08-12_预测数据整合")


def load_map() -> dict:
    mp = json.loads((INT_DIR / "rebuilt_map.json").read_text(encoding="utf-8"))
    return mp.get("mapping", {})


def actual_1x2(h, a):
    return "H" if h > a else ("D" if h == a else "A")


def main():
    mapping = load_map()
    print("rebuilt_records=", len(mapping))

    reg = [json.loads(l) for l in (BASE / "registry.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    # 每场取最新 created_at 主记录；占位记录用修复文件替换
    by_mid = {}
    for e in reg:
        mid = e.get("match_id")
        p = Path(e.get("path", ""))
        if not p.exists():
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        core = (rec.get("output") or {}).get("core_output") or {}
        probs = core.get("final_1x2_pct")
        is_ph = isinstance(probs, list) and len(probs) == 3 and abs(probs[0] - 37.4) < 0.1 and abs(probs[2] - 37.4) < 0.1
        pid = e.get("prediction_id") or p.stem
        if is_ph and pid in mapping:
            rp = Path(mapping[pid]["rebuilt_file"])
            if rp.exists():
                try:
                    rec = json.loads(rp.read_text(encoding="utf-8"))
                except Exception:
                    pass
        ts = rec.get("created_at", "")
        if mid not in by_mid or ts > by_mid[mid].get("created_at", ""):
            by_mid[mid] = {"rec": rec, "created_at": ts}

    # 逐场评估
    rows = []
    for mid, v in by_mid.items():
        rec = v["rec"]
        rp = BASE / "results" / f"{mid}.json"
        if not rp.exists():
            continue
        try:
            rs = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            continue
        s90 = rs.get("score_90")
        if not isinstance(s90, dict) or s90.get("home") is None:
            continue
        h, a = int(s90["home"]), int(s90["away"])
        core = (rec.get("output") or {}).get("core_output") or {}
        probs = core.get("final_1x2_pct")
        if not isinstance(probs, list) or len(probs) != 3:
            continue
        m = rec.get("match") or {}
        league = m.get("competition", m.get("stage", "?"))
        rows.append({
            "mid": mid, "league": league,
            "pmax": max(probs) / 100.0, "probs": probs,
            "actual": actual_1x2(h, a),
            "score": f"{h}-{a}",
        })

    print("scorable_matches=", len(rows))

    # 分箱
    bins = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5),
            (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]
    print()
    print(f"{'bin':<10} {'n':>4} {'avg_prob':>9} {'actual':>9} {'delta_pp':>9}")
    ece = 0.0
    tot = 0
    for lo, hi in bins:
        grp = [r for r in rows if lo <= r["pmax"] < hi]
        if not grp:
            continue
        n = len(grp)
        avg = sum(r["pmax"] for r in grp) / n
        hit = 0
        for r in grp:
            idx = r["probs"].index(max(r["probs"]))
            if "HDA"[idx] == r["actual"]:
                hit += 1
        actual_rate = hit / n
        ece += n * abs(avg - actual_rate)
        tot += n
        print(f"{lo:.1f}-{hi:.1f}  {n:>4} {avg*100:>8.1f}% {actual_rate*100:>8.1f}% {100*(avg-actual_rate):>+8.1f}")
    if tot:
        print(f"ECE={ece/tot:.4f} (n={tot})")

    # 分联赛 Top 联赛
    from collections import Counter
    lc = Counter(r["league"] for r in rows)
    print()
    print("by_league:", dict(lc.most_common(8)))


if __name__ == "__main__":
    main()
