#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""understat xG 采集（五大联赛）。

来路：understat 页面自身发出的公开请求 `GET /getLeagueData/<league>/<season>`，
返回全联赛球队的逐场 xG/npxG/xGA/xPTS/ppda。2026-08-16 实测无鉴权、无验证码；
必须带 `X-Requested-With: XMLHttpRequest`，否则返回的不是 JSON。

定位：只补 xG 这一项数据，**不预测、不写主证据**。产出快照仍须走
`crawl_evidence.py` 的来源清单门禁才能进 evidence_NNN_*.md。

⚠️ 时间口径（本模块最容易出错的地方）
    understat 的 `date` 是**无时区裸时间**（"2025-08-16 11:30:00"）。本仓库数据契约
    规定「带时区 offset，无 offset 不猜测」，所以本模块**不把它当成任何时区**，而是
    按最坏情况过滤：一场比赛只有在「任何时区解释下都早于 cutoff」时才计入赛前统计。
    代价是 cutoff 前 ±14h 内的比赛会被保守丢弃；换来的是绝不会把赛后数据混进赛前证据。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

BASE = "https://understat.com"

# understat 的联赛代号；键为本仓库常用写法。
LEAGUES = {
    "EPL": "EPL", "英超": "EPL",
    "La_liga": "La_liga", "西甲": "La_liga",
    "Bundesliga": "Bundesliga", "德甲": "Bundesliga",
    "Serie_A": "Serie_A", "意甲": "Serie_A",
    "Ligue_1": "Ligue_1", "法甲": "Ligue_1",
    "RFPL": "RFPL",
}

# 地球上 UTC 偏移的极值约 -12h~+14h。裸时间最坏情况按 ±14h 处理。
TZ_UNCERTAINTY = timedelta(hours=14)


def resolve_league(name: str) -> str:
    """把中英文联赛名归一到 understat 代号。"""
    key = str(name or "").strip()
    if key in LEAGUES:
        return LEAGUES[key]
    raise ValueError(f"未知联赛 {name!r}；支持：{sorted(set(LEAGUES.values()))}")


