#!/usr/bin/env python3
"""扩大排查：查 01-10~01-20 德甲+德国杯，找汉堡/勒沃库森。"""
import json
import os
import sys

sys.path.insert(0, r"F:\HM足球比赛预测\project007_APIFootball数据接入\02_脚本")
os.environ.setdefault("APIFOOTBALL_COM_KEY",
                      "2ed9a60dcca9457b4c8683d657342c1840559d5f097235846c764134e0e5d73d")

import apifootball_com_adapter as ad

# 德国杯 league_id
print("=== 找德国杯 league_id ===")
try:
    leagues = ad.request("get_leagues", {})
    rows = leagues if isinstance(leagues, list) else leagues.get("result", [])
    for lg in rows:
        name = str(lg.get("league_name") or "")
        if any(k in name.lower() for k in ("pokal", "cup", "dfb", "德国杯")):
            print("  ", lg.get("league_id"), name, "| season", lg.get("league_season"))
except Exception as exc:
    print("  ", str(exc)[:150])

# 查德甲 01-10~01-20 找汉堡/勒沃库森
print("\n=== 德甲 175 01-10~01-20 找汉堡/勒沃库森 ===")
try:
    events = ad.request("get_events", {"league_id": 175, "from": "2026-01-10", "to": "2026-01-20"})
    rows = events if isinstance(events, list) else events.get("result", [])
    print(f"  共 {len(rows)} 场")
    for e in rows:
        home = str(e.get("match_hometeam_name") or "")
        away = str(e.get("match_awayteam_name") or "")
        if any(k in home + away for k in ("Hamburg", "汉堡", "Leverkusen", "勒沃库森")):
            print(f"  ★ {e.get('match_date')} | {home} vs {away} | "
                  f"{e.get('match_hometeam_score')}-{e.get('match_awayteam_score')} | {e.get('match_status')} | id={e.get('match_id')}")
except Exception as exc:
    print("  ", str(exc)[:150])

# 查德国杯（假设 id 可能是 176 或其他），先列出 get_leagues 里 cup 类
print("\n=== 查德国杯候选 league_id 的 01-14 赛果 ===")
for lid in (176, 177, 44, 45, 46):
    try:
        events = ad.request("get_events", {"league_id": lid, "from": "2026-01-14", "to": "2026-01-14"})
        rows = events if isinstance(events, list) else events.get("result", [])
        if rows:
            print(f"  league_id={lid}: {len(rows)} 场")
            for e in rows[:8]:
                home = str(e.get("match_hometeam_name") or "")
                away = str(e.get("match_awayteam_name") or "")
                print(f"    {home} vs {away} | {e.get('match_hometeam_score')}-{e.get('match_awayteam_score')} | {e.get('match_status')}")
    except Exception:
        pass
