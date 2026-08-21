"""研究脚本 v2（research-only，不改任何生产概率文件/不 bump 版本）。

修正 v1 的方法论错误：v1 误用了赛后实际 xG（home_xG/away_xG，来自
top5_match_level_xg_2014_2022.csv）当作预测输入，构成数据泄漏——用赛后
已知信息"预测"该场比赛，结果虚高（Brier ~0.50 vs 市场 ~0.58，delta 显著
且好得不合常理）。README 明确警告过这一点，v1 报告 xg_market_join_report_20260820.json
作废，不得引用。

v2 改用 top5_prematch_rolling_xg_features_2014_2022.csv 里的赛前滚动特征
（home_xG_l10 / away_xG_l10：比赛前最近10场平均 xG），只用比赛发生前已知
的信息，这才是与生产 hybrid_shadow.py 的 lambda_prior 语义对齐的用法。

数据来源：
  - xG 滚动特征: C:\\Users\\Administrator\\AppData\\Local\\Temp\\xg_inspect\\
        top5_prematch_rolling_xg_features_2014_2022.csv（用户上传，已核验 sha256）
  - 赔率: project018_技能工作区整合/04_素材/shared-data/football-quant-fusion/
        datasets/big5_odds_full.csv（仓库现有唯一事实源，MarketAvg 列）

门槛：要求 home/away 的 l10 滚动窗口已填满（history_games >= 10），
avoid 用不足样本的滚动均值当 lambda（这与生产 min_history 门槛精神一致）。
"""
from __future__ import annotations

import csv
import json
import math
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

XG_CSV = Path(r"C:\Users\Administrator\AppData\Local\Temp\xg_inspect\top5_prematch_rolling_xg_features_2014_2022.csv")
ODDS_CSV = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\datasets\big5_odds_full.csv")

LEAGUE_MAP = {"EPL": "英超", "La_liga": "西甲", "Bundesliga": "德甲", "Serie_A": "意甲", "Ligue_1": "法甲"}

TEAM_ALIAS = {
    "Manchester City": "Man City", "Manchester United": "Man United",
    "Newcastle United": "Newcastle", "Nottingham Forest": "Nott'm Forest",
    "Queens Park Rangers": "QPR", "West Bromwich Albion": "West Brom",
    "Wolverhampton Wanderers": "Wolves",
    "Athletic Club": "Ath Bilbao", "Atletico Madrid": "Ath Madrid",
    "Real Betis": "Betis", "Celta Vigo": "Celta", "Deportivo La Coruna": "La Coruna",
    "Espanyol": "Espanol", "SD Huesca": "Huesca", "Real Sociedad": "Sociedad",
    "Sporting Gijon": "Sp Gijon", "Real Valladolid": "Valladolid",
    "Rayo Vallecano": "Vallecano",
    "Arminia Bielefeld": "Bielefeld", "Bayer Leverkusen": "Leverkusen",
    "Borussia Dortmund": "Dortmund", "Borussia M.Gladbach": "M'gladbach",
    "Eintracht Frankfurt": "Ein Frankfurt", "FC Cologne": "FC Koln",
    "Fortuna Duesseldorf": "Fortuna Dusseldorf", "Greuther Fuerth": "Greuther Furth",
    "Hamburger SV": "Hamburg", "Hannover 96": "Hannover", "Hertha Berlin": "Hertha",
    "Mainz 05": "Mainz", "Nuernberg": "Nurnberg", "RasenBallsport Leipzig": "RB Leipzig",
    "VfB Stuttgart": "Stuttgart",
    "AC Milan": "Milan", "Parma Calcio 1913": "Parma", "SPAL 2013": "Spal",
    "GFC Ajaccio": "Ajaccio GFCO", "Clermont Foot": "Clermont",
    "Paris Saint Germain": "Paris SG", "SC Bastia": "Bastia",
    "Saint-Etienne": "St Etienne",
}


def norm(name: str) -> str:
    name = TEAM_ALIAS.get(name, name)
    return re.sub(r"[^a-z0-9]", "", name.lower())


