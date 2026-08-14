# -*- coding: utf-8 -*-
"""P2-1 LLM 轨市场配对基线（2026-08-12，一次性分析工具）。

目标：LLM 轨 46 场结算不再"无对照"——用同场体彩 HAD 去水概率作为市场基线，
对比 LLM 双选/单选 vs 市场 argmax 的命中率。样本 33 场（其中 29 场可配对），
仍远低于 100 场门槛，只报告命中统计与分歧，不下优劣结论。
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")
INT_DIR = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\06_复盘\2026-08-12_预测数据整合")


def devig(odds):
    inv = [1.0 / x for x in odds]
    s = sum(inv)
    return [x / s for x in inv]


def actual_1x2(h, a):
    return "H" if h > a else ("D" if h == a else "A")


def main():
    # 1. LLM 结算明细
    data = json.loads((INT_DIR / "scattered_llm_backtest.json").read_text(encoding="utf-8"))
    detail = data["detail"]
    llm_rows = {x["match_id"]: x for x in detail if x.get("actual")}

    # 2. 主库赔率（每场取最新快照的 odds）
    reg = [json.loads(l) for l in (BASE / "registry.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    mid_odds = {}
    for e in reg:
        mid = e.get("match_id")
        if mid in mid_odds:
            continue
        p = Path(e.get("path", ""))
        if not p.exists():
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        inp = rec.get("input") or {}
        if inp.get("odds") and len(inp["odds"]) == 3:
            mid_odds[mid] = inp["odds"]

    # 3. 配对统计
    stats = {
        "llm_double": {"n": 0, "hit": 0},
        "llm_single": {"n": 0, "hit": 0},
        "market_argmax": {"n": 0, "hit": 0},
        "market_argmax_not_draw": {"n": 0, "hit": 0},
    }
    rows_out = []
    for mid, r in llm_rows.items():
        odds = mid_odds.get(mid)
        if not odds:
            continue
        mp = devig(odds)
        mkt_idx = max(range(3), key=lambda i: mp[i])
        mkt_pick = "HDA"[mkt_idx]
        # actual 是比分字符串 "0-1"，需解析为 H/D/A
        try:
            hs, as_ = r["actual"].split("-")
            actual = actual_1x2(int(hs), int(as_))
        except Exception:
            continue
        mkt_hit = mkt_pick == actual
        # 双选（LLM 双选含市场 argmax 时排除"沾光"口径：只计 LLM 双选不含市场项的情况）
        double = set()
        if r.get("llm_pick"):
            import re
            m = re.search(r"[（(]([HDA/]+)[）)]", r["llm_pick"])
            if m:
                double = {c for c in m.group(1).split("/") if c in "HDA"}
        dbl_hit = bool(double) and actual in double
        single = None
        m2 = re.search(r"[（(]([HDA])[）)]", r.get("llm_pick") or "")
        if m2:
            single = m2.group(1)
        sgl_hit = single == actual

        stats["llm_double"]["n"] += 1
        if dbl_hit:
            stats["llm_double"]["hit"] += 1
        if single:
            stats["llm_single"]["n"] += 1
            if sgl_hit:
                stats["llm_single"]["hit"] += 1
        stats["market_argmax"]["n"] += 1
        if mkt_hit:
            stats["market_argmax"]["hit"] += 1
        if mkt_pick != "D":
            stats["market_argmax_not_draw"]["n"] += 1
            if mkt_hit:
                stats["market_argmax_not_draw"]["hit"] += 1

        rows_out.append({
            "match_id": mid, "actual": actual,
            "llm_pick": r.get("llm_pick"), "llm_double_hit": dbl_hit,
            "llm_single_hit": sgl_hit,
            "market_pick": mkt_pick, "market_hit": mkt_hit,
            "odds": odds, "market_prob": [round(x * 100, 1) for x in mp],
            "disagree": (single != mkt_pick if single else None),
        })

    def rate(s):
        return round(100.0 * s["hit"] / s["n"], 2) if s["n"] else None

    summary = {
        "schema": "llm-market-paired-baseline-1.0",
        "paired_n": len(rows_out),
        "stats": {k: {**v, "hit_rate_pct": rate(v)} for k, v in stats.items()},
    }
    out = INT_DIR / "llm_market_paired_baseline.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows_out}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    # 分歧示例
    disag = [r for r in rows_out if r.get("disagree")]
    print("LLM单选 vs 市场方向分歧场次=", len(disag))
    for r in disag[:6]:
        print(f"  {r['match_id']} | LLM={r['llm_pick']} | 市场={r['market_pick']} | 实际={r['actual']}")


if __name__ == "__main__":
    main()
