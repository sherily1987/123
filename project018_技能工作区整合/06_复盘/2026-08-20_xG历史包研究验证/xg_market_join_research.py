"""研究脚本（research-only，不改任何生产概率文件/不 bump 版本）。

目的：用外部 xG 历史包（2014-2022，14584 场，Understat 口径）+ 仓库现有
big5_odds_full.csv（市场赔率）配对同场比赛，重新验证：
  1) xG-as-lambda（Dixon-Coles）vs 实际结果 vs 市场赔率去水后的 Brier/LogLoss
  2) 逐联赛 rho 网格搜索，看是否比全局固定 -0.08 有稳健收益（用配对 bootstrap 给 CI）

数据来源：
  - xG: C:\\Users\\Administrator\\AppData\\Local\\Temp\\xg_inspect\\top5_match_level_xg_2014_2022.csv
        （用户上传的「欧洲五大联赛_xG数据包_2014-2025.zip」，已核验 sha256）
  - 赔率: project018_技能工作区整合/04_素材/shared-data/football-quant-fusion/datasets/big5_odds_full.csv
        （仓库现有唯一事实源，MarketAvg 列）

产出：本目录 xg_market_join_report_20260820.json + 复盘 md（人工整理）。
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

XG_CSV = Path(r"C:\Users\Administrator\AppData\Local\Temp\xg_inspect\top5_match_level_xg_2014_2022.csv")
ODDS_CSV = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\datasets\big5_odds_full.csv")

LEAGUE_MAP = {
    "EPL": "英超",
    "La_liga": "西甲",
    "Bundesliga": "德甲",
    "Serie_A": "意甲",
    "Ligue_1": "法甲",
}

# xG 包名字 -> 赔率库名字（人工核对两侧队名清单后建立，仅覆盖有差异的）
TEAM_ALIAS = {
    # EPL
    "Manchester City": "Man City", "Manchester United": "Man United",
    "Newcastle United": "Newcastle", "Nottingham Forest": "Nott'm Forest",
    "Queens Park Rangers": "QPR", "West Bromwich Albion": "West Brom",
    "Wolverhampton Wanderers": "Wolves",
    # La Liga
    "Athletic Club": "Ath Bilbao", "Atletico Madrid": "Ath Madrid",
    "Real Betis": "Betis", "Celta Vigo": "Celta", "Deportivo La Coruna": "La Coruna",
    "Espanyol": "Espanol", "SD Huesca": "Huesca", "Real Sociedad": "Sociedad",
    "Sporting Gijon": "Sp Gijon", "Real Valladolid": "Valladolid",
    "Rayo Vallecano": "Vallecano",
    # Bundesliga
    "Arminia Bielefeld": "Bielefeld", "Bayer Leverkusen": "Leverkusen",
    "Borussia Dortmund": "Dortmund", "Borussia M.Gladbach": "M'gladbach",
    "Eintracht Frankfurt": "Ein Frankfurt", "FC Cologne": "FC Koln",
    "Fortuna Duesseldorf": "Fortuna Dusseldorf", "Greuther Fuerth": "Greuther Furth",
    "Hamburger SV": "Hamburg", "Hannover 96": "Hannover", "Hertha Berlin": "Hertha",
    "Mainz 05": "Mainz", "Nuernberg": "Nurnberg", "RasenBallsport Leipzig": "RB Leipzig",
    "VfB Stuttgart": "Stuttgart",
    # Serie A
    "AC Milan": "Milan", "Parma Calcio 1913": "Parma", "SPAL 2013": "Spal",
    # Ligue 1
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
                rows.append({
                    "league_cn": LEAGUE_MAP[r["league"]],
                    "date": r["date"][:10],
                    "home": r["home_team"], "away": r["away_team"],
                    "home_key": norm(r["home_team"]), "away_key": norm(r["away_team"]),
                    "home_goals": int(r["home_goals"]), "away_goals": int(r["away_goals"]),
                    "home_xg": float(r["home_xG"]), "away_xg": float(r["away_xG"]),
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

    LEAGUE_EN = {v: k for k, v in LEAGUE_MAP.items()}
    joined = []
    for r in xg_rows:
        key = (r["league_cn"], r["date"], r["home_key"], r["away_key"])
        cands = odds_idx.get(key)
        if not cands:
            continue
        oh, od, oa = cands[0]
        mh, md, ma = devig(oh, od, oa)
        idx = 0 if r["home_goals"] > r["away_goals"] else (2 if r["home_goals"] < r["away_goals"] else 1)
        joined.append({**r, "market": (mh, md, ma), "actual_idx": idx})

    print(f"xG rows: {len(xg_rows)}, odds-indexed keys: {len(odds_idx)}, joined: {len(joined)}", file=sys.stderr)

    by_league = defaultdict(list)
    for r in joined:
        by_league[r["league_cn"]].append(r)

    report = {"total_xg_rows": len(xg_rows), "joined_n": len(joined), "leagues": {}}

    for league, rows in by_league.items():
        best = None
        rho_grid = [round(x, 2) for x in [-0.20 + 0.01 * i for i in range(0, 25)]]
        for rho in rho_grid:
            bs = []
            for r in rows:
                m = dc_matrix(r["home_xg"], r["away_xg"], rho)
                p = dc_probs(m)
                bs.append(brier(p, r["actual_idx"]))
            mean_b = sum(bs) / len(bs)
            if best is None or mean_b < best[1]:
                best = (rho, mean_b)

        # 用最优 rho 和固定 -0.08 分别算全量指标，同时对比市场
        def compute(rho_val):
            bs, lls, hits = [], [], []
            for r in rows:
                m = dc_matrix(r["home_xg"], r["away_xg"], rho_val)
                p = dc_probs(m)
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

        # 配对 delta（xG-as-lambda fixed rho vs market），bootstrap CI
        import random
        random.seed(20260820)
        deltas = []
        for r in rows:
            m = dc_matrix(r["home_xg"], r["away_xg"], -0.08)
            p = dc_probs(m)
            deltas.append(brier(p, r["actual_idx"]) - brier(r["market"], r["actual_idx"]))
        n = len(deltas)
        boot_means = []
        for _ in range(2000):
            sample = [deltas[random.randrange(n)] for _ in range(n)]
            boot_means.append(sum(sample) / n)
        boot_means.sort()
        ci_lo, ci_hi = boot_means[int(0.025 * 2000)], boot_means[int(0.975 * 2000)]
        mean_delta = sum(deltas) / n

        report["leagues"][league] = {
            "n": len(rows),
            "market": market_stat,
            "xg_fixed_rho_-0.08": fixed_stat,
            "xg_best_rho": {"rho": best[0], **best_stat},
            "delta_fixed_vs_market_brier": {
                "mean": round(mean_delta, 6),
                "ci95": [round(ci_lo, 6), round(ci_hi, 6)],
                "significant": not (ci_lo <= 0 <= ci_hi),
            },
        }

    out_path = Path(__file__).parent / "xg_market_join_report_20260820.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