def load_xg():
    rows = []
    with open(XG_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                if int(r["home_history_games"]) < 10 or int(r["away_history_games"]) < 10:
                    continue
                if not r["home_xG_l10"] or not r["away_xG_l10"]:
                    continue
                rows.append({
                    "league_cn": LEAGUE_MAP[r["league"]],
                    "date": r["date"][:10],
                    "home": r["home_team"], "away": r["away_team"],
                    "home_key": norm(r["home_team"]), "away_key": norm(r["away_team"]),
                    "home_goals": int(r["target_home_goals"]), "away_goals": int(r["target_away_goals"]),
                    "home_xg_l10": float(r["home_xG_l10"]), "away_xg_l10": float(r["away_xG_l10"]),
                })
            except (KeyError, ValueError):
                continue
    return rows


def load_odds():
    idx = defaultdict(list)
    with open(ODDS_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            h, d, a = r.get("x2_MarketAvg_h"), r.get("x2_MarketAvg_d"), r.get("x2_MarketAvg_a")
            if not (h and d and a):
                continue
            try:
                oh, od, oa = float(h), float(d), float(a)
            except ValueError:
                continue
            key = (r["league"], r["match_date"], norm(r["home"]), norm(r["away"]))
            idx[key].append((oh, od, oa))
    return idx


def devig(oh, od, oa):
    ih, idr, ia = 1 / oh, 1 / od, 1 / oa
    s = ih + idr + ia
    return ih / s, idr / s, ia / s


def dc_matrix(lh, la, rho, n=10):
    from math import exp, factorial
    m = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            pi = exp(-lh) * lh ** i / factorial(i)
            pj = exp(-la) * la ** j / factorial(j)
            if i == 0 and j == 0:
                tau = 1 - lh * la * rho
            elif i == 0 and j == 1:
                tau = 1 + lh * rho
            elif i == 1 and j == 0:
                tau = 1 + la * rho
            elif i == 1 and j == 1:
                tau = 1 - rho
            else:
                tau = 1.0
            m[i][j] = pi * pj * tau
    return m


def dc_probs(m):
    n = len(m)
    ph = sum(m[i][j] for i in range(n) for j in range(n) if i > j)
    pd = sum(m[i][j] for i in range(n) for j in range(n) if i == j)
    pa = sum(m[i][j] for i in range(n) for j in range(n) if i < j)
    s = ph + pd + pa
    return ph / s, pd / s, pa / s


def brier(p, idx):
    return sum((p[k] - (1.0 if k == idx else 0.0)) ** 2 for k in range(3))


def logloss(p, idx):
    return -math.log(max(1e-12, p[idx]))


def main():
    xg_rows = load_xg()
    odds_idx = load_odds()

    joined = []
    for r in xg_rows:
        # 赔率 CSV 的 league 字段是中文（英超/西甲/德甲/意甲/法甲），与 r["league_cn"] 对齐
        key = (r["league_cn"], r["date"], r["home_key"], r["away_key"])
        cands = odds_idx.get(key)
        if not cands:
            continue
        oh, od, oa = cands[0]
        mh, md, ma = devig(oh, od, oa)
        idx = 0 if r["home_goals"] > r["away_goals"] else (2 if r["home_goals"] < r["away_goals"] else 1)
        joined.append({**r, "market": (mh, md, ma), "actual_idx": idx})

    print(f"xG rows (min_history>=10): {len(xg_rows)}, joined with odds: {len(joined)}", file=sys.stderr)

    by_league = defaultdict(list)
    for r in joined:
        by_league[r["league_cn"]].append(r)

    report = {
        "note": "v2 修正版：赛前滚动 xG_l10 作为 lambda，非赛后实际 xG。min_history>=10。",
        "total_prematch_rows_min_history10": len(xg_rows),
        "joined_n": len(joined),
        "leagues": {},
    }

    for league, rows in sorted(by_league.items()):
        rho_grid = [round(-0.20 + 0.01 * i, 2) for i in range(25)]
        best = None
        for rho in rho_grid:
            bs = []
            for r in rows:
                p = dc_probs(dc_matrix(r["home_xg_l10"], r["away_xg_l10"], rho))
                bs.append(brier(p, r["actual_idx"]))
            mean_b = sum(bs) / len(bs)
            if best is None or mean_b < best[1]:
                best = (rho, mean_b)

        def compute(rho_val):
            bs, lls, hits = [], [], []
            for r in rows:
                p = dc_probs(dc_matrix(r["home_xg_l10"], r["away_xg_l10"], rho_val))
                bs.append(brier(p, r["actual_idx"]))
                lls.append(logloss(p, r["actual_idx"]))
                hits.append(int(max(range(3), key=lambda k: p[k]) == r["actual_idx"]))
            return {
                "brier_mean": round(sum(bs) / len(bs), 6),
                "log_loss_mean": round(sum(lls) / len(lls), 6),
                "accuracy_pct": round(sum(hits) / len(hits) * 100, 2),
            }

        market_bs = [brier(r["market"], r["actual_idx"]) for r in rows]
        market_stat = {
            "brier_mean": round(sum(market_bs) / len(market_bs), 6),
            "log_loss_mean": round(sum(logloss(r["market"], r["actual_idx"]) for r in rows) / len(rows), 6),
        }
        fixed_stat = compute(-0.08)
        best_stat = compute(best[0])

        random.seed(20260820)
        deltas_fixed = []
        deltas_best = []
        for r in rows:
            p_fixed = dc_probs(dc_matrix(r["home_xg_l10"], r["away_xg_l10"], -0.08))
            p_best = dc_probs(dc_matrix(r["home_xg_l10"], r["away_xg_l10"], best[0]))
            deltas_fixed.append(brier(p_fixed, r["actual_idx"]) - brier(r["market"], r["actual_idx"]))
            deltas_best.append(brier(p_best, r["actual_idx"]) - brier(r["market"], r["actual_idx"]))

        def boot_ci(deltas):
            n = len(deltas)
            means = []
            for _ in range(2000):
                sample = [deltas[random.randrange(n)] for _ in range(n)]
                means.append(sum(sample) / n)
            means.sort()
            lo, hi = means[int(0.025 * 2000)], means[int(0.975 * 2000)]
            mean_d = sum(deltas) / n
            return {"mean": round(mean_d, 6), "ci95": [round(lo, 6), round(hi, 6)], "significant": not (lo <= 0 <= hi)}

        report["leagues"][league] = {
            "n": len(rows),
            "market": market_stat,
            "xg_l10_fixed_rho_-0.08": fixed_stat,
            "xg_l10_best_rho": {"rho": best[0], **best_stat},
            "delta_fixed_vs_market_brier": boot_ci(deltas_fixed),
            "delta_bestrho_vs_market_brier": boot_ci(deltas_best),
        }

    out_path = Path(__file__).parent / "xg_market_join_report_v2_20260820.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
