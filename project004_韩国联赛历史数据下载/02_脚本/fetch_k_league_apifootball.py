#!/usr/bin/env python3
"""韩职 K1/K2 赛果批量获取 + 合并（复用 project007 api_football_adapter）。

- /fixtures?league=X&season=Y 一次返回整赛季全部场次，每个(联赛,赛季)只调 1 次；
- 断点续传：raw JSON 已存在且 results>0 则跳过；
- 限速：默认 7 秒/请求（免费版 10 次/分钟）；
- 输出：
  - raw JSON → 04_素材/apifootball_raw/{k1,k2}_{season}.json
  - 合并 CSV → 04_素材/标准化/k_league_1_2_results_2014_2024.csv
    （fbref 2014-2021 + apifootball 2022-2024，每赛季单一数据源，
      避免跨源队名拼写差异导致重复）

用法:
  python fetch_k_league_apifootball.py            # k1+k2, 2022-2024
  python fetch_k_league_apifootball.py --leagues k1 --delay 0   # 仅 K1 不等待
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent
ADAPTER = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\api_football_adapter.py"
)
RAW_DIR = PROJ / "04_素材" / "apifootball_raw"
OUT_CSV = PROJ / "04_素材" / "标准化" / "k_league_1_2_results_2014_2024.csv"
FBREF_K1 = PROJ / "04_素材" / "csv" / "K-League-1_fbref_match_results.csv"

LEAGUES = {"k1": (292, "K League 1"), "k2": (293, "K League 2")}
SEASONS = [2022, 2023, 2024]
COLUMNS = ["competition", "season_end_year", "date", "home", "away",
           "home_goals", "away_goals", "status", "source"]


def fetch_league_season(league, season, delay):
    out = RAW_DIR / f"{league}_{season}.json"
    if out.exists():
        try:
            if json.loads(out.read_text(encoding="utf-8")).get("results", 0) > 0:
                return out, "skipped"
        except Exception:
            pass
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(ADAPTER), "fixtures", "--league", str(LEAGUES[league][0]),
         "--season", str(season), "--output", str(out)],
        text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{league} {season} 拉取失败: {(proc.stderr or proc.stdout)[-300:]}")
    if delay:
        time.sleep(delay)
    return out, "fetched"


def api_rows(league, season):
    raw = RAW_DIR / f"{league}_{season}.json"
    data = json.loads(raw.read_text(encoding="utf-8"))
    name = LEAGUES[league][1]
    rows = []
    for m in data.get("response", []):
        goals = m.get("goals") or {}
        rows.append({
            "competition": name,
            "season_end_year": season,
            "date": m["fixture"]["date"][:10],
            "home": m["teams"]["home"]["name"],
            "away": m["teams"]["away"]["name"],
            "home_goals": goals.get("home"),
            "away_goals": goals.get("away"),
            "status": m["fixture"]["status"].get("short"),
            "source": "apifootball",
        })
    return rows


def fbref_rows():
    rows = []
    if not FBREF_K1.exists():
        return rows
    with open(FBREF_K1, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            year = int(float(r["Season_End_Year"]))
            if year > 2021:
                continue
            hg = r.get("HomeGoals")
            ag = r.get("AwayGoals")
            rows.append({
                "competition": "K League 1",
                "season_end_year": year,
                "date": r["Date"],
                "home": r["Home"],
                "away": r["Away"],
                "home_goals": int(float(hg)) if hg not in ("", None) else None,
                "away_goals": int(float(ag)) if ag not in ("", None) else None,
                "status": "FT",
                "source": "fbref",
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="k1,k2")
    ap.add_argument("--delay", type=float, default=7.0)
    a = ap.parse_args()
    selected = [x.strip() for x in a.leagues.split(",") if x.strip()]

    for league in selected:
        if league not in LEAGUES:
            sys.exit(f"未知联赛: {league}，可选 k1/k2")
        for season in SEASONS:
            path, status = fetch_league_season(league, season, a.delay)
            rows = api_rows(league, season)
            print(f"{league} {season}: {status}（{len(rows)} 场）", flush=True)

    all_rows = fbref_rows() + [r for lg in selected for s in SEASONS for r in api_rows(lg, s)]
    seen = set()
    dedup = []
    for r in all_rows:
        key = (r["competition"], r["season_end_year"], r["date"], r["home"], r["away"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    dedup.sort(key=lambda r: (r["competition"], r["season_end_year"], r["date"]))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(dedup)

    by_comp = {}
    for r in dedup:
        by_comp.setdefault(r["competition"], 0)
        by_comp[r["competition"]] += 1
    print("合并 CSV 已写入:", OUT_CSV)
    for comp, n in sorted(by_comp.items()):
        print(f"  {comp}: {n} 场")


if __name__ == "__main__":
    main()
