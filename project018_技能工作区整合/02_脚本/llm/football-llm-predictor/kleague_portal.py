#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""K League 官方数据门户客户端（韩职）。

来路：`data.kleague.com` 页面自身发出的公开 POST 请求，2026-08-16 抓包得到：

    POST portal.kleague.com/data/matc/scoreInfoForMain.do
         meetYear=2026&meetSeq=1&gameId=133
    POST portal.kleague.com/data/matc/matchPlayerPosInfo.do
         meetYear=2026&meetSeq=1&gameId=133&homeTeam=K22&awayTeam=K03

无鉴权、无验证码。响应是 HTML 片段，但球员数据以 JSON 数组内嵌在其中。

另有官网 API 层（2026-08-16 抓包），返回规范 JSON：

    POST www.kleague.com/api/recentMatchResult.do   近期赛程/赛果（含 gameId、队代码、endYn）
    POST www.kleague.com/api/clubRank.do            积分榜 + 近6场走势

⚠️ 球员接口是**赛后**数据，赛前拿不到首发（2026-08-16 实测确认）
    `matchPlayerPosInfo.do` 对已完赛场次返回 40 人（含 goalQty/workTime 等赛后字段），
    对未开赛场次（`endYn=N`）**返回 0 人**。所以官方门户没有赛前首发，这条别再找了；
    它只能用于赛果、回测和历史库。按数据契约 `collected_at < kickoff`，赛后数据对
    赛前证据是 POST_MATCH_NOT_USABLE，`looks_post_match()` 用来挡这个误用。

    韩职**赛前可用**的是另外两样：`fetch_fixtures()` 的赛程/开球时刻，
    `fetch_standings()` 的积分榜与近6场走势（对应六类证据的「战意/动机」「近况/状态」）。

⚠️ 时间口径
    `gameDate`/`gameTime` 不带时区 offset。韩职在韩国举办，KST(+09:00) 是显然读法，
    但接口没声明，本模块**不替调用方假设**：`kickoff_naive` 原样给出，要带时区请显式
    传 `assume_offset`。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

BASE = "https://portal.kleague.com/data/matc"
API_BASE = "https://www.kleague.com/api"
REFERER = "https://data.kleague.com/"
API_REFERER = "https://www.kleague.com/"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")

# 只有比赛打完才会有值的字段；用于挡住把赛后数据当赛前证据用。
POST_MATCH_FIELDS = ("goalQty", "assistQty", "workTime", "changeIQty", "changeOQty")

# 响应把球员数组塞在形如 `log([{...}]);` 的调用里。
_EMBEDDED_ARRAY = re.compile(r"\w+\(\s*(\[\{.*?\}\])\s*\)\s*;", re.S)


def extract_players(html: str) -> list[dict[str, Any]]:
    """从响应 HTML 里取出内嵌的球员 JSON 数组。

    优先解析 JSON 而不是抓 `data-` 属性——后者依赖 DOM 写法，改版就碎。
    """
    for match in _EMBEDDED_ARRAY.finditer(str(html or "")):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(data, list) and data and isinstance(data[0], dict) \
                and "playerId" in data[0]:
            return data
    return []


