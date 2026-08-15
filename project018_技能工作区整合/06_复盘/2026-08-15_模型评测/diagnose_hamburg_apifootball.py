#!/usr/bin/env python3
"""用 apifootball.com apiv3 查汉堡 vs 勒沃库森（2026-01-14 德甲）赛果。

1. get_leagues 找德甲 league_id
2. get_events 查 2026-01-14 德甲赛果
"""
import json
import os
import sys

sys.path.insert(0, r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\skill\football-quant-fusion\scripts")
os.environ.setdefault("API_FOOTBALL_KEY", "c6a716469c9da4b82552c4efa8043629")

import apifootball_adapter as ad

# 1. 找德甲 league_id
print("=== get_leagues 找德甲 ===")
try:
    leagues = ad.fetch("get_leagues", {})
    for lg in leagues:
        name = str(lg.get("league_name") or lg.get("country_name") or "")
        if any(k in name.lower() for k in ("germany", "bundesliga", "德国", "德甲")):
            print("  命中:", json.dumps(lg, ensure_ascii=False)[:300])
except Exception as exc:
    print("  get_leagues 失败:", exc)

# 2. 先试德甲常见 league_id（apifootball.com 的 id 未知，需从 leagues 结果确认）
# 直接按日期查所有 events，用队名匹配汉堡/勒沃库森
print("\n=== get_events 2026-01-14（德甲候选 league_id）===")
# 常见候选：德甲在 apifootball.com 的 id 需要从 leagues 结果推断
# 先尝试几个可能的 id（307 是示例里的，德甲可能是别的）
for lid in (152, 175, 78, 307):
    try:
        events = ad.fetch("get_events", {"league_id": lid, "from": "2026-01-14", "to": "2026-01-14"})
        if not events:
            continue
        print(f"  league_id={lid}: {len(events)} 场")
        for e in events[:5]:
            home = str(e.get("match_hometeam_name") or "")
            away = str(e.get("match_awayteam_name") or "")
            print(f"    {e.get('match_id')} | {home} vs {away} | {e.get('match_hometeam_score')}-{e.get('match_awayteam_score')} | {e.get('match_status')}")
            if "汉堡" in home + away or "勒沃库森" in home + away or "hamburg" in (home+away).lower() or "leverkusen" in (home+away).lower():
                print("    ★★ 命中汉堡场:", json.dumps(e, ensure_ascii=False)[:600])
    except Exception as exc:
        print(f"  league_id={lid} 失败: {str(exc)[:80]}")
