#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FotMob 公开联赛接口（第 4 级：页面自己发出的 /api/data/leagues）。

2026-08-16 Playwright 抓包，再纯 HTTP 复验：
    GET /api/data/allLeagues                 联赛 id 目录（不要猜数字）
    GET /api/data/leagues?id=<联赛ID>        积分榜 + 赛程
    GET /api/data/matchDetails?matchId=      单场球队 xG，打完才有数

定位：只取结构化快照，不写主证据、不改生产 1X2。
赛程 status.utcTime 带 Z，按 collected_at < kickoff 过滤即可，不必 ±14h。
球队 xG 榜是「截至抓取时刻的赛季累计」：快照必须开球前取，否则对当场是 POST_MATCH。
不是每个联赛都有 table.xg：韩职/韩K2/日乙/芬超/MLS 已复验确认没有。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

BASE = "https://www.fotmob.com"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")

# 2026-08-16 HTTP 实测。id 来自 GET /api/data/allLeagues，再经 leagues?id= 复验。
# 未列入的联赛不要猜数字，先查 allLeagues。
LEAGUES = {
    "荷甲": 57, "Eredivisie": 57,
    "葡超": 61, "Liga Portugal": 61,
    "日职": 223, "J1": 223, "J. League": 223,
    "日乙": 8974, "J2": 8974, "J. League 2": 8974,
    "美职": 130, "MLS": 130,
    "瑞超": 67, "Allsvenskan": 67,
    "挪超": 59, "Eliteserien": 59,
    "英冠": 48, "Championship": 48,
    "巴甲": 268, "Serie A BRA": 268,
    "芬超": 51, "Veikkausliiga": 51,
    "沙职": 536, "Saudi Pro League": 536,
    "韩职": 9080, "K League 1": 9080,
    "韩K2": 9116, "K League 2": 9116,
}

# 积分榜带 table.xg 的联赛（赛季累计，抓取时刻快照）。没有的不要把空榜当缺源失败。
TABLE_XG_IDS = frozenset({57, 61, 223, 67, 59, 48, 268, 536})
# 已复验确认积分榜没有 xG 列。
NO_TABLE_XG_IDS = frozenset({130, 51, 9080, 9116, 8974})


def resolve_league(name: str) -> int:
    key = str(name or "").strip()
    if key in LEAGUES:
        return LEAGUES[key]
    if key.isdigit():
        return int(key)
    raise ValueError(f"未知联赛 {name!r}；已确认：{sorted(set(LEAGUES))}")


def parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(timezone.utc)


def require_cutoff(cutoff_iso: str) -> datetime:
    try:
        cutoff = datetime.fromisoformat(str(cutoff_iso).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"cutoff 必须是带时区的 ISO 时间，收到 {cutoff_iso!r}") from exc
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError(f"cutoff 缺时区 offset，不猜测：{cutoff_iso!r}")
    return cutoff.astimezone(timezone.utc)


