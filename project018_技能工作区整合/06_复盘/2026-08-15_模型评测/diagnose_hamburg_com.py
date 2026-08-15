#!/usr/bin/env python3
"""用 apifootball.com apiv3（APIFOOTBALL_COM_KEY）查汉堡 vs 勒沃库森赛果。"""
import json
import os
import sys

sys.path.insert(0, r"F:\HM足球比赛预测\project007_APIFootball数据接入\02_脚本")
os.environ.setdefault("APIFOOTBALL_COM_KEY",
                      "2ed9a60dcca9457b4c8683d657342c1840559d5f097235846c764134e0e5d73d")

import apifootball_com_adapter as ad

# 1. get_leagues 找德甲
print("=== get_leagues 找德甲 ===")
try:
    leagues = ad.request("get_leagues", {})
    rows = leagues if isinstance(leagues, list) else leagues.get("result", [])
    for lg in rows:
        name = str(lg.get("league_name") or lg.get("country_name") or "")
        if any(k in name.lower() for k in ("germany", "bundesliga", "德国", "德甲")):
            print("  命中:", json.dumps(lg, ensure_ascii=False)[:400])
except Exception as exc:
    print("  get_leagues 失败:", str(exc)[:200])

# 2. 直接按日期查德甲候选 league_id
print("\n=== get_events 2026-01-14 ===")
for lid in (152, 175, 78, 79, 307):
    try:
        events = ad.request("get_events", {"league_id": lid, "from": "2026-01-14", "to": "2026-01-14"})
        rows = events if isinstance(events, list) else events.get("result", [])
        if not rows:
            continue
        print(f"  league_id={lid}: {len(rows)} 场")
        for e in rows[:6]:
            home = str(e.get("match_hometeam_name") or "")
            away = str(e.get("match_awayteam_name") or "")
            hs = e.get("match_hometeam_score")
            as_ = e.get("match_awayteam_score")
            st = e.get("match_status")
            print(f"    {e.get('match_id')} | {home} vs {away} | {hs}-{as_} | {st}")
            if any(k in home + away for k in ("汉堡", "勒沃库森", "Hamburg", "Leverkusen")):
                print("    ★★ 命中汉堡场:", json.dumps(e, ensure_ascii=False)[:700])
    except Exception as exc:
        print(f"  league_id={lid} 失败: {str(exc)[:100]}")
