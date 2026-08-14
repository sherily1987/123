#!/usr/bin/env python3
"""通用联赛历史赛果下载器（API-Football 免费版，2022–2024 赛季）。

把 project004/008/009/010/011 反复出现的「同模板联赛下载脚本」收编为单入口：
- /fixtures?league=<id>&season=Y 一次返回整季全部场次，每个赛季只调 1 次；
- 断点续传：raw JSON 已存在且 results>0 则跳过；
- 限速：默认 7 秒/请求（免费版 10 次/分钟）；
- 输出到目标项目文件夹（按全局工作台 SOP）：
  - raw JSON → <项目>/04_素材/apifootball_raw/<slug>_{season}.json
  - CSV → <项目>/04_素材/标准化/<slug>_results_2022_2024.csv

用法:
  python download_league_history.py --league-id 103 --league-name Eliteserien \
      --slug eliteserien --project <目标项目路径>
  python download_league_history.py --league-id 103 --league-name Eliteserien \
      --slug eliteserien --project <项目路径> --delay 0   # 已拉过时快速重合并
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
ADAPTER = HERE / "api_football_adapter.py"
SEASONS_DEFAULT = [2022, 2023, 2024]
COLUMNS = ["competition", "season_end_year", "date", "home", "away",
           "home_goals", "away_goals", "status", "source"]


def fetch_season(league_id, slug, project, season, delay):
    raw_dir = project / "04_素材" / "apifootball_raw"
    out = raw_dir / f"{slug}_{season}.json"
    if out.exists():
        try:
            if json.loads(out.read_text(encoding="utf-8")).get("results", 0) > 0:
                return out, "skipped"
        except Exception:
            pass
    raw_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(ADAPTER), "fixtures", "--league", str(league_id),
         "--season", str(season), "--output", str(out)],
        text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{season} 拉取失败: {(proc.stderr or proc.stdout)[-300:]}")
    if delay:
        time.sleep(delay)
    return out, "fetched"


def season_rows(league_name, slug, project, season):
    raw = project / "04_素材" / "apifootball_raw" / f"{slug}_{season}.json"
    data = json.loads(raw.read_text(encoding="utf-8"))
    rows = []
    for m in data.get("response", []):
        goals = m.get("goals") or {}
        rows.append({
            "competition": league_name,
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
    ap = argparse.ArgumentParser(description="通用联赛历史赛果下载器（API-Football 免费版）")
    ap.add_argument("--league-id", type=int, required=True, help="API-Football league id（如 103=挪超、244=芬超）")
    ap.add_argument("--league-name", required=True, help="联赛英文名（用于 CSV competition 列）")
    ap.add_argument("--slug", required=True, help="文件前缀 slug（小写，如 eliteserien）")
    ap.add_argument("--project", required=True, help="目标项目文件夹绝对路径（输出写入其 04_素材/）")
    ap.add_argument("--seasons", nargs="+", type=int, default=SEASONS_DEFAULT, help="赛季列表，默认 2022 2023 2024")
    ap.add_argument("--delay", type=float, default=7.0, help="请求间隔秒数，默认 7")
    a = ap.parse_args()

    project = Path(a.project)
    if not project.exists():
        project.mkdir(parents=True, exist_ok=True)
    for season in a.seasons:
        path, status = fetch_season(a.league_id, a.slug, project, season, a.delay)
        print(f"{a.league_name} {season}: {status}（{len(season_rows(a.league_name, a.slug, project, season))} 场）", flush=True)

    rows = [r for s in a.seasons for r in season_rows(a.league_name, a.slug, project, s)]
    rows.sort(key=lambda r: (r["season_end_year"], r["date"]))
    out_csv = project / "04_素材" / "标准化" / f"{a.slug}_results_{a.seasons[0]}_{a.seasons[-1]}.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print("CSV 已写入:", out_csv)
    print(f"  {a.league_name}: 共 {len(rows)} 场")


if __name__ == "__main__":
    main()