def table_xg(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tables = payload.get("table") or []
    if not tables:
        return []
    block = ((tables[0] or {}).get("data") or {}).get("table") or {}
    rows = block.get("xg") or []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append({
            "team": row.get("name") or row.get("teamName"),
            "fotmob_team_id": row.get("id") or row.get("teamId"),
            "played": row.get("played"),
            "xg": row.get("xg"),
            "xg_conceded": row.get("xgConceded"),
            "xpts": row.get("xPoints"),
            "gf_xg_diff": row.get("xgDiff"),
            "position": row.get("position"),
        })
    return out


def fixtures(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = ((payload.get("fixtures") or {}).get("allMatches") or [])
    out = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        status = row.get("status") or {}
        utc = parse_utc(status.get("utcTime") or "")
        out.append({
            "match_id": row.get("id"),
            "home": (row.get("home") or {}).get("name"),
            "away": (row.get("away") or {}).get("name"),
            "kickoff_utc": utc.isoformat() if utc else None,
            "finished": bool(status.get("finished")),
            "score": status.get("scoreStr"),
        })
    return out


def extract_match_xg(details: dict[str, Any]) -> dict[str, Any]:
    """从 matchDetails 抽主客 xG。无此块则空。"""
    groups = (((details.get("content") or {}).get("stats") or {}).get("Periods") or {}).get("All") or {}
    found = None
    for group in groups.get("stats") or []:
        for row in group.get("stats") or []:
            title = str(row.get("title") or "")
            vals = row.get("stats")
            if title == "Expected goals (xG)" and isinstance(vals, list) and len(vals) == 2:
                if vals[0] is not None and vals[1] is not None:
                    found = vals
    general = details.get("general") or {}
    utc = parse_utc(str(general.get("matchTimeUTCDate") or ""))
    if utc is None:
        # "Fri, Aug 7, 2026, 10:25 UTC" 不解析，避免猜格式
        utc = None
    return {
        "match_id": general.get("matchId"),
        "home": (general.get("homeTeam") or {}).get("name"),
        "away": (general.get("awayTeam") or {}).get("name"),
        "kickoff_utc": utc.isoformat() if utc else None,
        "finished": bool(general.get("finished")),
        "xg_home": None if not found else float(found[0]),
        "xg_away": None if not found else float(found[1]),
        "looks_post_match": bool(found) or bool(general.get("finished")),
    }


def snapshot_status(*, collected_at: str, kickoff_utc: str | None) -> str:
    if not kickoff_utc:
        return "UNAVAILABLE"
    cutoff = require_cutoff(collected_at)
    kick = parse_utc(kickoff_utc)
    if kick is None:
        return "UNAVAILABLE"
    if cutoff < kick:
        return "VALID"
    return "POST_MATCH_NOT_USABLE"


def fetch_all_leagues(*, timeout_s: int = 40) -> dict[str, Any]:
    """联赛 id 目录。未知联赛先查这里，不要猜 id。"""
    import httpx
    url = f"{BASE}/api/data/allLeagues"
    r = httpx.get(url, timeout=timeout_s, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or "countries" not in data:
        raise ValueError("fotmob allLeagues 不是目录 JSON")
    return data


def fetch_league(league: str | int, *, timeout_s: int = 40) -> dict[str, Any]:
    import httpx
    lid = resolve_league(str(league))
    url = f"{BASE}/api/data/leagues?id={lid}"
    r = httpx.get(url, timeout=timeout_s, headers={
        "User-Agent": USER_AGENT,
        "Referer": f"{BASE}/leagues/{lid}",
    })
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or not data.get("details"):
        raise ValueError(f"fotmob leagues?id={lid} 不是联赛 JSON")
    return data


def fetch_match_details(match_id: str | int, *, timeout_s: int = 40) -> dict[str, Any]:
    import httpx
    url = f"{BASE}/api/data/matchDetails?matchId={match_id}"
    r = httpx.get(url, timeout=timeout_s, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.json()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", help="中文名、英文名或数字 id")
    ap.add_argument("--cutoff", help="带时区的 ISO，过滤赛程")
    ap.add_argument("--match-id", help="可选：再拉一场 matchDetails（赛后才有球队 xG）")
    ap.add_argument("--list", action="store_true", help="打印已确认联赛与是否有 table.xg")
    args = ap.parse_args()
    if args.list:
        seen = {}
        for name, lid in LEAGUES.items():
            seen.setdefault(lid, []).append(name)
        rows = []
        for lid, names in sorted(seen.items()):
            if lid in TABLE_XG_IDS:
                xg = "table.xg"
            elif lid in NO_TABLE_XG_IDS:
                xg = "no-xg"
            else:
                xg = "unverified-xg"
            rows.append({"fotmob_id": lid, "names": names, "xg": xg})
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not args.league:
        ap.error("需要 --league，或用 --list 查看已确认联赛")
    payload = fetch_league(args.league)
    det = payload.get("details") or {}
    lid = det.get("id")
    xg = table_xg(payload)
    fx = fixtures(payload)
    if args.cutoff:
        cutoff = require_cutoff(args.cutoff)
        fx = [m for m in fx if m["kickoff_utc"] and parse_utc(m["kickoff_utc"]) < cutoff]
    out = {
        "league": det.get("name"),
        "fotmob_id": lid,
        "table_xg": bool(xg),
        "xg_teams": len(xg),
        "fixtures": len(fx),
        "top_xg": xg[:5],
    }
    if args.match_id:
        mx = extract_match_xg(fetch_match_details(args.match_id))
        out["match_xg"] = mx
        if mx.get("looks_post_match"):
            out["match_xg_status"] = "POST_MATCH_NOT_USABLE"
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
