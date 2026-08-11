#!/usr/bin/env python3
"""瑞超（Allsvenskan）赛果批量获取（复用 project007 api_football_adapter）。

与 project004/008/009 同一模式：
- /fixtures?league=113&season=Y 一次返回整季全部场次，每个赛季只调 1 次；
- 断点续传：raw JSON 已存在且 results>0 则跳过；
- 限速：默认 7 秒/请求（免费版 10 次/分钟）；
- 输出：
  - raw JSON → 04_素材/apifootball_raw/allsvenskan_{season}.json
  - CSV → 04_素材/标准化/allsvenskan_results_2022_2024.csv

用法:
  python fetch_allsvenskan_apifootball.py            # 2022-2024
  python fetch_allsvenskan_apifootball.py --delay 0  # 已拉过时快速重合并
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
OUT_CSV = PROJ / "04_素材" / "标准化" / "allsvenskan_results_2022_2024.csv"

LEAGUE_ID = 113
LEAGUE_NAME = "Allsvenskan"
SEASONS = [2022, 2023, 2024]
COLUMNS = ["competition", "season_end_year", "date", "home", "away",
           "home_goals", "away_goals", "status", "source"]


def fetch_season(season, delay):
    out = RAW_DIR / f"allsvenskan_{season}.json"
    if out.exists():
        try:
            if json.loads(out.read_text(encoding="utf-8")).get("results", 0) > 0:
                return out, "skipped"
        except Exception:
            pass
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(ADAPTER), "fixtures", "--league", str(LEAGUE_ID),
         "--season", str(season), "--output", str(out)],
        text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{season} 拉取失败: {(proc.stderr or proc.stdout)[-300:]}")
    if delay:
        time.sleep(delay)
    return out, "fetched"


def season_rows(season):
    raw = RAW_DIR / f"allsvenskan_{season}.json"
    data = json.loads(raw.read_text(encoding="utf-8"))
    rows = []
    for m in data.get("response", []):
        goals = m.get("goals") or {}
        rows.append({
            "competition": LEAGUE_NAME,
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=7.0)
    a = ap.parse_args()

    for season in SEASONS:
        path, status = fetch_season(season, a.delay)
        print(f"Allsvenskan {season}: {status}（{len(season_rows(season))} 场）", flush=True)

    rows = [r for s in SEASONS for r in season_rows(s)]
    rows.sort(key=lambda r: (r["season_end_year"], r["date"]))
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print("CSV 已写入:", OUT_CSV)
    print(f"  {LEAGUE_NAME}: 共 {len(rows)} 场")


if __name__ == "__main__":
    main()
