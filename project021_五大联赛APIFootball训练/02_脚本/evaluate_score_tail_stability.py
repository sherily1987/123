#!/usr/bin/env python3
"""样本外比较旧比分截断与尾部稳定矩阵；只写研究报告，不改生产参数。"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import tune_score_params_by_league as base  # noqa: E402

DEFAULT_LAM3 = 0.20
DEFAULT_T = 1.30


def _pmf(lam: np.ndarray, n: int) -> np.ndarray:
    lam = np.maximum(lam, 1e-9)
    k = np.arange(n)
    out = np.exp(k[None, :] * np.log(lam)[:, None] - lam[:, None]
                 - np.array([math.lgamma(x + 1) for x in k]))
    out /= out.sum(axis=1, keepdims=True)
    return out


def _bp(lh: np.ndarray, la: np.ndarray, lam3: float, n: int) -> np.ndarray:
    a, b = _pmf(lh, n), _pmf(la, n)
    m = a[:, :, None] * b[:, None, :]
    den_h = np.maximum(lh, 1e-12)[:, None, None]
    den_a = np.maximum(la, 1e-12)[:, None, None]
    acc = np.zeros_like(m)
    for k in range(n):
        c = np.array([math.comb(i, k) if i >= k else 0 for i in range(n)])
        coef = math.factorial(k) * (lam3 / (den_h * den_a)) ** k
        acc += (c[None, :, None] * c[None, None, :]) * coef
    m *= math.exp(-lam3) * acc
    m /= m.sum(axis=(1, 2), keepdims=True)
    return m


def stable_bp_matrices(lh: np.ndarray, la: np.ndarray, lam3: float,
                       n: int = 11, tail_buffer: int = 8) -> np.ndarray:
    """先扩大网格，再将 >=n 的比分折叠到 n-1。"""
    high = _bp(lh, la, lam3, n + max(0, int(tail_buffer)))
    out = np.zeros((len(lh), n, n), dtype=float)
    for i in range(high.shape[1]):
        for j in range(high.shape[2]):
            out[:, min(i, n - 1), min(j, n - 1)] += high[:, i, j]
    out /= out.sum(axis=(1, 2), keepdims=True)
    return out


def evaluate(rows: list[dict], tail_buffer: int) -> dict:
    lh, la, kept = base.solve_lambdas(rows)
    n = len(kept)
    if n < 240:
        return {"status": "too_small", "n": n}
    split = int(n * 0.7)
    y = np.array([r["ft"] for r in kept])
    old = base.temperature_scale(
        base.bp_matrices(lh[split:], la[split:], DEFAULT_LAM3), DEFAULT_T
    )
    stable = base.temperature_scale(
        stable_bp_matrices(lh[split:], la[split:], DEFAULT_LAM3, tail_buffer=tail_buffer),
        DEFAULT_T,
    )
    old_m, stable_m = base.metrics(old, y[split:]), base.metrics(stable, y[split:])
    return {
        "status": "ok", "n": n, "train_n": split, "test_n": n - split,
        "split_day": kept[split]["day"], "production_m4": old_m,
        "stable_tail_buffer": {"buffer": tail_buffer, **stable_m},
        "delta_stable_minus_m4": {
            "score_log_loss": round(stable_m["score_log_loss"] - old_m["score_log_loss"], 5),
            "top1_acc_pct": round(stable_m["top1_acc_pct"] - old_m["top1_acc_pct"], 2),
            "top3_acc_pct": round(stable_m["top3_acc_pct"] - old_m["top3_acc_pct"], 2),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, default=base.PROJ)
    ap.add_argument("--tail-buffer", type=int, default=8)
    args = ap.parse_args()
    norm = args.project.resolve() / "04_素材" / "标准化"
    report = {
        "schema": "score-tail-stability-oos-1.0", "research_only": True,
        "production_unchanged": "M4 BP lambda3=0.20, score temperature=1.30",
        "tail_buffer": args.tail_buffer, "ran_at": datetime.now().isoformat(timespec="seconds"),
        "groups": {},
    }
    for name, files in base.GROUPS.items():
        rows = base.load_group(norm, files)
        report["groups"][name] = {"loaded_with_market": len(rows), **evaluate(rows, args.tail_buffer)}
        print(name, report["groups"][name], flush=True)
    out = args.project.resolve() / "05_交付" / "score_tail_stability_oos.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
