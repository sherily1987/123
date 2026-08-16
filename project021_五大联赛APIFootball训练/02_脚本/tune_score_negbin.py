#!/usr/bin/env python3
"""负二项比分研究：与生产 BP(λ3=0.05, T=1.30) 同数据对照。不改生产常数。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.special import gammaln

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import tune_score_params_by_league as base  # noqa: E402

R_GRID = (3.0, 4.0, 6.0, 8.0, 12.0, 16.0)
T_GRID = base.T_GRID
MIN_TEST = base.MIN_TEST
LL_WIN = base.LL_WIN


def nb_pmf(lam, r):
    mu = np.maximum(lam, 1e-9)
    p = r / (r + mu)
    k = base.GRID
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
    m = a[:, :, None] * b[:, None, :]
    m /= m.sum(axis=(1, 2), keepdims=True)
    return m


def slice_metrics(m, y):
    n = m.shape[0]
    out = base.metrics(m, y)
    zz = (y[:, 0] == 0) & (y[:, 1] == 0)
    blow = (y[:, 0] >= 3) | (y[:, 1] >= 3)
    for name, mask in (("zero_zero", zz), ("blowout_3plus", blow)):
        if int(mask.sum()) == 0:
            out[name] = {"n": 0}
            continue
        idx = np.where(mask)[0]
        ll = float(-np.log(np.clip(m[idx, y[idx, 0], y[idx, 1]], 1e-12, 1.0)).mean())
        p00 = float(m[idx, 0, 0].mean()) if name == "zero_zero" else None
        out[name] = {"n": int(mask.sum()), "score_log_loss": round(ll, 5),
                     "mean_p00": None if p00 is None else round(p00, 4)}
    return out


def fit_group(rows: list[dict]) -> dict:
    lh, la, kept = base.solve_lambdas(rows)
    n = len(kept)
    if n < MIN_TEST * 2:
        return {"status": "too_small", "n": n}
    split = int(n * 0.7)
    y = np.array([r["ft"] for r in kept])
    y_tr, y_te = y[:split], y[split:]
    bp_te = base.temperature_scale(
        base.bp_matrices(lh[split:], la[split:], base.DEFAULT_LAM3), base.DEFAULT_T)
    baseline = {
        "family": "bivariate_poisson",
        "lambda3": base.DEFAULT_LAM3,
        "temperature": base.DEFAULT_T,
        "test": slice_metrics(bp_te, y_te),
    }
    best = None
    for r in R_GRID:
        nb_tr = nb_matrices(lh[:split], la[:split], r)
        nb_te = nb_matrices(lh[split:], la[split:], r)
        for T in T_GRID:
            tr = base.metrics(base.temperature_scale(nb_tr, T), y_tr)
            te = slice_metrics(base.temperature_scale(nb_te, T), y_te)
            row = {"family": "negbin", "r": r, "temperature": T, "train": tr, "test": te}
            if best is None or tr["score_log_loss"] < best["train"]["score_log_loss"]:
                best = row
    adopt = False
    reason = "keep_bp_default"
    if best and best["test"]["n"] >= MIN_TEST:
        dll = baseline["test"]["score_log_loss"] - best["test"]["score_log_loss"]
        dtop3 = best["test"]["top3_acc_pct"] - baseline["test"]["top3_acc_pct"]
        if dll >= LL_WIN:
            adopt = True
            reason = f"test_log_loss_improved_{dll:.4f}"
        elif dll >= 0 and dtop3 >= 1.0:
            adopt = True
            reason = "test_top3_plus_1pp_ll_not_worse"
    return {
        "status": "ok", "n": n, "train_n": split, "test_n": n - split,
        "first_day": kept[0]["day"], "last_day": kept[-1]["day"],
        "split_day": kept[split]["day"],
        "bp_default": baseline,
        "nb_train_best": best,
        "adopt_over_bp": adopt,
        "adopt_reason": reason,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, default=base.PROJ)
    args = ap.parse_args()
    project = args.project.resolve()
    norm = project / "04_素材" / "标准化"
    report = {
        "schema": "score-negbin-research-1.0",
        "research_only": True,
        "production_unchanged": "SCORE_MODEL=bp SCORE_LAMBDA3=0.05 SCORE_TEMPERATURE_FT=1.30",
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "grid": {"r": list(R_GRID), "temperature": list(T_GRID)},
        "groups": {},
    }
    for name, files in base.GROUPS.items():
        rows = base.load_group(norm, files)
        report["groups"][name] = {"files": files, "loaded_with_market": len(rows), **fit_group(rows)}
        g = report["groups"][name]
        best = g.get("nb_train_best") or {}
        print(name, g.get("status"), "n=", g.get("n"), "adopt=", g.get("adopt_over_bp"),
              "nb=", best.get("r"), best.get("temperature"), flush=True)
    out = project / "05_交付" / "score_negbin_research.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
