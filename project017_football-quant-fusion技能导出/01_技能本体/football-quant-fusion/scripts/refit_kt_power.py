#!/usr/bin/env python3
"""refit_kt_power — 在 power 去水下重拟合体彩 1X2 校准层（K/T）（R2④）。

背景：现 K=1.14/T=0.96 是按 proportional 去水拟合的；默认去水已切 power，
需在 power 下重新网格拟合，消除"校准层与去水方法"的最后耦合。
数据：体彩2026收盘HAD（closing_had + 全场比分），按 matchDate 时间切分
（train < 2026-05-17，test >= 2026-05-17，与原 1348 场切分一致）。
选择：train ECE 网格选优；test 报告（并与旧参数/无校准对照）。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖\zu-yu-dashi-3/scripts")
from odds_methods import devig
from predict import calibrate_1x2


def load(hist_path, split_date="2026-05-17"):
    data = json.loads(Path(hist_path).read_text(encoding="utf-8"))
    rows = []
    for m in data.get("matches", []):
        had = m.get("closing_had")
        res = m.get("sectionsNo999")
        if not had or not res or ":" not in res:
            continue
        try:
            odds = [float(had[0]), float(had[1]), float(had[2])]
            h, a = map(int, res.split(":"))
        except Exception:
            continue
        if h > 12 or a > 12:
            continue
        rows.append({
            "date": str(m.get("matchDate") or ""), "odds": odds,
            "idx": 0 if h > a else (1 if h == a else 2),
        })
    train = [r for r in rows if r["date"] < split_date]
    test = [r for r in rows if r["date"] >= split_date]
    return rows, train, test


def metrics(probs, idxs):
    obs = []
    bs = []
    ll = []
    hit = []
    for p, i in zip(probs, idxs):
        obs += [(p[k], 1 if k == i else 0) for k in range(3)]
        bs.append(sum((p[k] - (1 if k == i else 0)) ** 2 for k in range(3)))
        ll.append(-math.log(max(1e-12, p[i])))
        hit.append(int(max(range(3), key=lambda k: p[k]) == i))
    n = len(probs)
    ece = 0.0
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        g = [(x, y) for x, y in obs if lo <= x < (hi if b < 9 else 1.000001)]
        if not g:
            continue
        ap = sum(x[0] for x in g) / len(g)
        aa = sum(x[1] for x in g) / len(g)
        ece += len(g) / len(obs) * abs(ap - aa)
    return {
        "n": n, "brier_mean": round(sum(bs) / n, 6), "log_loss": round(sum(ll) / n, 6),
        "accuracy_pct": round(sum(hit) / n * 100, 2), "ece": round(ece, 6),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", required=True, help="sporttery_all_leagues_history_2026.json")
    ap.add_argument("--output", required=True)
    ap.add_argument("--devig-method", default="power")
    a = ap.parse_args()
    rows, train, test = load(a.history)
    m = a.devig_method
    tr_p = [devig(r["odds"], m)[0] for r in train]
    te_p = [devig(r["odds"], m)[0] for r in test]
    tr_i = [r["idx"] for r in train]
    te_i = [r["idx"] for r in test]

    best = None
    for k in [x / 100.0 for x in range(80, 141, 2)]:
        for t in [x / 100.0 for x in range(80, 121, 2)]:
            mm = metrics([calibrate_1x2(p, k, t) for p in tr_p], tr_i)
            if best is None or mm["ece"] < best[2]["ece"]:
                best = (k, t, mm)
    k, t, _ = best
    rep = {
        "schema_version": "refit-kt-power-1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devig_method": m,
        "n": len(rows), "train_n": len(train), "test_n": len(test),
        "fitted": {"draw_k": k, "temperature": t,
                   "train_metrics": metrics([calibrate_1x2(p, k, t) for p in tr_p], tr_i),
                   "test_metrics": metrics([calibrate_1x2(p, k, t) for p in te_p], te_i)},
        "old_proportional_kt": {"draw_k": 1.14, "temperature": 0.96,
                                "train_metrics": metrics([calibrate_1x2(p, 1.14, 0.96) for p in tr_p], tr_i),
                                "test_metrics": metrics([calibrate_1x2(p, 1.14, 0.96) for p in te_p], te_i)},
        "no_cal": {"draw_k": 1.0, "temperature": 1.0,
                   "train_metrics": metrics([calibrate_1x2(p, 1.0, 1.0) for p in tr_p], tr_i),
                   "test_metrics": metrics([calibrate_1x2(p, 1.0, 1.0) for p in te_p], te_i)},
    }
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "fitted": {"draw_k": k, "temperature": t,
                   "test": {x: rep["fitted"]["test_metrics"][x] for x in ("brier_mean", "ece", "log_loss", "accuracy_pct")}},
        "old_proportional_kt_test": {x: rep["old_proportional_kt"]["test_metrics"][x] for x in ("brier_mean", "ece", "log_loss", "accuracy_pct")},
        "no_cal_test": {x: rep["no_cal"]["test_metrics"][x] for x in ("brier_mean", "ece", "log_loss", "accuracy_pct")},
        "output": a.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
