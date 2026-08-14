#!/usr/bin/env python3
"""evaluate_devig — 去水方法独立评估（R1②）。

对比 proportional / additive / power / shin 在：
1) devig_backtest_400_matches.jsonl（芬/瑞/挪/美 各100，Pinnacle 收盘，独立集）
2) football-data 五大联赛 46696 场（含 1X2 赔率与全场比分）
指标：1X2 Brier / LogLoss / 准确率 / ECE；按联赛与时间切分报告。
决策建议：方法须在独立集与全量上都最优（或与最优差距<0.0005）且 ECE 不劣，才切换默认。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"F:\HM足球比赛预测\project017_football-quant-fusion技能导出\02_核心引擎依赖\zu-yu-dashi-3/scripts")
from odds_methods import devig, METHODS


def actual_1x2(h, a):
    return 0 if h > a else (1 if h == a else 2)


def metrics(rows, key_probs):
    obs = []
    bs = []
    ll = []
    hit = []
    for r in rows:
        p = r[key_probs]
        i = r["actual_idx"]
        obs += [(p[k], 1 if k == i else 0) for k in range(3)]
        bs.append(sum((p[k] - (1 if k == i else 0)) ** 2 for k in range(3)))
        ll.append(-math.log(max(1e-12, p[i])))
        hit.append(int(max(range(3), key=lambda k: p[k]) == i))
    n = len(rows)
    ece = 0.0
    bins = []
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        g = [(p, y) for p, y in obs if lo <= p < (hi if b < 9 else 1.000001)]
        if not g:
            continue
        ap = sum(x[0] for x in g) / len(g)
        aa = sum(x[1] for x in g) / len(g)
        ece += len(g) / len(obs) * abs(ap - aa)
        bins.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(g), "avg_prob": round(ap, 5), "actual_rate": round(aa, 5)})
    return {
        "n": n,
        "brier_mean": round(sum(bs) / n, 6),
        "log_loss": round(sum(ll) / n, 6),
        "accuracy_pct": round(sum(hit) / n * 100, 2),
        "ece": round(ece, 6),
        "calibration_bins": bins,
    }


def run_set(rows, label):
    out = {"set": label, "n": len(rows), "methods": {}}
    for m in METHODS:
        probs = []
        for r in rows:
            p, _ = devig(r["odds"], m)
            probs.append(p)
        key = f"p_{m}"
        for r, p in zip(rows, probs):
            r[key] = p
        out["methods"][m] = metrics(rows, key)
    out["by_league"] = {}
    for lg in sorted({r.get("league") for r in rows}):
        sub = [r for r in rows if r.get("league") == lg]
        out["by_league"][lg] = {"n": len(sub), "methods": {
            m: metrics(sub, f"p_{m}") for m in METHODS}}
    if len(rows) >= 20:
        half = len(rows) // 2
        out["chronological_split"] = {
            "first_half": {m: metrics(rows[:half], f"p_{m}") for m in METHODS},
            "second_half": {m: metrics(rows[half:], f"p_{m}") for m in METHODS},
        }
    return out


def load_400(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        s = r.get("score_90")
        o = ((r.get("snapshots") or {}).get("closing") or {}).get("odds")
        if not s or not o:
            continue
        rows.append({
            "league": r.get("league", "?"), "season": r.get("season", ""),
            "odds": [float(x) for x in o],
            "actual_idx": actual_1x2(int(s[0]), int(s[1])),
        })
    return rows


def load_big5(jsonl_path, limit=0):
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if not r.get("odds") or not r.get("actual"):
                continue
            rf = r.get("raw_fields") or {}
            rows.append({
                "league": str(r.get("competition") or r.get("stage") or "?"),
                "season": rf.get("Season") or r.get("season") or "",
                "odds": [float(x) for x in r["odds"][:3]],
                "actual_idx": actual_1x2(int(r["actual"][0]), int(r["actual"][1])),
            })
            if limit and len(rows) >= limit:
                break
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--devig-400", required=True)
    ap.add_argument("--big5-jsonl", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    rep = {
        "schema_version": "devig-eval-1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "methods": list(METHODS),
        "independent_400": run_set(load_400(a.devig_400), "devig_backtest_400"),
        "big5_46696": run_set(load_big5(a.big5_jsonl), "football-data_big5"),
    }
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    def best(blk):
        return min(blk["methods"], key=lambda m: (blk["methods"][m]["brier_mean"], blk["methods"][m]["log_loss"]))

    b400, b5 = best(rep["independent_400"]), best(rep["big5_46696"])
    rec = "switch_to_power" if b400 == b5 == "power" else "keep_proportional_or_recheck"
    print(json.dumps({
        "status": "ok",
        "independent_400_best": b400,
        "big5_best": b5,
        "recommendation": rec,
        "independent_400": {m: {k: v for k, v in rep["independent_400"]["methods"][m].items() if k != "calibration_bins"} for m in METHODS},
        "big5": {m: {k: v for k, v in rep["big5_46696"]["methods"][m].items() if k != "calibration_bins"} for m in METHODS},
        "output": a.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
