#!/usr/bin/env python3
"""train_ht_models — 半场矩阵模型验证（DC vs 双变量泊松）（BP 半场接入前置）。

半场 λ = 全场 λ × FIRST_HALF_SHARE(0.45)；网格 7×7（0..6），与引擎 ht 口径一致。
数据：football-data 五大联赛含半场比分（HTHG/HTAG）且有 1X2 赔率的场次。
每个模型独立拟合温度 T（train 比分 LogLoss 网格）；BP 网格 λ3 ∈ {0.02,0.05,0.1}。
指标：半场比分 LL / Top1 / Top3 / ECE + 半场 1X2 准确率。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/skills/zu-yu-dashi-3/scripts")
import predict as P
import goal_model_ensemble as G

HT_N = 7  # 0..6
GRID = np.arange(HT_N)


def load_ht(jsonl_path, sample_target=23348):
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if not r.get("odds") or not r.get("actual"):
                continue
            rf = r.get("raw_fields") or {}
            hthg, htag = rf.get("HTHG"), rf.get("HTAG")
            if hthg is None or htag is None:
                continue
            day = str(r.get("kickoff") or G.parse_csv_date(rf.get("Date")) or "")[:10]
            if not day:
                continue
            try:
                rows.append({
                    "day": day,
                    "odds": [float(x) for x in r["odds"][:3]],
                    "ht": (int(hthg), int(htag)),
                })
            except (TypeError, ValueError):
                continue
    rows.sort(key=lambda r: r["day"])
    if sample_target and len(rows) > sample_target:
        step = max(1, len(rows) // sample_target)
        rows = rows[::step]
    return rows


def dc_ht(lh, la):
    out = np.zeros((len(lh), HT_N, HT_N))
    for n in range(len(lh)):
        m = P.matrix(lh[n] * P.FIRST_HALF_SHARE, la[n] * P.FIRST_HALF_SHARE, P.RHO_DEFAULT / 2, HT_N - 1)
        for (i, j), v in m.items():
            if i < HT_N and j < HT_N:
                out[n, i, j] = v
    return out


def bp_ht(lh, la, lam3):
    out = np.zeros((len(lh), HT_N, HT_N))
    for n in range(len(lh)):
        m = P.bp_matrix(lh[n] * P.FIRST_HALF_SHARE, la[n] * P.FIRST_HALF_SHARE, lam3, HT_N - 1)
        for (i, j), v in m.items():
            if i < HT_N and j < HT_N:
                out[n, i, j] = v
    return out


def metrics(m, y):
    n = m.shape[0]
    flat = np.clip(m, 1e-12, 1.0)
    ll = float(-np.log(flat[np.arange(n), y[:, 0], y[:, 1]]).mean())
    top1 = top3 = 0
    h1 = 0
    for i in range(n):
        idx = np.argsort(m[i].ravel())[::-1][:3]
        yi = y[i, 0] * HT_N + y[i, 1]
        top1 += int(yi == idx[0])
        top3 += int(yi in idx[:3])
        # HT 1X2
        h = sum(m[i, a, b] for a in range(HT_N) for b in range(HT_N) if a > b)
        d = sum(m[i, a, b] for a in range(HT_N) for b in range(HT_N) if a == b)
        a2 = 1 - h - d
        ycls = 0 if y[i, 0] > y[i, 1] else (1 if y[i, 0] == y[i, 1] else 2)
        pred = 0 if h >= d and h >= a2 else (1 if d >= a2 else 2)
        h1 += int(pred == ycls)
    flatp = flat.reshape(-1)
    flaty = np.zeros_like(flatp)
    flaty[np.arange(n) * HT_N * HT_N + y[:, 0] * HT_N + y[:, 1]] = 1
    ece = 0.0
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        sel = (flatp >= lo) & (flatp < (hi if b < 9 else 1.000001))
        if sel.sum() == 0:
            continue
        ece += sel.sum() / len(flatp) * abs(flatp[sel].mean() - flaty[sel].mean())
    return {
        "n": n, "score_log_loss": round(ll, 5), "top1_acc_pct": round(top1 / n * 100, 2),
        "top3_acc_pct": round(top3 / n * 100, 2), "ht_1x2_acc_pct": round(h1 / n * 100, 2),
        "ece": round(ece, 5),
    }


def fit_temperature(m, y, grid=(1.0, 1.1, 1.2, 1.3, 1.4, 1.5)):
    best = (1.0, float("inf"))
    for T in grid:
        mc = G.temperature_scale(m, T)
        ll = float(-np.log(np.clip(mc[np.arange(m.shape[0]), y[:, 0], y[:, 1]], 1e-12, 1.0)).mean())
        if ll < best[1]:
            best = (T, ll)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--sample-target", type=int, default=23348)
    a = ap.parse_args()
    rows = load_ht(a.input, a.sample_target)
    print(f"loaded {len(rows)}", flush=True)
    lh, la, rows = G.solve_lambdas(rows)
    n = len(rows)
    split = int(n * 0.7)
    y = np.array([r["ht"] for r in rows])
    print(f"solved {n} (train {split}/test {n - split})", flush=True)
    t0 = time.time()

    dc_tr = dc_ht(lh[:split], la[:split])
    dc_te = dc_ht(lh[split:], la[split:])
    Td, _ = fit_temperature(dc_tr, y[:split])
    dc_res = metrics(G.temperature_scale(dc_te, Td), y[split:])
    print(f"dc T={Td} {dc_res} {time.time()-t0:.0f}s", flush=True)

    bp_best = None
    for lam3 in (0.02, 0.05, 0.1):
        bp_tr = bp_ht(lh[:split], la[:split], lam3)
        T3, ll3 = fit_temperature(bp_tr, y[:split])
        if bp_best is None or ll3 < bp_best[1]:
            bp_best = (lam3, T3, ll3)
    lam3, T3, _ = bp_best
    bp_te = bp_ht(lh[split:], la[split:], lam3)
    bp_res = metrics(G.temperature_scale(bp_te, T3), y[split:])
    print(f"bp lam3={lam3} T={T3} {bp_res} {time.time()-t0:.0f}s", flush=True)

    rep = {
        "schema_version": "ht-model-1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "n": n, "train_n": split, "test_n": n - split,
        "models": {
            "dc": {"temperature": Td, "test": dc_res},
            "bp": {"lambda3": lam3, "temperature": T3, "test": bp_res},
        },
    }
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v["test"] for k, v in rep["models"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
