#!/usr/bin/env python3
"""深入诊断 3 场 not_finished：看 2036932 的 matchResultList/isCancel + 3 场登记记录的 sporttery_meta。"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

FIXED_API = "https://webapi.sporttery.cn/gateway/uniform/football/getFixedBonusV1.qry"
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/134 Mobile Safari/537.36",
      "Referer": "https://m.sporttery.cn/mjc/zqsj/?tab=result", "Accept": "application/json,text/plain,*/*"}
STORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")

# 1. 2036932 的 matchResultList / isCancel
url = FIXED_API + "?" + urllib.parse.urlencode({"clientCode": 3001, "matchId": "2036932"})
d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))
v = d.get("value") or {}
print("=== 2036932 isCancel ===", v.get("isCancel"))
print("=== 2036932 matchResultList ===")
print(json.dumps(v.get("matchResultList"), ensure_ascii=False)[:1500])

# 2. 3 场登记记录里的 match 信息
print("\n=== 3 场登记记录的 match / sporttery_meta ===")
for mid in ("sporttery-2036932", "sporttery-2040832", "sporttery-2040828"):
    for line in open(STORE / "registry.jsonl", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        if e["match_id"] != mid:
            continue
        rec = json.loads(Path(e["path"]).read_text(encoding="utf-8"))
        m = rec.get("match") or {}
        sm = m.get("sporttery_meta") or {}
        inp = rec.get("input") or {}
        print(f"--- {mid} ---")
        print("  match.competition:", m.get("competition"), "| stage:", m.get("stage"))
        print("  match.home/away:", m.get("home"), "vs", m.get("away"))
        print("  match.kickoff:", m.get("kickoff"))
        print("  sporttery_meta:", json.dumps(sm, ensure_ascii=False)[:300])
        print("  input keys:", sorted(inp.keys()))
        break
