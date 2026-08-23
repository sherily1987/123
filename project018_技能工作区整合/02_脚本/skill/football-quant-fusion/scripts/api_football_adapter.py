#!/usr/bin/env python3
"""api_football_adapter — API-Football (api-sports.io v3) enrichment adapter.

数据源: https://v3.football.api-sports.io
认证: 环境变量 API_FOOTBALL_KEY（经 x-apisports-key 请求头发送），
      key 不写入任何文件、不出现在输出中。
响应信封: {get, parameters, errors, results, paging, response}

已知限制（2026-08-03 实测，Free 套餐）:
- 仅开放 2022–2024 赛季；2025/2026 当前赛季返回 "Free plans do not have access to this season"。
- 每日额度 100 次（报错请求同样计入额度）。
- /odds 赔率接口未适配；免费套餐赔率覆盖不稳，市场基线仍以体彩官方采集为准。
- --search 与 --current 不能同传（API 报错）；本适配器已处理为有 search 时自动忽略 current。

子命令:
  status                       账号与当日额度
  leagues --season / --search / --country / --current   联赛覆盖与赛季
  teams  --search / --id       球队查询（用于拿 team id）
  fixtures --date / --team / --league+--season / --live / --id   赛程与比分
  standings --league --season  积分榜
  injuries --league --season / --fixture / --team  伤停
  h2h --home <id> --away <id>  两队历史交锋

用法示例:
  python api_football_adapter.py status
  python api_football_adapter.py leagues --season 2024 --output leagues.json
  python api_football_adapter.py teams --search "Manchester United"
  python api_football_adapter.py fixtures --date 2026-08-02 --output fixtures.json
  python api_football_adapter.py standings --league 39 --season 2025 --output standings.json
  python api_football_adapter.py injuries --league 39 --season 2025 --output injuries.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://v3.football.api-sports.io"
HEAD = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def api_key():
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        sys.exit("缺少环境变量 API_FOOTBALL_KEY（在 https://dashboard.api-football.com 获取）")
    return key


def get(path, params):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={**HEAD, "x-apisports-key": api_key()})
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
            if attempt == 2:
                raise
            time.sleep(0.5 * (2 ** attempt))
    raise last_error  # pragma: no cover - loop either returns or raises


def fetch(path, params):
    data = get(path, params)
    if data.get("errors"):
        raise RuntimeError(json.dumps(data["errors"], ensure_ascii=False))
    return data


def save(output, data, summary, items=None):
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if items is not None:
        summary = {**summary, "preview": items[:10], "total": len(items)}
        if len(items) > 10:
            summary["note"] = "完整数据已写入 --output 文件，预览仅前 10 条"
    print(json.dumps({"status": "ok", **summary}, ensure_ascii=False, indent=2))


def cmd_status(a):
    data = fetch("/status", {})
    sub = data["response"]["subscription"]
    req = data["response"]["requests"]
    save(a.output, data, {
        "plan": sub["plan"], "active": sub["active"],
        "requests_used": req["current"], "requests_limit_day": req["limit_day"],
    })


def cmd_leagues(a):
    params = {}
    if a.season:
        params["season"] = a.season
    if a.search:
        params["search"] = a.search
    if a.country:
        params["country"] = a.country
    if a.current and not a.search:
        params["current"] = "true"
    data = fetch("/leagues", params)
    rows = [{"id": x["league"]["id"], "name": x["league"]["name"],
             "type": x["league"].get("type"),
             "country": (x.get("country") or {}).get("name"),
             "seasons": [s.get("year") for s in x.get("seasons", []) if s.get("year")]}
            for x in data.get("response", [])]
    save(a.output, data, {"count": len(rows)}, rows)


def cmd_teams(a):
    params = {"id": a.id} if a.id else {"search": a.search}
    data = fetch("/teams", params)
    teams = [{"id": t["team"]["id"], "name": t["team"]["name"],
              "country": t["team"].get("country"), "code": t["team"].get("code")}
             for t in data.get("response", [])]
    save(a.output, data, {"count": len(teams)}, teams)


def cmd_fixtures(a):
    params = {"timezone": "Asia/Shanghai"}
    for k in ("id", "date", "team", "league", "season", "live", "from", "to"):
        v = getattr(a, k, None)
        if v:
            params[k] = v
    data = fetch("/fixtures", params)
    rows = [{"fixture_id": f["fixture"]["id"], "date": f["fixture"]["date"],
             "status": f["fixture"]["status"].get("short"),
             "league": f["league"].get("name"), "round": f["league"].get("round"),
             "home": f["teams"]["home"].get("name"), "home_id": f["teams"]["home"].get("id"),
             "away": f["teams"]["away"].get("name"), "away_id": f["teams"]["away"].get("id"),
             "goals": f.get("goals")}
            for f in data.get("response", [])]
    save(a.output, data, {"count": len(rows)}, rows)


def cmd_standings(a):
    data = fetch("/standings", {"league": a.league, "season": a.season})
    rows = []
    for grp in data.get("response", []):
        for table in grp.get("league", {}).get("standings", []):
            for row in table:
                rows.append({"rank": row.get("rank"), "team": row["team"]["name"],
                             "team_id": row["team"]["id"], "points": row.get("points"),
                             "played": (row.get("all") or {}).get("played"),
                             "goals_diff": row.get("goalsDiff"), "form": row.get("form"),
                             "description": row.get("description")})
    league = ((data.get("response") or [{}])[0].get("league") or {}).get("name")
    save(a.output, data, {"league": league, "count": len(rows)}, rows)


def cmd_injuries(a):
    params = {k: getattr(a, k) for k in ("league", "season", "fixture", "team") if getattr(a, k)}
    data = fetch("/injuries", params)
    rows = [{"fixture_id": x.get("fixture", {}).get("id"),
             "team": x.get("team", {}).get("name"),
             "player": x.get("player", {}).get("name"),
             "type": x.get("player", {}).get("type"),
             "reason": x.get("player", {}).get("reason")}
            for x in data.get("response", [])]
    save(a.output, data, {"count": len(rows)}, rows)


def cmd_h2h(a):
    data = fetch("/fixtures/headtohead", {"h2h": f"{a.home}-{a.away}", "timezone": "Asia/Shanghai"})
    rows = [{"fixture_id": f["fixture"]["id"], "date": f["fixture"]["date"],
             "league": f["league"].get("name"),
             "home": f["teams"]["home"].get("name"), "away": f["teams"]["away"].get("name"),
             "goals": f.get("goals")}
            for f in data.get("response", [])]
    save(a.output, data, {"count": len(rows)}, rows)


def main():
    ap = argparse.ArgumentParser(description="API-Football v3 adapter (key: API_FOOTBALL_KEY env)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_output(p):
        p.add_argument("--output", help="写入的 JSON 文件路径")

    p = sub.add_parser("status")
    add_output(p)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("leagues")
    p.add_argument("--season", type=int)
    p.add_argument("--search")
    p.add_argument("--country")
    p.add_argument("--current", action="store_true")
    add_output(p)
    p.set_defaults(fn=cmd_leagues)

    p = sub.add_parser("teams")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--search")
    g.add_argument("--id", type=int)
    add_output(p)
    p.set_defaults(fn=cmd_teams)

    p = sub.add_parser("fixtures")
    p.add_argument("--id", type=int)
    p.add_argument("--date")
    p.add_argument("--team", type=int)
    p.add_argument("--league", type=int)
    p.add_argument("--season", type=int)
    p.add_argument("--live")
    p.add_argument("--from")
    p.add_argument("--to")
    add_output(p)
    p.set_defaults(fn=cmd_fixtures)

    p = sub.add_parser("standings")
    p.add_argument("--league", type=int, required=True)
    p.add_argument("--season", type=int, required=True)
    add_output(p)
    p.set_defaults(fn=cmd_standings)

    p = sub.add_parser("injuries")
    p.add_argument("--league", type=int)
    p.add_argument("--season", type=int)
    p.add_argument("--fixture", type=int)
    p.add_argument("--team", type=int)
    add_output(p)
    p.set_defaults(fn=cmd_injuries)

    p = sub.add_parser("h2h")
    p.add_argument("--home", type=int, required=True)
    p.add_argument("--away", type=int, required=True)
    add_output(p)
    p.set_defaults(fn=cmd_h2h)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
