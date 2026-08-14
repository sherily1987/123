# -*- coding: utf-8 -*-
"""拉取韩职 K League 1 历史数据（api-sports.io，走 Clash 代理 7897）。

输出：标准化 events jsonl（与 saudi_pro_league 同 schema），供训练轨自动发现。
用法：python fetch_kor_k1.py
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LEAGUE_ID = 292
SEASONS = [2021, 2022, 2023, 2024, 2025, 2026]
OUT = Path(r"F:\HM足球比赛预测\project021_五大联赛APIFootball训练\04_素材\标准化\korea_k1_events.jsonl")
PROXY = "http://127.0.0.1:7897"


def get_key():
    key = os.environ.get("API_FOOTBALL_KEY", "")
    if not key:
        raise SystemExit("API_FOOTBALL_KEY 未设置")
    return key


def make_opener():
    proxy = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    return urllib.request.build_opener(proxy)


def call(opener, key, path, params, retries=3):
    url = f"https://v3.football.api-sports.io/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    for i in range(retries):
        try:
            with opener.open(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))
    return None


def main():
    key = get_key()
    opener = make_opener()
    fetched_at = datetime.now(timezone.utc).isoformat()
    total = 0
    lines = []
    errors = []

    for season in SEASONS:
        # api-sports fixtures 不支持 page 参数（一次返回全部，paging.total=1）
        d = call(opener, key, "fixtures", {"league": LEAGUE_ID, "season": season})
        if not d or "response" not in d:
            errors.append(f"{season}: 无响应 {str(d)[:80]}")
            continue
        res = d.get("response", [])
        season_count = 0
        for f in res:
            fx = f.get("fixture", {})
            teams = f.get("teams", {})
            goals = f.get("goals", {})
            status = (f.get("fixture") or {}).get("status", {}).get("long", "")
            home = (teams.get("home") or {}).get("name", "")
            away = (teams.get("away") or {}).get("name", "")
            home_id = (teams.get("home") or {}).get("id")
            away_id = (teams.get("away") or {}).get("id")
            hg = goals.get("home")
            ag = goals.get("away")
            record = {
                "provider": "api-sports.io",
                "source_type": "event_result",
                "match_id": fx.get("id"),
                "league_id": LEAGUE_ID,
                "league_name": "K League 1",
                "season": season,
                "kickoff": (fx.get("date") or "")[:19].replace("T", "T"),
                "home_id": home_id,
                "home": home,
                "away_id": away_id,
                "away": away,
                "actual": [hg, ag] if hg is not None and ag is not None else None,
                "status": status,
                "collected_at": fetched_at,
                "field_availability": {
                    "statistics": "POST_MATCH",
                    "lineup": "UNKNOWN",
                    "player_statistics": "UNKNOWN",
                },
            }
            lines.append(json.dumps(record, ensure_ascii=False))
            season_count += 1
            total += 1
        print(f"赛季 {season}: {season_count} 场", flush=True)
        time.sleep(1)

    with OUT.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n完成：共 {total} 场，输出 {OUT}")
    print(f"错误: {len(errors)}")
    for e in errors[:5]:
        print("  ", e)


if __name__ == "__main__":
    main()
