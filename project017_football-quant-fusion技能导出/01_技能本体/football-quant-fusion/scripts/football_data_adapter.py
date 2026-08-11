#!/usr/bin/env python3
"""football_data_adapter — football-data.org v4 适配器。

API Key 只从环境变量 FOOTBALL_DATA_API_KEY 读取（SKILL 硬规则：不写入输出）。
用途：赛程/积分/近期结果/交锋的交叉核验；无 Key 或该源无赛事覆盖时标 UNAVAILABLE。
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


API = "https://api.football-data.org/v4"


# [中文功能] 读取 API Key（仅环境变量）
def api_key():
    k = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
    if not k:
        raise SystemExit("FOOTBALL_DATA_API_KEY 未设置；Key 只从环境变量读取，不写入输出。")
    return k


# [中文功能] 带重试的 GET 请求
def get(path, params=None, retries=3):
    qs = "?" + urllib.parse.urlencode(params) if params else ""
    req = urllib.request.Request(API + path + qs, headers={"X-Auth-Token": api_key()})
    for n in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (403, 404) and n == 0:
                # 403 可能是套餐权限不足；404 为无覆盖。两者都返回结构化错误而非裸异常。
                return {"error": {"code": e.code, "reason": "no_coverage_or_permission"}}
            if e.code in (429, 500, 503) and n < retries:
                time.sleep(2 ** n)
                continue
            raise
    raise RuntimeError("football-data.org request failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--competition", help="赛事代码，如 PL/SA/BL/PD/FL1")
    ap.add_argument("--team", help="球队名查询")
    ap.add_argument("--output", required=True)
    ap.add_argument("--status", default="FINISHED", help="FILTER: FINISHED/SCHEDULED/TIMED")
    ap.add_argument("--limit", type=int, default=50)
    a = ap.parse_args()
    if not a.competition and not a.team:
        raise SystemExit("需要 --competition 或 --team 之一")
    fetched = datetime.now(timezone.utc).isoformat()
    data = None
    query = {}
    if a.team:
        data = get("/teams", {"search": a.team})
        query = {"team": a.team}
    elif a.competition:
        data = get("/competitions/" + a.competition.upper() + "/matches", {"status": a.status, "limit": a.limit})
        query = {"competition": a.competition.upper(), "status": a.status, "limit": a.limit}
    out = {
        "schema_version": "football-data-adapter-1.0",
        "source": "football-data.org",
        "provider_model": "football-data.org v4",
        "fetched_at": fetched,
        "query": query,
        "status": "UNAVAILABLE" if (data or {}).get("error") else "VALID",
        "note": "该源无赛事覆盖或套餐无权限时必须标 UNAVAILABLE，不得用其他联赛数据替代。",
        "data": data,
    }
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({"status": out["status"], "query": query, "output": a.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