def _parse_naive(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except (TypeError, ValueError):
            continue
    return None


def is_definitely_before(match_date: str, cutoff_iso: str) -> bool:
    """裸时间的比赛是否在**任何时区解释下**都早于 cutoff。

    cutoff 必须带时区 offset；不带则拒绝（不猜测本机时区）。
    """
    naive = _parse_naive(match_date)
    if naive is None:
        return False
    try:
        cutoff = datetime.fromisoformat(str(cutoff_iso).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError(f"cutoff 必须是带时区的 ISO 时间，收到 {cutoff_iso!r}")
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError(f"cutoff 缺时区 offset，不猜测：{cutoff_iso!r}")
    # 最晚可能的真实时刻 = 裸时间 + 最大西向偏移
    latest_possible = (naive + TZ_UNCERTAINTY).replace(tzinfo=cutoff.tzinfo)
    return latest_possible < cutoff.replace(tzinfo=cutoff.tzinfo)


def team_xg_summary(
    history: list[dict[str, Any]],
    *,
    cutoff_iso: str | None = None,
    last_n: int | None = None,
) -> dict[str, Any]:
    """按场次聚合 xG 指标。

    cutoff_iso 给定时只统计「确定早于 cutoff」的场次（见模块 docstring 的时间口径）。
    last_n 只取最近 N 场（在 cutoff 过滤之后按日期排序取尾）。
    """
    rows = list(history or [])
    excluded = 0
    if cutoff_iso:
        kept = [r for r in rows if is_definitely_before(r.get("date", ""), cutoff_iso)]
        excluded = len(rows) - len(kept)
        rows = kept
    rows.sort(key=lambda r: str(r.get("date", "")))
    if last_n:
        rows = rows[-last_n:]

    def total(key):
        return sum(float(r.get(key) or 0) for r in rows)

    played = len(rows)
    return {
        "matches": played,
        "excluded_by_cutoff": excluded,
        "xG": round(total("xG"), 3),
        "xGA": round(total("xGA"), 3),
        "npxG": round(total("npxG"), 3),
        "npxGA": round(total("npxGA"), 3),
        "xPTS": round(total("xpts"), 3),
        "scored": int(total("scored")),
        "missed": int(total("missed")),
        "xG_per_match": round(total("xG") / played, 3) if played else None,
        "xGA_per_match": round(total("xGA") / played, 3) if played else None,
        # 进球减去 xG：正=超期望完成，负=欠收。用于「运气/效率」类证据，不作预测。
        "finishing_delta": round(total("scored") - total("xG"), 3) if played else None,
    }


def summarise_league(
    payload: dict[str, Any],
    *,
    cutoff_iso: str | None = None,
    last_n: int | None = None,
    teams_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    """把 getLeagueData 原始响应聚合成每队一行。"""
    wanted = {t.casefold() for t in (teams_filter or [])}
    out = []
    for team in (payload.get("teams") or {}).values():
        title = str(team.get("title", ""))
        if wanted and title.casefold() not in wanted:
            continue
        row = {"team": title, "understat_team_id": team.get("id")}
        row.update(team_xg_summary(team.get("history") or [],
                                   cutoff_iso=cutoff_iso, last_n=last_n))
        out.append(row)
    out.sort(key=lambda r: (-(r["xG"] or 0), r["team"]))
    return out


def fetch_league_data(league: str, season: int | str, *, timeout_s: int = 30) -> dict[str, Any]:
    """取 understat 公开联赛数据。X-Requested-With 缺了会拿到非 JSON。"""
    import httpx

    code = resolve_league(league)
    url = f"{BASE}/getLeagueData/{code}/{season}"
    response = httpx.get(url, timeout=timeout_s, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"),
        "Referer": f"{BASE}/league/{code}",
        "X-Requested-With": "XMLHttpRequest",
    })
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"understat 未返回 JSON（{len(response.text)} 字符）——"
            f"多半是缺 X-Requested-With 头或接口已改：{url}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="采集 understat 五大联赛 xG")
    parser.add_argument("--league", required=True, help="EPL/西甲/La_liga/德甲/意甲/法甲 …")
    parser.add_argument("--season", required=True, help="赛季起始年，如 2025")
    parser.add_argument("--cutoff", help="赛前截止时刻（必须带时区 offset），只统计确定早于它的场次")
    parser.add_argument("--last-n", type=int, help="只看最近 N 场")
    parser.add_argument("--team", action="append", default=[], help="只输出指定球队，可重复")
    parser.add_argument("--out-dir", help="写入快照目录；不给则只打印")
    args = parser.parse_args(argv)

    payload = fetch_league_data(args.league, args.season)
    rows = summarise_league(payload, cutoff_iso=args.cutoff,
                            last_n=args.last_n, teams_filter=args.team)

    header = f"{'team':<26} {'M':>3} {'xG':>7} {'xGA':>7} {'xPTS':>7} {'GF-xG':>7}"
    print(header)
    for row in rows:
        print(f"{row['team']:<26} {row['matches']:>3} {row['xG']:>7} "
              f"{row['xGA']:>7} {row['xPTS']:>7} {str(row['finishing_delta']):>7}")
    if args.cutoff and rows:
        print(f"\ncutoff={args.cutoff}；按最坏时区（±14h）保守剔除 "
              f"{rows[0]['excluded_by_cutoff']} 场，无 offset 的裸时间不猜测。")

    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        code = resolve_league(args.league)
        path = out_dir / f"understat_{code}_{args.season}.json"
        path.write_text(json.dumps({
            "source": f"{BASE}/league/{code}",
            "endpoint": f"{BASE}/getLeagueData/{code}/{args.season}",
            "cutoff": args.cutoff,
            "cutoff_policy": "naive_dates_excluded_within_14h_of_cutoff",
            "last_n": args.last_n,
            "teams": rows,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