def looks_post_match(players: list[dict[str, Any]]) -> bool:
    """这批球员数据是否已含赛后字段（非零出场/进球等）。"""
    for player in players or []:
        for field in POST_MATCH_FIELDS:
            try:
                if float(player.get(field) or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def split_by_side(players: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按 haGubunCd 分主客（H/A），并整理成精简记录。"""
    sides: dict[str, list[dict[str, Any]]] = {"home": [], "away": []}
    for player in players or []:
        side = "home" if str(player.get("haGubunCd", "")).upper() == "H" else "away"
        sides[side].append({
            "player_id": player.get("playerId"),
            "name": player.get("name"),
            "back_no": player.get("backNo"),
            "position": player.get("positionName"),
            "team_id": player.get("teamId"),
            "captain": str(player.get("captainYn", "")).upper() == "Y",
            "minutes": player.get("workTime"),
            "goals": player.get("goalQty"),
            "assists": player.get("assistQty"),
        })
    for side in sides.values():
        side.sort(key=lambda p: (p["back_no"] is None, p["back_no"]))
    return sides


# 韩文赛果代码 → 本仓库写法
FORM_CODES = {"승": "W", "무": "D", "패": "L"}


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """校验官网 API 信封并取出 data。"""
    code = str((payload or {}).get("resultCode", ""))
    if code != "200":
        raise RuntimeError(f"K League API 返回 resultCode={code!r} "
                           f"msg={(payload or {}).get('resultMsg')!r}")
    return (payload or {}).get("data") or {}


def parse_fixtures(payload: dict[str, Any], *, assume_offset: str | None = None
                   ) -> list[dict[str, Any]]:
    """把 recentMatchResult.do 响应整理成赛程行。

    `assume_offset` 形如 "+09:00"。不传则只给裸时间——接口没声明时区，不替调用方猜。
    """
    rows = []
    for row in _unwrap(payload).get("all") or []:
        date = str(row.get("gameDate") or "").replace(".", "-")
        time_ = str(row.get("gameTime") or "")
        naive = f"{date}T{time_}:00" if date and time_ else ""
        finished = str(row.get("endYn", "")).upper() == "Y"
        rows.append({
            "game_id": row.get("gameId"),
            "league_id": row.get("leagueId"),      # 1=K League 1, 2=K League 2
            "meet_seq": row.get("meetSeq"),
            "round": row.get("roundId"),
            "kickoff_naive": naive,
            "kickoff_iso": f"{naive}{assume_offset}" if naive and assume_offset else None,
            "assumed_offset": assume_offset,
            "finished": finished,
            # 未开赛才可能作赛前证据；已完赛的按契约是 POST_MATCH_NOT_USABLE
            "pre_match_status": "POST_MATCH_NOT_USABLE" if finished else "PRE_MATCH_CANDIDATE",
            "home_team_code": row.get("homeTeam"),
            "home_team_name": row.get("homeTeamName"),
            "away_team_code": row.get("awayTeam"),
            "away_team_name": row.get("awayTeamName"),
            "home_goal": row.get("homeGoal") if finished else None,
            "away_goal": row.get("awayGoal") if finished else None,
            "stadium": row.get("fieldNameFull") or row.get("fieldName"),
        })
    rows.sort(key=lambda r: (str(r["kickoff_naive"]), r["game_id"] or 0))
    return rows


def parse_standings(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """把 clubRank.do 响应整理成各级联赛的积分榜（含近6场走势）。"""
    data = _unwrap(payload)
    out: dict[str, list[dict[str, Any]]] = {}
    for key in ("league1", "league2"):
        table = []
        for row in data.get(key) or []:
            form = [FORM_CODES.get(str(row.get(f"game0{i}") or ""), "?")
                    for i in range(1, 7)
                    if row.get(f"game0{i}")]
            table.append({
                "rank": row.get("rank"),
                "team_code": row.get("teamId"),
                "team_name": row.get("teamName"),
                "points": row.get("gainPoint"),
                "played": row.get("gameCount"),
                "won": row.get("winCnt"),
                "drawn": row.get("tieCnt"),
                "lost": row.get("lossCnt"),
                "goals_for": row.get("gainGoal"),
                "goals_against": row.get("lossGoal"),
                "recent_form": form,
            })
        table.sort(key=lambda r: (r["rank"] is None, r["rank"]))
        out[key] = table
    return out


def _api_post(endpoint: str, *, timeout_s: int = 30) -> dict[str, Any]:
    import httpx

    response = httpx.post(f"{API_BASE}/{endpoint}", timeout=timeout_s,
                          headers={"User-Agent": USER_AGENT, "Referer": API_REFERER,
                                   "X-Requested-With": "XMLHttpRequest"})
    response.raise_for_status()
    return response.json()


def fetch_fixtures(*, assume_offset: str | None = None) -> list[dict[str, Any]]:
    """近期赛程/赛果。**这是 gameId 与队代码的来源**，喂给 fetch_match_players。"""
    return parse_fixtures(_api_post("recentMatchResult.do"), assume_offset=assume_offset)


def fetch_standings() -> dict[str, list[dict[str, Any]]]:
    """积分榜 + 近6场走势。赛前可用，对应六类证据的「战意/动机」「近况/状态」。"""
    return parse_standings(_api_post("clubRank.do"))


def _post(endpoint: str, payload: dict[str, str], *, timeout_s: int = 30) -> str:
    import httpx

    response = httpx.post(f"{BASE}/{endpoint}", timeout=timeout_s, data=payload,
                          headers={"User-Agent": USER_AGENT, "Referer": REFERER,
                                   "X-Requested-With": "XMLHttpRequest"})
    response.raise_for_status()
    return response.text


def fetch_match_players(meet_year: str, meet_seq: str, game_id: str,
                        home_team: str, away_team: str) -> dict[str, Any]:
    """取单场球员数据。返回结构里显式标出赛前可用性。"""
    html = _post("matchPlayerPosInfo.do", {
        "meetYear": str(meet_year), "meetSeq": str(meet_seq), "gameId": str(game_id),
        "homeTeam": str(home_team), "awayTeam": str(away_team)})
    players = extract_players(html)
    post_match = looks_post_match(players)
    return {
        "meet_year": meet_year, "meet_seq": meet_seq, "game_id": game_id,
        "home_team_code": home_team, "away_team_code": away_team,
        "player_count": len(players),
        "is_post_match": post_match,
        # 与数据契约同名，便于下游直接判定
        "pre_match_status": "POST_MATCH_NOT_USABLE" if post_match else "PRE_MATCH_CANDIDATE",
        "sides": split_by_side(players),
    }


def fetch_score_info(meet_year: str, meet_seq: str, game_id: str) -> str:
    """取单场比分信息片段（原始 HTML，交由调用方解析）。"""
    return _post("scoreInfoForMain.do", {
        "meetYear": str(meet_year), "meetSeq": str(meet_seq), "gameId": str(game_id)})


def _cmd_fixtures(args) -> int:
    rows = fetch_fixtures(assume_offset=args.assume_offset)
    print(f"{'gameId':>7} {'L':>2} {'开球(裸时间)':<20} {'状态':<22} 对阵")
    for row in rows:
        score = (f"{row['home_goal']}-{row['away_goal']}"
                 if row["finished"] else "vs")
        print(f"{row['game_id']:>7} {row['league_id']:>2} {row['kickoff_naive']:<20} "
              f"{row['pre_match_status']:<22} "
              f"{row['home_team_name']}({row['home_team_code']}) {score} "
              f"{row['away_team_name']}({row['away_team_code']})")
    if not args.assume_offset:
        print("\n开球时刻无时区 offset，未猜测；需要带时区请加 --assume-offset +09:00。")
    return _maybe_write(rows, args.out)


def _cmd_standings(args) -> int:
    tables = fetch_standings()
    for key, table in tables.items():
        print(f"== {key} ==")
        for row in table:
            print(f"  {row['rank']:>2} {row['team_name']:<8} {row['team_code']} "
                  f"积{row['points']:>3} {row['played']:>2}场 "
                  f"{row['won']}-{row['drawn']}-{row['lost']} "
                  f"进{row['goals_for']}失{row['goals_against']} "
                  f"近况 {' '.join(row['recent_form'])}")
    return _maybe_write(tables, args.out)


def _maybe_write(data, out) -> int:
    if out:
        from pathlib import Path
        Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"\n已写入 {out}")
    return 0


def _cmd_players(args) -> int:
    result = fetch_match_players(args.meet_year, args.meet_seq, args.game_id,
                                 args.home_team, args.away_team)
    print(f"球员 {result['player_count']} 人 | {result['pre_match_status']}")
    for side in ("home", "away"):
        names = [f"{p['back_no']}.{p['name']}({p['position']})"
                 for p in result["sides"][side][:11]]
        print(f"  {side}: {' '.join(names)}")
    if result["is_post_match"]:
        print("\n⚠️ 含赛后字段（出场时间/进球），按数据契约不得用作赛前证据。")
    elif result["player_count"] == 0:
        print("\n未开赛场次返回 0 人——官方门户没有赛前首发，这是已确认的缺口，不是抓取失败。")
    return _maybe_write(result, args.out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="K League 官方数据（赛程/积分榜/单场球员）")
    parser.add_argument("--out", help="写入 JSON 文件")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fix = sub.add_parser("fixtures", help="近期赛程/赛果，gameId 与队代码的来源")
    p_fix.add_argument("--assume-offset", help='显式指定时区，如 "+09:00"；不给则只出裸时间')
    p_fix.add_argument("--out")
    p_fix.set_defaults(func=_cmd_fixtures)

    p_rank = sub.add_parser("standings", help="积分榜 + 近6场走势（赛前可用）")
    p_rank.add_argument("--out")
    p_rank.set_defaults(func=_cmd_standings)

    p_pl = sub.add_parser("players", help="单场球员数据（⚠️ 赛后数据）")
    p_pl.add_argument("--meet-year", required=True)
    p_pl.add_argument("--meet-seq", required=True, help="1=K League 1, 2=K League 2")
    p_pl.add_argument("--game-id", required=True, help="从 fixtures 子命令取")
    p_pl.add_argument("--home-team", required=True, help="队代码，如 K22")
    p_pl.add_argument("--away-team", required=True, help="队代码，如 K03")
    p_pl.add_argument("--out")
    p_pl.set_defaults(func=_cmd_players)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
