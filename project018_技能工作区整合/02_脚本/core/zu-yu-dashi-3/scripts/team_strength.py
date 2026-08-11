#!/usr/bin/env python3
"""team_strength — Dixon-Coles 团队强度模型（时间衰减，R1①）。

数据：football-data 五大联赛 46696 场（含 1X2 赔率与全场比分）。
模型：λ_home = exp(home_adv + α_home + β_away)，λ_away = exp(α_away + β_home)；
目标：时间衰减加权的泊松对数似然 + Dixon-Coles τ 修正（ρ=-0.08，与引擎一致）；
权重：w = exp(-ln2·(t_max − t_match)/half_life)；
拟合：scipy L-BFGS，soft 约束 Σα≈0（拟合后重归一化）。

用途：
1) 无盘口比赛的 model_first λ（替代 Elo 启发式）；
2) 官方前瞻 λ 先验的对手强度调整；
3) 与市场 λ 对照量化分歧。
注意：仅覆盖五大联赛球队；芬超/瑞超/巴西甲等需另行按联赛拟合。
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

try:
    from predict import matrix as dc_matrix, one as dc_one
except ImportError:
    dc_matrix = dc_one = None


RHO = -0.08


# [中文功能] 解析日期（ISO 或 dd/mm/yy、dd/mm/yyyy）
def parse_day(value):
    if not value:
        return None
    s = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d.toordinal()
        except ValueError:
            continue
    return None


# [中文功能] 加载含赔率的比赛（可选按日期截止）
def load_matches(jsonl_path, train_until=None, league_id=None, require_odds=True):
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if not r.get("actual") or (require_odds and not r.get("odds")):
                continue
            if league_id is not None and str(r.get("league_id")) != str(league_id):
                continue
            rf = r.get("raw_fields") or {}
            day = parse_day(r.get("kickoff")) or parse_day(rf.get("Date"))
            if day is None:
                continue
            if train_until and day > train_until:
                continue
            match = {
                "home": r.get("home"), "away": r.get("away"),
                "gh": int(r["actual"][0]), "ga": int(r["actual"][1]),
                "day": day, "league": str(r.get("league_id") or r.get("competition") or r.get("stage") or r.get("div") or "?"),
                "odds": [float(x) for x in r.get("odds", [])[:3]],
            }
            provider_market = r.get("provider_market_1x2")
            if isinstance(provider_market, list) and len(provider_market) == 3 and all(isinstance(x, (int, float)) and x > 0 for x in provider_market):
                match["provider_market"] = [float(x) for x in provider_market]
            rows.append(match)
    return rows


# [中文功能] 时间衰减权重
def decay_weights(days, half_life):
    if half_life <= 0:
        return np.ones(len(days))
    return np.exp(-np.log(2.0) * (days.max() - days) / half_life)


# [中文功能] 泊松对数似然
def pois_ll(k, lam):
    lam = np.maximum(lam, 1e-9)
    return k * np.log(lam) - lam - np.array([math.lgamma(x + 1) for x in k])


# [中文功能] DC τ 对数修正及梯度
def tau_terms(lh, la, gh, ga, rho):
    lt = np.zeros(len(lh))
    dlh = np.zeros(len(lh))
    dla = np.zeros(len(lh))
    for (i, j) in ((0, 0), (1, 0), (0, 1), (1, 1)):
        m = (gh == i) & (ga == j)
        if not m.any():
            continue
        if (i, j) == (0, 0):
            t = 1 + lh[m] * la[m] * rho
            lt[m] = np.log(np.maximum(t, 1e-9))
            dlh[m] = la[m] * rho / np.maximum(t, 1e-9)
            dla[m] = lh[m] * rho / np.maximum(t, 1e-9)
        elif (i, j) == (1, 0):
            t = 1 - la[m] * rho
            lt[m] = np.log(np.maximum(t, 1e-9))
            dla[m] = -rho / np.maximum(t, 1e-9)
        elif (i, j) == (0, 1):
            t = 1 - lh[m] * rho
            lt[m] = np.log(np.maximum(t, 1e-9))
            dlh[m] = -rho / np.maximum(t, 1e-9)
        else:
            lt[m] = math.log(max(1 + rho, 1e-9))
    return lt, dlh, dla


# [中文功能] 构建模型对象并拟合
def fit_model(matches, half_life=500.0, penalty=1e-3, max_iter=200):
    teams = sorted({m["home"] for m in matches} | {m["away"] for m in matches})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = np.array([idx[m["home"]] for m in matches])
    ai = np.array([idx[m["away"]] for m in matches])
    gh = np.array([m["gh"] for m in matches])
    ga = np.array([m["ga"] for m in matches])
    days = np.array([m["day"] for m in matches])
    w = decay_weights(days, half_life)

    def unpack(p):
        return p[0], p[1:1 + n], p[1 + n:]

    def objective(p):
        adv, al, be = unpack(p)
        lh = np.exp(adv + al[hi] + be[ai])
        la = np.exp(al[ai] + be[hi])
        ll = w * (pois_ll(gh, lh) + pois_ll(ga, la))
        lt, _, _ = tau_terms(lh, la, gh, ga, RHO)
        loss = -(ll.sum() + (w * lt).sum()) + penalty * al.sum() ** 2
        return loss

    def gradient(p):
        adv, al, be = unpack(p)
        lh = np.exp(adv + al[hi] + be[ai])
        la = np.exp(al[ai] + be[hi])
        lt, dlh, dla = tau_terms(lh, la, gh, ga, RHO)
        grad = np.zeros_like(p)
        grad[0] = -(w * ((gh - lh) + dlh)).sum()
        g_alpha = np.zeros(n)
        g_beta = np.zeros(n)
        np.add.at(g_alpha, hi, -(w * ((gh - lh) + dlh)))
        np.add.at(g_alpha, ai, -(w * ((ga - la) + dla)))
        np.add.at(g_beta, ai, -(w * ((gh - lh) + dlh)))
        np.add.at(g_beta, hi, -(w * ((ga - la) + dla)))
        grad[1:1 + n] = g_alpha + 2 * penalty * al.sum()
        grad[1 + n:] = g_beta
        return grad

    p0 = np.zeros(1 + 2 * n)
    p0[0] = 0.2
    res = minimize(objective, p0, jac=gradient, method="L-BFGS-B",
                   options={"maxiter": max_iter, "ftol": 1e-8})
    adv, al, be = unpack(res.x)
    # 重归一化：Σα=0，把均值转移进 home_adv（保持 λ 不变）
    mean_al = al.mean()
    al = al - mean_al
    adv = adv + mean_al
    # 每队加权样本量与最后比赛日
    sw = np.zeros(n)
    last = np.zeros(n)
    np.add.at(sw, hi, w)
    np.add.at(sw, ai, w)
    np.maximum.at(last, hi, days)
    np.maximum.at(last, ai, days)
    return {
        "teams": teams, "home_adv": float(adv),
        "alpha": [float(x) for x in al], "beta": [float(x) for x in be],
        "weighted_n": [float(x) for x in sw], "last_day": [float(x) for x in last],
        "half_life": half_life, "n_matches": len(matches),
        "max_day": float(days.max()), "converged": res.success,
        "nit": int(res.nit), "fun": float(res.fun), "rho": RHO,
    }


# [中文功能] 用已拟合模型预测一场（无盘口 model_first λ + 1X2）
def predict_match(model, home, away, day=None):
    if home not in model["teams"] or away not in model["teams"]:
        return {"status": "UNFITTED_TEAM", "note": "球队不在拟合覆盖内（五大联赛外或无记录）"}
    i = model["teams"].index(home)
    j = model["teams"].index(away)
    lh = math.exp(model["home_adv"] + model["alpha"][i] + model["beta"][j])
    la = math.exp(model["alpha"][j] + model["beta"][i])
    probs = None
    if dc_matrix is not None:
        probs = dc_one(dc_matrix(lh, la, RHO))
    return {
        "status": "VALID", "home": home, "away": away,
        "lambda_home": round(lh, 4), "lambda_away": round(la, 4),
        "home_adv": round(model["home_adv"], 4),
        "probs_1x2": [round(x, 4) for x in probs] if probs else None,
        "source": "dixon_coles_team_strength",
    }


# [中文功能] 市场 1X2（比例去水）
def market_probs(odds):
    q = [1.0 / x for x in odds]
    s = sum(q)
    return [x / s for x in q]


# [中文功能] 时间切分 OOS 验证：模型 vs 市场 vs 频率基线
def validate(matches, model, from_day, half_life=500.0, to_day=None, baseline_key="market", baseline_label="market"):
    test = [m for m in matches if m["day"] >= from_day and (to_day is None or m["day"] < to_day)]
    rows = []
    skip = 0
    for m in test:
        if m["home"] not in model["teams"] or m["away"] not in model["teams"]:
            skip += 1
            continue
        i = model["teams"].index(m["home"])
        j = model["teams"].index(m["away"])
        lh = math.exp(model["home_adv"] + model["alpha"][i] + model["beta"][j])
        la = math.exp(model["alpha"][j] + model["beta"][i])
        mp = dc_one(dc_matrix(lh, la, RHO))
        row = {
            "league": m["league"], "day": m["day"],
            "actual_idx": 0 if m["gh"] > m["ga"] else (1 if m["gh"] == m["ga"] else 2),
            "model": mp,
        }
        if baseline_key == "market":
            baseline = market_probs(m["odds"]) if len(m["odds"]) == 3 and all(x > 1 for x in m["odds"]) else None
        else:
            baseline = m.get(baseline_key)
            if not (isinstance(baseline, list) and len(baseline) == 3 and all(isinstance(x, (int, float)) and x > 0 for x in baseline)):
                baseline = None
        if baseline is not None:
            row[baseline_label] = baseline
        rows.append(row)
    if not rows:
        return {"n": 0, "skip": skip}

    def metrics(key, rs=None):
        rs = rows if rs is None else rs
        bs = [sum((r[key][i] - (1 if i == r["actual_idx"] else 0)) ** 2 for i in range(3)) for r in rs]
        ll = [-math.log(max(1e-12, r[key][r["actual_idx"]])) for r in rs]
        hit = [int(max(range(3), key=lambda k: r[key][k]) == r["actual_idx"]) for r in rs]
        n = len(rs)
        return {
            "n": n, "brier_mean": round(sum(bs) / n, 6),
            "log_loss": round(sum(ll) / n, 6), "accuracy_pct": round(sum(hit) / n * 100, 2),
        }

    freq = {0: 0.0, 1: 0.0, 2: 0.0}
    for m in matches:
        if m["day"] < from_day:
            freq[0 if m["gh"] > m["ga"] else (1 if m["gh"] == m["ga"] else 2)] += 1
    tot = sum(freq.values())
    freq_p = [freq[i] / tot for i in range(3)]
    freq_bs = [sum((freq_p[i] - (1 if i == r["actual_idx"] else 0)) ** 2 for i in range(3)) for r in rows]
    freq_ll = [-math.log(max(1e-12, freq_p[r["actual_idx"]])) for r in rows]
    by_league = {}
    for r in rows:
        by_league.setdefault(r["league"], []).append(r)
    market_rows = [r for r in rows if baseline_label in r]
    market_report = (
        metrics(baseline_label, market_rows)
        if market_rows
        else {"status": "UNAVAILABLE", "reason": "no_pre_match_odds"}
    )

    def league_report(rs):
        market_rs = [r for r in rs if baseline_label in r]
        return {
            "n": len(rs),
            "model": metrics("model", rs),
            baseline_label: metrics(baseline_label, market_rs) if market_rs else {"status": "UNAVAILABLE", "reason": "no_pre_match_odds"},
        }

    return {
        "n": len(rows), "skip": skip,
        "model": metrics("model"),
        baseline_label: market_report,
        "frequency_baseline": {
            "n": len(rows), "brier_mean": round(sum(freq_bs) / len(rows), 6),
            "log_loss": round(sum(freq_ll) / len(rows), 6),
            "probs": [round(x, 4) for x in freq_p],
        },
        "by_league": {k: league_report(v) for k, v in by_league.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--input")
    ap.add_argument("--output")
    ap.add_argument("--half-life", type=float, default=500.0)
    ap.add_argument("--train-until", help="拟合截止日 YYYY-MM-DD（默认全部）")
    ap.add_argument("--league-id", help="仅加载指定联赛 ID")
    ap.add_argument("--results-only", action="store_true", help="允许加载无赛前赔率的已完场赛果")
    ap.add_argument("--predict-home")
    ap.add_argument("--predict-away")
    ap.add_argument("--ratings")
    ap.add_argument("--prior", action="store_true", help="输出可并入模型输入的 lambda_prior（对手强度调整）")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--from", dest="from_day", help="验证起始日 YYYY-MM-DD")
    ap.add_argument("--to", dest="to_day", help="验证结束日 YYYY-MM-DD（不含该日）")
    a = ap.parse_args()
    cutoff = parse_day(a.train_until) if a.train_until else None

    if a.fit:
        if not a.input:
            raise SystemExit("--fit 需要 --input")
        t0 = time.time()
        matches = load_matches(
            a.input,
            train_until=cutoff,
            league_id=a.league_id,
            require_odds=not a.results_only,
        )
        print(f"fit input matches: {len(matches)}（截止 {a.train_until or '全部'}）", flush=True)
        model = fit_model(matches, a.half_life)
        model["schema_version"] = "team-strength-1.0"
        model["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        model["source"] = "football-data 五大联赛"
        if a.output:
            Path(a.output).parent.mkdir(parents=True, exist_ok=True)
            Path(a.output).write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "status": "ok", "teams": len(model["teams"]), "n_matches": len(matches),
            "home_adv": model["home_adv"], "converged": model["converged"],
            "nit": model["nit"], "fit_seconds": round(time.time() - t0, 1), "output": a.output,
        }, ensure_ascii=False, indent=2))
        return

    if a.predict_home and a.predict_away:
        if not a.ratings:
            raise SystemExit("--predict 需要 --ratings")
        model = json.loads(Path(a.ratings).read_text(encoding="utf-8"))
        res = predict_match(model, a.predict_home, a.predict_away)
        if a.prior and res.get("status") == "VALID":
            prior = {
                "lambda_home": res["lambda_home"],
                "lambda_away": res["lambda_away"],
                "weight": 0.02,
                "source": "dixon_coles_team_strength",
                "sample_legs": None,
                "note": "DC团队强度(时间衰减半衰期500天)对手强度调整λ；系数未回测，作为软先验",
            }
            res["lambda_prior"] = prior
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    if a.validate:
        if not a.ratings or not a.from_day:
            raise SystemExit("--validate 需要 --ratings 与 --from YYYY-MM-DD")
        if not a.input:
            raise SystemExit("--validate 需要 --input")
        model = json.loads(Path(a.ratings).read_text(encoding="utf-8"))
        matches = load_matches(
            a.input,
            league_id=a.league_id,
            require_odds=not a.results_only,
        )
        rep = validate(matches, model, parse_day(a.from_day), a.half_life, parse_day(a.to_day) if a.to_day else None)
        rep["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        if a.output:
            Path(a.output).parent.mkdir(parents=True, exist_ok=True)
            Path(a.output).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return
    ap.print_help()


if __name__ == "__main__":
    main()
