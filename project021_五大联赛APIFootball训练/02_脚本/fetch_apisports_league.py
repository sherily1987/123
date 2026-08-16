#!/usr/bin/env python3
"""拉取 api-sports.io 国内联赛赛果（无历史赔率）。

与 fetch_kor_k1.py 同口径：只写 event_result，不编造赔率。
无市场联赛由 run_full_backtest 的 no_market 组只比频率基线。
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROXY = "http://127.0.0.1:7897"


def get_key() -> str:
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        raise SystemExit("API_FOOTBALL_KEY 未设置")
    return key


def make_opener():
    proxy = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    return urllib.request.build_opener(proxy)


def call(opener, key: str, path: str, params: dict, retries: int = 3):
    url = f"https://v3.football.api-sports.io/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    last = None
    for i in range(retries):
        try:
            with opener.open(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            last = exc
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))
    raise RuntimeError(last)


def normalize(row: dict, league_id: int, league_name: str, season: int, collected_at: str) -> dict | None:
    fx = row.get("fixture") or {}
    teams = row.get("teams") or {}
    goals = row.get("goals") or {}
    home = (teams.get("home") or {}).get("name") or ""
    away = (teams.get("away") or {}).get("name") or ""
    hg, ag = goals.get("home"), goals.get("away")
    raw_status = ((fx.get("status") or {}).get("long") or "")
    status = "Finished" if raw_status.lower() in {"finished", "match finished"} else raw_status
    if not home or not away:
        return None
    return {
        "provider": "api-sports.io",
        "source_type": "event_result",
        "match_id": fx.get("id"),
        "league_id": league_id,
        "league_name": league_name,
        "season": season,
        "kickoff": (fx.get("date") or "")[:19],
        "home_id": (teams.get("home") or {}).get("id"),
        "home": home,
        "away_id": (teams.get("away") or {}).get("id"),
        "away": away,
        "actual": [int(hg), int(ag)] if hg is not None and ag is not None else None,
        "status": status,
        "collected_at": collected_at,
        "field_availability": {
            "statistics": "POST_MATCH",
            "lineup": "UNKNOWN",
            "player_statistics": "UNKNOWN",
        },
    }


def download(league_id: int, name: str, slug: str, seasons: list[int], output: Path) -> dict:
    key = get_key()
    opener = make_opener()
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows, errors = [], []
    for season in seasons:
        data = call(opener, key, "fixtures", {"league": league_id, "season": season})
        fixtures = data.get("response") or []
        kept = 0
        for item in fixtures:
            rec = normalize(item, league_id, name, season, collected_at)
            if rec:
                rows.append(rec)
                kept += 1
        print(f"赛季 {season}: {kept} 场", flush=True)
        if not fixtures:
            errors.append(f"{season}: empty response errors={data.get('errors')}")
        time.sleep(1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    finished = sum(1 for r in rows if str(r.get("status") or "").lower() == "finished" and r.get("actual"))
    return {
        "slug": slug, "league_id": league_id, "output": str(output),
        "rows": len(rows), "finished_with_score": finished, "errors": errors,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league-id", type=int, required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seasons", nargs="*", type=int, default=[2021, 2022, 2023, 2024, 2025, 2026])
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(download(args.league_id, args.name, args.slug, args.seasons, args.output),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
