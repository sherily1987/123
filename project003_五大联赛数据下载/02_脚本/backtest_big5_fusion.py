#!/usr/bin/env python3
"""五大联赛融合登记样本回测评估（融合 payload 感知）。

读取融合注册库中指定 snapshot（默认 closing）且已结算的五大联赛样本：
- 模型概率：output.core_output.final_1x2_pct（market_only 时=去水市场概率）
- 市场基线：output.core_output.market_prob_pct（power 去水）
- 指标：Brier / Log Loss / ECE(10桶) / argmax命中率，按联赛+总体输出

用法:
  python backtest_big5_fusion.py
  python backtest_big5_fusion.py --snapshot t_minus_6h
  python backtest_big5_fusion.py --leagues 英超 德甲
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean

STORE = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion\backtest")
LEAGUES = ["英超", "西甲", "意甲", "德甲", "法甲"]


def idx_1x2(h, a):
    return 0 if h > a else (1 if h == a else 2)


def probs_of(payload):
    core = payload.get("core_output") or payload
    p = core.get("final_1x2_pct")
    if not p:
        p = core.get("market_prob_pct")
    return [x / 100 for x in p] if p and len(p) == 3 else None


def ece10(obs):
    pairs = [(p[j], int(i == j)) for p, i in obs for j in range(3)]
    if not pairs:
        return None
    z = 0.0
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        g = [x for x in pairs if lo <= x[0] < (hi if b < 9 else 1.000001)]
        if not g:
            continue
        z += len(g) / len(pairs) * abs(mean(x[0] for x in g) - mean(x[1] for x in g))
    return z


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=STORE)
    ap.add_argument("--leagues", nargs="*", default=LEAGUES)
    ap.add_argument("--snapshot", default="closing")
    ap.add_argument("--output")
    a = ap.parse_args()
    store = Path(a.store)

    samples = []
    for line in store.joinpath("registry.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        p = Path(e["path"])
        if not p.exists():
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        comp = (r.get("match") or {}).get("competition")
        if r.get("snapshot_type") != a.snapshot or comp not in a.leagues:
            continue
        rp = store / "results" / f"{r['match_id']}.json"
        if not rp.exists():
            continue
        rs = json.loads(rp.read_text(encoding="utf-8"))
        sc = rs.get("score_90") or {}
        if sc.get("home") is None or sc.get("away") is None:
            continue
        model = probs_of(r.get("output") or {})
        market = ((r.get("output") or {}).get("core_output") or {}).get("market_prob_pct")
        if not model:
            continue
        samples.append({
            "league": comp, "match_id": r["match_id"],
            "model": model, "market": [x / 100 for x in market] if market else None,
            "actual": idx_1x2(sc["home"], sc["away"]),
        })

    by = {lg: [] for lg in a.leagues}
    for s in samples:
        by[s["league"]].append(s)

    def metrics(rows, key):
        obs = [(s[key], s["actual"]) for s in rows if s[key]]
        if not obs:
            return None
        brier = mean(sum((p[j] - (j == i)) ** 2 for j in range(3)) for p, i in obs)
        ll = mean(-math.log(max(1e-15, p[i])) for p, i in obs)
        hit = mean(int(max(range(3), key=lambda j: p[j]) == i) for p, i in obs)
        return {"n": len(obs), "brier": round(brier, 6), "logloss": round(ll, 6),
                "ece": round(ece10(obs), 6) if ece10(obs) is not None else None,
                "argmax_hit_pct": round(hit * 100, 2)}

    out = {"schema": "big5-fusion-backtest-1.0", "snapshot": a.snapshot,
           "note": "market_only 下 final_1x2 固定为去水市场，模型与市场基线一致属预期",
           "leagues": {}, "overall": {}}
    for lg in a.leagues:
        rows = by[lg]
        out["leagues"][lg] = {
            "n": len(rows),
            "model": metrics(rows, "model"),
            "market": metrics(rows, "market"),
        }
    out["overall"]["model"] = metrics(samples, "model")
    out["overall"]["market"] = metrics(samples, "market")
    out["overall"]["n"] = len(samples)

    if a.output:
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        Path(a.output).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
