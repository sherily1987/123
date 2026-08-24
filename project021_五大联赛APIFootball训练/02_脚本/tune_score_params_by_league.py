#!/usr/bin/env python3
"""按联赛组网格搜索比分 BP 的 λ3 与温度 T（研究，不改生产常数）。

λ 一律从市场 1X2 反解（与正式 market_only 同一口径）。
当前生产 M4 默认是 λ3=0.20、T=1.30；本脚本只写 05_交付 报告。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE = ROOT / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
import predict as P  # noqa: E402

PROJ = ROOT / "project021_五大联赛APIFootball训练"
N = 11
GRID = np.arange(0, N)
DEFAULT_LAM3 = 0.20
DEFAULT_T = 1.30
LAM3_GRID = (0.02, 0.05, 0.08, 0.10, 0.15)
T_GRID = (1.0, 1.1, 1.2, 1.3, 1.4, 1.5)
MIN_TEST = 120
LL_WIN = 0.005

GROUPS = {
    "big5": [
        "premier_league_events_provider_market.jsonl",
        "la_liga_events_provider_market.jsonl",
        "bundesliga_events_provider_market.jsonl",
        "serie_a_events_provider_market.jsonl",
        "ligue_1_events_provider_market.jsonl",
    ],
    "nordic": [
        "norway_eliteserien_events_provider_market.jsonl",
        "sweden_allsvenskan_events_provider_market.jsonl",
        "finland_veikkausliiga_events_provider_market.jsonl",
    ],
    "j1": [
        "apisports_japan_j1_league_events_closing_attached.jsonl",
    ],
}


def market_probs(row: dict) -> list[float] | None:
    for key in ("closing_market_1x2", "provider_market_1x2"):
        val = row.get(key)
        if isinstance(val, (list, tuple)) and len(val) >= 3:
            try:
                p = [float(val[0]), float(val[1]), float(val[2])]
            except (TypeError, ValueError):
                continue
            if min(p) > 0 and abs(sum(p) - 1) < 0.08:
                s = sum(p)
                return [x / s for x in p]
    odds = row.get("odds")
    if isinstance(odds, (list, tuple)) and len(odds) >= 3:
        try:
            p, _ = P.devig([float(odds[0]), float(odds[1]), float(odds[2])], "power")
            return [float(p[0]), float(p[1]), float(p[2])]
        except (TypeError, ValueError):
            return None
    return None


def load_group(norm: Path, files: list[str]) -> list[dict]:
    rows = []
    for name in files:
        path = norm / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            actual = rec.get("actual")
            if not (isinstance(actual, (list, tuple)) and len(actual) >= 2):
                continue
            try:
                h, a = int(actual[0]), int(actual[1])
            except (TypeError, ValueError):
                continue
            if h < 0 or a < 0:
                continue
            probs = market_probs(rec)
            if not probs:
                continue
            day = str(rec.get("kickoff") or "")[:10]
            if len(day) < 10:
                continue
            rows.append({"day": day, "ft": (min(h, N - 1), min(a, N - 1)), "probs": probs})
    rows.sort(key=lambda r: r["day"])
    return rows


def solve_lambdas(rows: list[dict]) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    lh, la, kept = [], [], []
    for rec in rows:
        lam = P.solve_lam_from_probs(rec["probs"])
        if lam is None:
            continue
        lh.append(lam[0])
        la.append(lam[1])
        kept.append(rec)
    return np.array(lh), np.array(la), kept


def pois_pmf(lam):
    lam = np.maximum(lam, 1e-9)
    k = GRID
    lg = k * np.log(lam)[:, None] - lam[:, None] - np.array([math.lgamma(x + 1) for x in k])
    p = np.exp(lg)
    p /= p.sum(axis=1, keepdims=True)
    return p


def bp_matrices(lh, la, lam3):
    a = pois_pmf(lh)
    b = pois_pmf(la)
    m = a[:, :, None] * b[:, None, :]
    lam1 = np.maximum(lh, 1e-12)[:, None, None]
    lam2 = np.maximum(la, 1e-12)[:, None, None]
    acc = np.zeros_like(m)
    for k in range(N):
        ci = np.array([math.comb(i, k) if i >= k else 0 for i in range(N)])
        term_k = (ci[:, None] * ci[None, :])[None, :, :]
        coef = math.exp(math.lgamma(k + 1)) * (lam3 / (lam1 * lam2)) ** k
        acc += term_k * coef
    m = m * np.exp(-lam3) * acc
    m /= m.sum(axis=(1, 2), keepdims=True)
    return m


def temperature_scale(m, T):
    inv = 1.0 / T
    mc = np.maximum(m, 1e-15) ** inv
    mc /= mc.sum(axis=(1, 2), keepdims=True)
    return mc


def metrics(m, y):
    n = m.shape[0]
    flat = np.clip(m, 1e-12, 1.0)
    ll = float(-np.log(flat[np.arange(n), y[:, 0], y[:, 1]]).mean())
    top1 = top3 = 0
    for i in range(n):
        idx = np.argsort(m[i].ravel())[::-1][:3]
        yi = int(y[i, 0]) * N + int(y[i, 1])
        top1 += int(yi == idx[0])
        top3 += int(yi in idx[:3])
    return {
        "n": n,
        "score_log_loss": round(ll, 5),
        "top1_acc_pct": round(100.0 * top1 / n, 2),
        "top3_acc_pct": round(100.0 * top3 / n, 2),
    }


def fit_group(rows: list[dict]) -> dict:
    lh, la, kept = solve_lambdas(rows)
    n = len(kept)
    if n < MIN_TEST * 2:
        return {"status": "too_small", "n": n}
    split = int(n * 0.7)
    y = np.array([r["ft"] for r in kept])
    y_tr, y_te = y[:split], y[split:]
    default = None
    best = None
    for lam3 in LAM3_GRID:
        bp_tr = bp_matrices(lh[:split], la[:split], lam3)
        bp_te = bp_matrices(lh[split:], la[split:], lam3)
        for T in T_GRID:
            tr = metrics(temperature_scale(bp_tr, T), y_tr)
            te = metrics(temperature_scale(bp_te, T), y_te)
            row = {"lambda3": lam3, "temperature": T, "train": tr, "test": te}
            if abs(lam3 - DEFAULT_LAM3) < 1e-12 and abs(T - DEFAULT_T) < 1e-12:
                default = row
            if best is None or tr["score_log_loss"] < best["train"]["score_log_loss"]:
                best = row
    if default is None:
        default = {
            "lambda3": DEFAULT_LAM3, "temperature": DEFAULT_T,
            "test": metrics(temperature_scale(bp_matrices(lh[split:], la[split:], DEFAULT_LAM3), DEFAULT_T), y_te),
        }
    adopt = False
    reason = "keep_default"
    if best and best["test"]["n"] >= MIN_TEST:
        dll = default["test"]["score_log_loss"] - best["test"]["score_log_loss"]
        if dll >= LL_WIN:
            adopt = True
            reason = f"test_log_loss_improved_{dll:.4f}"
        elif dll >= 0 and (best["test"]["top3_acc_pct"] - default["test"]["top3_acc_pct"]) >= 1.0:
            adopt = True
            reason = "test_top3_plus_1pp_ll_not_worse"
    return {
        "status": "ok",
        "n": n,
        "train_n": split,
        "test_n": n - split,
        "first_day": kept[0]["day"],
        "last_day": kept[-1]["day"],
        "split_day": kept[split]["day"],
        "production_default": default,
        "train_best": best,
        "adopt_for_research": adopt,
        "adopt_reason": reason,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, default=PROJ)
    args = ap.parse_args()
    project = args.project.resolve()
    norm = project / "04_素材" / "标准化"
    report = {
        "schema": "score-params-by-league-1.0",
        "research_only": True,
        "production_unchanged": "M4 SCORE_LAMBDA3=0.20 SCORE_TEMPERATURE_FT=1.30",
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "grid": {"lambda3": list(LAM3_GRID), "temperature": list(T_GRID)},
        "groups": {},
    }
    for name, files in GROUPS.items():
        rows = load_group(norm, files)
        report["groups"][name] = {"files": files, "loaded_with_market": len(rows), **fit_group(rows)}
        g = report["groups"][name]
        print(name, g.get("status"), "n=", g.get("n"), "adopt=", g.get("adopt_for_research"),
              "best=", (g.get("train_best") or {}).get("lambda3"),
              (g.get("train_best") or {}).get("temperature"), flush=True)
    out = project / "05_交付" / "score_params_by_league.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
