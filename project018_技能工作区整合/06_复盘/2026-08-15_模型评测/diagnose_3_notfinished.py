#!/usr/bin/env python3
"""诊断 3 场 not_finished 的 matchId：直查体彩 getFixedBonusV1 原始返回。"""
import json
import urllib.parse
import urllib.request

FIXED_API = "https://webapi.sporttery.cn/gateway/uniform/football/getFixedBonusV1.qry"
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/134 Mobile Safari/537.36",
      "Referer": "https://m.sporttery.cn/mjc/zqsj/?tab=result", "Accept": "application/json,text/plain,*/*"}

for mid in ("2036932", "2040832", "2040828"):
    url = FIXED_API + "?" + urllib.parse.urlencode({"clientCode": 3001, "matchId": mid})
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        v = d.get("value") or {}
        print(f"=== matchId {mid} ===")
        print("value keys:", sorted(v.keys()))
        for k in ("matchStatusName", "matchDate", "homeTeamAllName", "awayTeamAllName",
                  "sectionsNo999", "sectionsNo1", "businessDate", "leagueAllName", "matchNumStr"):
            print(f"  {k} =", v.get(k))
    except Exception as exc:
        print(f"=== matchId {mid} ===  ERROR: {type(exc).__name__} {str(exc)[:120]}")
    print()
