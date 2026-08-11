#!/usr/bin/env python3
"""football_data_enrich — 把 football-data.org 元信息安全合并进模型输入。

不覆盖体彩赔率；只附加 field_meta.football_data 与 source_evidence。
需要 FOOTBALL_DATA_API_KEY；无 Key 时返回原输入并标注 UNAVAILABLE。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--home-query", required=True)
    ap.add_argument("--away-query", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    data = json.loads(Path(a.input).read_text(encoding="utf-8-sig"))
    if not os.environ.get("FOOTBALL_DATA_API_KEY", "").strip():
        if isinstance(data, dict) and "matches" in data:
            for m in data["matches"]:
                m.setdefault("field_meta", {})["football_data"] = {"status": "UNAVAILABLE", "reason": "missing API key"}
        else:
            data.setdefault("field_meta", {})["football_data"] = {"status": "UNAVAILABLE", "reason": "missing API key"}
        Path(a.output).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "ok_noop", "reason": "FOOTBALL_DATA_API_KEY missing; input unchanged", "output": a.output}, ensure_ascii=False))
        return
    # 完整实现依赖 football_data_adapter 的查询能力；Key 存在时逐场附加来源元信息。
    import football_data_adapter as fda

    def resolve_team(q):
        r = fda.get("/teams", {"search": q})
        teams = (r or {}).get("teams") or []
        if not teams:
            return None, None
        t = teams[0]
        return t.get("id"), {"id": t.get("id"), "name": t.get("name"), "shortName": t.get("shortName"), "tla": t.get("tla"), "area": (t.get("area") or {}).get("name")}

    home_id, home_info = resolve_team(a.home_query)
    away_id, away_info = resolve_team(a.away_query)

    def enrich_match(m):
        kick = (m.get("kickoff") or "").replace("Z", "+00:00")[:10]
        head = None
        if home_id and kick:
            d0 = (datetime.fromisoformat(kick) - timedelta(days=7)).date().isoformat()
            d1 = (datetime.fromisoformat(kick) + timedelta(days=7)).date().isoformat()
            r = fda.get("/teams/" + str(home_id) + "/matches", {"dateFrom": d0, "dateTo": d1})
            for mm in (r or {}).get("matches") or []:
                h2 = ((mm.get("homeTeam") or {}).get("id"))
                a2 = ((mm.get("awayTeam") or {}).get("id"))
                if h2 == home_id and a2 == away_id:
                    head = {"date": mm.get("utcDate"), "competition": ((mm.get("competition") or {}).get("name")), "status": mm.get("status"), "score": (mm.get("score") or {}).get("fullTime")}
                    break
        m.setdefault("field_meta", {})["football_data"] = {
            "status": "VALID" if head else "PARTIAL",
            "provider_model": "football-data.org v4",
            "home_team": home_info,
            "away_team": away_info,
            "matched_fixture": head,
            "note": "仅作身份与赛程交叉核验；不覆盖体彩赔率。",
        }
        m.setdefault("source_evidence", []).append("football-data.org")
        return m

    if isinstance(data, dict) and "matches" in data:
        data["matches"] = [enrich_match(m) for m in data["matches"]]
    else:
        data = enrich_match(data)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "home": home_info, "away": away_info, "output": a.output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
