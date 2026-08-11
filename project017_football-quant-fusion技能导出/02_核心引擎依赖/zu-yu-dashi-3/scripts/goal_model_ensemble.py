#!/usr/bin/env python3
"""goal_model_ensemble — 目标模型对比（R2③）。

对比独立泊松+Dixon-Coles（引擎基线）、双变量泊松（BP）、负二项（NB）及其等权 ensemble，
在 football-data 五大联赛 46696 场上 OOS 评估（λ 由市场 1X2 反解，同引擎口径）：
比分 LogLoss / Top1-5 / ECE、O/U2.5 Brier、BTTS Brier；每个模型独立拟合温度 T（train 网格）。
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
from scipy.special import gammaln

sys.path.insert(0, r"H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖\zu-yu-dashi-3/scripts")
import predict as P

N = 13  # 0..12
GRID = np.arange(0, N)


def parse_csv_date(s):
    s = str(s or "").strip()
    parts = s.split("/")
    if len(parts) != 3:
        return s
    try:
        d, m, y = int(parts[0]), int(parts[1]), parts[2]
        if len(str(y)) == 2:
            yy = int(y)
            y = 1900 + yy if yy >= 70 else 2000 + yy
        return f"{int(y):04d}-{m:02d}-{d:02d}"
    except ValueError:
        return s


def load(jsonl_path, sample_target=15566):
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if not r.get("odds") or not r.get("actual"):
                continue
            rf = r.get("raw_fields") or {}
            day = str(r.get("kickoff") or parse_csv_date(rf.get("Date")) or "")[:10]
            if not day:
                continue
            rows.append({
                "day": day, "league": str(r.get("competition") or r.get("stage") or "?"),
                "odds": [float(x) for x in r["odds"][:3]],
                "ft": (int(r["actual"][0]), int(r["actual"][1])),
            })
    rows.sort(key=lambda r: r["day"])
    if sample_target and len(rows) > sample_target:
        step = max(1, len(rows) // sample_target)
        rows = rows[::step]
    return rows


def solve_lambdas(rows):
    lh = np.zeros(len(rows))
    la = np.zeros(len(rows))
    ok = np.ones(len(rows), dtype=bool)
    for n, r in enumerate(rows):
        p, _ = P.devig(r["odds"], "power")
        lam = P.solve_lam_from_probs(p)
        if lam is None:
            ok[n] = False
            continue
        lh[n], la[n] = lam
    return lh[ok], la[ok], [r for i, r in enumerate(rows) if ok[i]]


def pois_pmf(lam, n=N):
    lam = np.maximum(lam, 1e-9)
    k = GRID
    lg = k * np.log(lam)[:, None] - lam[:, None] - np.array([math.lgamma(x + 1) for x in k])
    p = np.exp(lg)
    p /= p.sum(axis=1, keepdims=True)
    return p  # (n, 13)


def dc_matrices(lh, la, rho=-0.08):
    a = pois_pmf(lh)
    b = pois_pmf(la)
    m = a[:, :, None] * b[:, None, :]  # (n,13,13)
    # DC tau
    t = np.ones_like(m)
    t[:, 0, 0] = 1 + lh * la * rho
    t[:, 0, 1] = 1 - la * rho
    t[:, 1, 0] = 1 - lh * rho
    t[:, 1, 1] = 1 + rho
    m = m * t
    m /= m.sum(axis=(1, 2), keepdims=True)
    return m


def bp_matrices(lh, la, lam3):
    a = pois_pmf(lh)
    b = pois_pmf(la)
    m = a[:, :, None] * b[:, None, :]
    lam1 = np.maximum(lh, 1e-12)[:, None, None]
    lam2 = np.maximum(la, 1e-12)[:, None, None]
    acc = np.zeros_like(m)
    for k in range(N):
        ci = np.array([math.comb(i, k) if i >= k else 0 for i in range(N)])  # (13,)
        term_k = (ci[:, None] * ci[None, :])[None, :, :]  # (1,13,13)
        coef = math.exp(math.lgamma(k + 1)) * (lam3 / (lam1 * lam2)) ** k  # (n,1,1)
        acc += term_k * coef
    m = m * np.exp(-lam3) * acc
    m /= m.sum(axis=(1, 2), keepdims=True)
    return m


def nb_pmf(lam, r, n=N):
    # NB(k; r, mu): p=r/(r+mu); P(k)=Gamma(k+r)/(Gamma(r)k!) p^r (1-p)^k
    mu = np.maximum(lam, 1e-9)
    p = r / (r + mu)
    k = GRID
    lg = (gammaln(k + r)[None, :] - gammaln(r)
          + k[None, :] * np.log(1 - p)[:, None]
          + r * np.log(p)[:, None]
          - gammaln(k + 1)[None, :])
    pm = np.exp(lg)
    pm /= pm.sum(axis=1, keepdims=True)
    return pm


def nb_matrices(lh, la, r):
    a = nb_pmf(lh, r)
    b = nb_pmf(la, r)
    return a[:, :, None] * b[:, None, :]


def temperature_scale(m, T):
    inv = 1.0 / T
    mc = np.maximum(m, 1e-15) ** inv
    mc /= mc.sum(axis=(1, 2), keepdims=True)
    return mc


def metrics(m, y):
    n = m.shape[0]
    flat = np.clip(m, 1e-12, 1.0)
    ll = float(-np.log(flat[np.arange(n), y[:, 0], y[:, 1]]).mean())
    top1 = top3 = top5 = 0
    for i in range(n):
        idx = np.argsort(m[i].ravel())[::-1][:5]
        yi = y[i, 0] * N + y[i, 1]
        top1 += int(yi == idx[0])
        top3 += int(yi in idx[:3])
        top5 += int(yi in idx)
    # ECE per-cell
    flatp = flat.reshape(-1)
    flaty = np.zeros_like(flatp)
    flaty[np.arange(n) * N * N + y[:, 0] * N + y[:, 1]] = 1
    ece = 0.0
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        sel = (flatp >= lo) & (flatp < (hi if b < 9 else 1.000001))
        if sel.sum() == 0:
            continue
        ece += sel.sum() / len(flatp) * abs(flatp[sel].mean() - flaty[sel].mean())
    # OU2.5 / BTTS
    gh = y[:, 0]; ga = y[:, 1]
    ghg = GRID[:, None] + GRID[None, :]  # (13,13)
    mf = m.reshape(n, -1)
    ou_over = mf[:, (ghg > 2.5).ravel()].sum(axis=1)
    btts_mask = (GRID[:, None] > 0) & (GRID[None, :] > 0)
    btts = mf[:, btts_mask.ravel()].sum(axis=1)
    ou_b = float(np.mean((ou_over - (gh + ga > 2.5)) ** 2))
    bt_b = float(np.mean((btts - ((gh > 0) & (ga > 0))) ** 2))
    return {
        "n": n, "score_log_loss": round(ll, 5),
        "top1_acc_pct": round(top1 / n * 100, 2), "top3_acc_pct": round(top3 / n * 100, 2),
        "top5_acc_pct": round(top5 / n * 100, 2), "ece": round(ece, 5),
        "ou_2_5_brier": round(ou_b, 6), "btts_brier": round(bt_b, 6),
    }


def fit_temperature(m, y, grid=(1.0, 1.1, 1.2, 1.3, 1.4, 1.5)):
    best = (1.0, float("inf"))
    for T in grid:
        mc = temperature_scale(m, T)
        ll = float(-np.log(np.clip(mc[np.arange(m.shape[0]), y[:, 0], y[:, 1]], 1e-12, 1.0)).mean())
        if ll < best[1]:
            best = (T, ll)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--sample-target", type=int, default=15566)
    a = ap.parse_args()
    rows = load(a.input, a.sample_target)
    print(f"loaded {len(rows)}", flush=True)
    lh, la, rows = solve_lambdas(rows)
    n = len(rows)
    split = int(n * 0.7)
    y = np.array([r["ft"] for r in rows])
    print(f"solved {n} (train {split}/test {n - split})", flush=True)

    res = {"schema_version": "goal-model-ensemble-1.0",
           "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "n": n, "train_n": split, "test_n": n - split, "models": {}}
    t0 = time.time()
    dc_tr = dc_matrices(lh[:split], la[:split])
    dc_te = dc_matrices(lh[split:], la[split:])
    T, _ = fit_temperature(dc_tr, y[:split])
    res["models"]["dc"] = {"temperature": T, "test": metrics(temperature_scale(dc_te, T), y[split:])}
    print(f"dc done {time.time()-t0:.0f}s T={T}", flush=True)

    bp_best = None
    for lam3 in (0.05, 0.1, 0.15):
        bp_tr = bp_matrices(lh[:split], la[:split], lam3)
        T3, ll3 = fit_temperature(bp_tr, y[:split])
        if bp_best is None or ll3 < bp_best[1]:
            bp_best = (lam3, T3, ll3, bp_tr)
    lam3, T3, _, bp_tr = bp_best
    bp_te = bp_matrices(lh[split:], la[split:], lam3)
    res["models"]["bp"] = {"lambda3": lam3, "temperature": T3, "test": metrics(temperature_scale(bp_te, T3), y[split:])}
    print(f"bp done {time.time()-t0:.0f}s lam3={lam3} T={T3}", flush=True)

    nb_best = None
    for r in (4, 8, 16):
        nb_tr = nb_matrices(lh[:split], la[:split], r)
        Tr, llr = fit_temperature(nb_tr, y[:split])
        if nb_best is None or llr < nb_best[1]:
            nb_best = (r, Tr, llr, nb_tr)
    r_, Tr, _, nb_tr = nb_best
    nb_te = nb_matrices(lh[split:], la[split:], r_)
    res["models"]["nb"] = {"r": r_, "temperature": Tr, "test": metrics(temperature_scale(nb_te, Tr), y[split:])}
    print(f"nb done {time.time()-t0:.0f}s r={r_} T={Tr}", flush=True)

    ens_tr = (temperature_scale(dc_tr, res["models"]["dc"]["temperature"])
              + temperature_scale(bp_tr, T3)
              + temperature_scale(nb_tr, Tr)) / 3.0
    ens_te = (temperature_scale(dc_te, res["models"]["dc"]["temperature"])
              + temperature_scale(bp_te, T3)
              + temperature_scale(nb_te, Tr)) / 3.0
    Te, _ = fit_temperature(ens_tr, y[:split])
    res["models"]["ensemble"] = {"temperature": Te, "weights": "equal_1/3",
                                 "test": metrics(temperature_scale(ens_te, Te), y[split:])}
    print(f"ensemble done {time.time()-t0:.0f}s T={Te}", flush=True)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v["test"] for k, v in res["models"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
