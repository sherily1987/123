#!/usr/bin/env python3
"""Fetch Sporttery historical results + pre-match odds for ALL listed leagues.

Unlike fetch_sporttery_history.py (big5+cups only), this keeps every league
returned by getConditionsV1/getMatchDataPageListV1, with optional excludes.

Features:
- date-range resume
- matchId-level resume for fixed-bonus enrichment
- conservative concurrency
- atomic save
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone

BASE = "https://webapi.sporttery.cn/gateway"
COND = BASE + "/uniform/fb/getConditionsV1.qry?method=result"
LIST = BASE + "/uniform/fb/getMatchDataPageListV1.qry"
FIXED = BASE + "/uniform/football/getFixedBonusV1.qry"
HEAD = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/134 Mobile Safari/537.36",
    "Referer": "https://m.sporttery.cn/mjc/zqsj/?tab=result",
    "Accept": "application/json,text/plain,*/*",
}
STOP_CODES = {403, 429, 567}
DEFAULT_EXCLUDE = {"友谊", "俱乐部友谊"}


# [中文功能] 原子写JSON（先写临时文件再替换）
def atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# [中文功能] 带重试的HTTP GET请求（体彩官方接口）
def get(url, retries=3):
    for n in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEAD)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in STOP_CODES:
                raise RuntimeError(f"STOP_HTTP_{e.code}")
            if n == retries:
                raise
        except Exception:
            if n == retries:
                raise
        time.sleep((2 ** n) + random.uniform(0.2, 0.9))


# [中文功能] 生成起始到结束的日期序列
def days(a, b):
    while a <= b:
        yield a
        a += timedelta(days=1)


# [中文功能] 展平官方接口按天分组的场次列表
def flatten(j):
    return [m for g in j.get("value", {}).get("matchInfoList", []) for m in g.get("subMatchList", [])]


# [中文功能] 按联赛名与关键词过滤需要保留的场次
def keep_league(name, include, exclude):
    s = name or ""
    if any(x and x in s for x in exclude):
        return False
    if include:
        return any(x and x in s for x in include)
    return True


# [中文功能] 取指定时间点之前最近的一次盘口快照
def latest_before(rows, kickoff):
    good = []
    for r in rows or []:
        try:
            t = datetime.fromisoformat(
                (r.get("updateDate") or "") + "T" + (r.get("updateTime") or "00:00:00") + "+08:00"
            )
        except ValueError:
            continue
        if not kickoff or t < kickoff:
            good.append((t, r))
    return max(good, key=lambda x: x[0])[1] if good else None


# [中文功能] 从盘口行提取主/平/客三项赔率
def odds3(r, keys=("h", "d", "a")):
    if not r:
        return None
    try:
        return [float(r[k]) for k in keys]
    except (KeyError, TypeError, ValueError):
        return None


# [中文功能] 抓取单场固定奖金与赔率历史
def fixed(m):
    time.sleep(random.uniform(0.2, 0.55))
    mid = m["matchId"]
    u = FIXED + "?" + urllib.parse.urlencode({"clientCode": 3001, "matchId": mid})
    v = get(u)["value"]
    oh = v.get("oddsHistory") or {}
    try:
        k = datetime.fromisoformat(
            m["matchDate"] + "T" + (m.get("matchTime") or "00:00")[:5] + ":00+08:00"
        )
    except Exception:
        k = None
    names = {"had": "hadList", "hhad": "hhadList", "crs": "crsList", "ttg": "ttgList", "hafu": "hafuList"}
    snap = {x: latest_before(oh.get(y, []), k) for x, y in names.items()}
    return {
        **m,
        "kickoff_iso": k.isoformat() if k else None,
        "closing_pre_match": snap,
        "closing_had": odds3(snap["had"]),
        "hhad_line": (snap["hhad"] or {}).get("goalLine") if snap["hhad"] else None,
        "closing_hhad": odds3(snap["hhad"]),
        "odds_history": oh,
        "fixed_bonus_url": u,
        "match_result_list": v.get("matchResultList"),
        "sections_no999": v.get("sectionsNo999") or m.get("sectionsNo999"),
        "sectionsNo999": v.get("sectionsNo999") or m.get("sectionsNo999"),
    }


# [中文功能] 批量下载指定日期区间的历史数据
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--list-delay", type=float, default=0.25)
    ap.add_argument("--include-league", action="append", default=[], help="substring filter; repeatable")
    ap.add_argument("--exclude-league", action="append", default=[], help="substring filter; repeatable")
    ap.add_argument("--list-only", action="store_true", help="only list matches, no fixed-bonus fetch")
    ap.add_argument("--max-matches", type=int, default=0, help="optional cap for smoke tests")
    args = ap.parse_args()

    cond = get(COND)["value"]
    lo = date.fromisoformat(cond["startDate"])
    hi = date.fromisoformat(cond["endDate"])
    start = max(lo, date.fromisoformat(args.start)) if args.start else lo
    end = min(hi, date.fromisoformat(args.end)) if args.end else hi
    include = args.include_league
    exclude = set(DEFAULT_EXCLUDE) | set(args.exclude_league)

    old = {}
    meta = {}
    if os.path.exists(args.output):
        try:
            prev = json.load(open(args.output, encoding="utf-8"))
            for x in prev.get("matches", []):
                if "fixed_error" in x:
                    continue
                # list-only rows may lack odds_history; keep enriched ones
                if x.get("odds_history") or x.get("closing_had") or args.list_only:
                    old[str(x.get("matchId") or x.get("match_id"))] = x
            meta = prev
        except Exception:
            pass

    found = {}
    for i, d in enumerate(days(start, end)):
        if i:
            time.sleep(max(0.0, args.list_delay))
        u = LIST + "?" + urllib.parse.urlencode({"method": "result", "matchDate": d.isoformat()})
        j = get(u)
        for m in flatten(j):
            lg = m.get("leagueAbbName") or m.get("leagueAllName") or ""
            if not keep_league(lg, include, exclude):
                continue
            found[str(m["matchId"])] = m

    if args.max_matches and len(found) > args.max_matches:
        # stable subset by matchId
        keep_ids = sorted(found.keys(), key=lambda x: int(x))[: args.max_matches]
        found = {k: found[k] for k in keep_ids}

    print(
        json.dumps(
            {
                "phase": "list_done",
                "available_range": [str(lo), str(hi)],
                "requested_range": [str(start), str(end)],
                "selected": len(found),
                "cached_enriched": sum(1 for x in old.values() if x.get("odds_history")),
                "league_counts": dict(Counter((m.get("leagueAbbName") or m.get("leagueAllName") or "?") for m in found.values())),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    if args.list_only:
        rows = list(found.values())
        out = {
            "schema_version": "sporttery-history-all-list-1.0",
            "source": "中国体彩网移动端官方赛果列表",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "available_range": {"start": str(lo), "end": str(hi)},
            "requested_range": {"start": str(start), "end": str(end)},
            "filter": {"include": include, "exclude": sorted(exclude)},
            "count": len(rows),
            "league_counts": dict(Counter((m.get("leagueAbbName") or m.get("leagueAllName") or "?") for m in rows)),
            "matches": rows,
        }
        atomic(args.output, out)
        print(json.dumps({"status": "ok", "mode": "list_only", "count": len(rows), "output": args.output}, ensure_ascii=False))
        return

    pending = [m for k, m in found.items() if k not in old or not old[k].get("odds_history")]
    # preserve already enriched
    for k, m in found.items():
        if k in old and old[k].get("odds_history"):
            continue
        if k not in old:
            old[k] = m

    print(json.dumps({"phase": "enrich_start", "pending": len(pending)}, ensure_ascii=False), flush=True)
    errors = []

    # [中文功能] 并发任务包装，单场异常不回传崩溃
    def task(m):
        try:
            return fixed(m)
        except Exception as e:
            return {**m, "fixed_error": str(e)}

    workers = max(1, min(args.workers, 8))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for n, row in enumerate(ex.map(task, pending), 1):
            mid = str(row.get("matchId"))
            if "fixed_error" in row:
                errors.append(row)
            else:
                old[mid] = row
            if n % 25 == 0 or n == len(pending):
                payload = {
                    "schema_version": "sporttery-history-all-1.0",
                    "source": "中国体彩网移动端官方赛果与固定奖金接口",
                    "source_page": "https://m.sporttery.cn/mjc/zqsj/?tab=result",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "available_range": {"start": str(lo), "end": str(hi)},
                    "requested_range": {"start": str(start), "end": str(end)},
                    "filter": {"include": include, "exclude": sorted(exclude), "mode": "all_leagues"},
                    "count": sum(1 for x in old.values() if x.get("odds_history")),
                    "listed": len(found),
                    "matches": [x for x in old.values() if x.get("odds_history")],
                    "errors": errors[-50:],
                    "error_count": len(errors),
                    "league_counts": dict(
                        Counter((x.get("leagueAbbName") or x.get("leagueAllName") or "?") for x in old.values() if x.get("odds_history"))
                    ),
                    "notes": [
                        "all leagues from official conditions list",
                        "closing_* uses last pre-kickoff snapshot",
                        "resume-safe by matchId",
                    ],
                }
                atomic(args.output, payload)
                print(
                    json.dumps(
                        {
                            "saved_enriched": payload["count"],
                            "progress": n,
                            "pending_total": len(pending),
                            "errors": len(errors),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            if any(str(x.get("fixed_error", "")).startswith("STOP_HTTP_") for x in errors[-5:]):
                break

    enriched = [x for x in old.values() if x.get("odds_history")]
    final = {
        "schema_version": "sporttery-history-all-1.0",
        "source": "中国体彩网移动端官方赛果与固定奖金接口",
        "source_page": "https://m.sporttery.cn/mjc/zqsj/?tab=result",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "available_range": {"start": str(lo), "end": str(hi)},
        "requested_range": {"start": str(start), "end": str(end)},
        "filter": {"include": include, "exclude": sorted(exclude), "mode": "all_leagues"},
        "count": len(enriched),
        "listed": len(found),
        "matches": enriched,
        "errors": errors,
        "error_count": len(errors),
        "league_counts": dict(Counter((x.get("leagueAbbName") or x.get("leagueAllName") or "?") for x in enriched)),
        "notes": [
            "all leagues from official conditions list",
            "closing_* uses last pre-kickoff snapshot",
            "resume-safe by matchId",
        ],
    }
    atomic(args.output, final)
    print(
        json.dumps(
            {
                "status": "ok" if not errors else "partial",
                "count": len(enriched),
                "listed": len(found),
                "errors": len(errors),
                "output": args.output,
                "league_counts": final["league_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
