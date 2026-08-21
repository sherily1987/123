#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按联赛解析近 5 场检索地址。

地址来自仓库 `30_数据/网页源可达性矩阵.md` 与已复验的 fotmob / understat / kleague
表。不猜未列入的 FotMob id；封锁源不出现在返回列表里。
本模块只给检索路径，不抓页、不写主证据。
"""
from __future__ import annotations

FOTMOB_LEAGUES = "https://www.fotmob.com/api/data/leagues?id={id}"
FOTMOB_CATALOG = "https://www.fotmob.com/api/data/allLeagues"
UNDERSTAT = "https://understat.com/getLeagueData/{code}/{season}"
JLEAGUE = "https://www.jleague.jp/en/match/"
KLEAGUE_RANK = "https://www.kleague.com/api/clubRank.do"
KLEAGUE_FIXTURES = "https://www.kleague.com/api/recentMatchResult.do"
FLASHSCORE = "https://www.flashscore.com/"
TM_KLEAGUE = "https://www.transfermarkt.com/k-league-1/startseite/wettbewerb/RSK1"

BLOCKED_FORM_HOSTS = (
    "fbref.com",
    "whoscored.com",
    "forebet.com",
    "besoccer.com",
)

# 体彩常用名 → 近 5 场主源。fotmob id / understat 代号禁止在表外猜测。
_LEAGUES: dict[str, dict] = {
    "英超": {"understat": "EPL"},
    "西甲": {"understat": "La_liga"},
    "德甲": {"understat": "Bundesliga"},
    "意甲": {"understat": "Serie_A"},
    "法甲": {"understat": "Ligue_1"},
    "荷甲": {"fotmob": 57},
    "Eredivisie": {"fotmob": 57},
    "葡超": {"fotmob": 61},
    "日职": {"fotmob": 223, "jleague": True},
    "J1": {"fotmob": 223, "jleague": True},
    "日乙": {"fotmob": 8974, "jleague": True},
    "J2": {"fotmob": 8974, "jleague": True},
    "韩职": {"kleague": True, "fotmob": 9080, "transfermarkt": TM_KLEAGUE},
    "K League 1": {"kleague": True, "fotmob": 9080},
    "韩K2": {"kleague": True, "fotmob": 9116},
    "K League 2": {"kleague": True, "fotmob": 9116},
    "瑞超": {"fotmob": 67},
    "挪超": {"fotmob": 59},
    "英冠": {"fotmob": 48},
    "巴甲": {"fotmob": 268},
    "芬超": {"fotmob": 51},
    "沙职": {"fotmob": 536},
    "美职": {"fotmob": 130},
    "MLS": {"fotmob": 130},
}


def sources_for(league: str, season_start: int | None = None) -> dict:
    """返回该联赛近 5 场应访问的 URL 列表。未知联赛只给目录+Flashscore，不编 id。"""
    key = str(league or "").strip()
    spec = _LEAGUES.get(key)
    season = int(season_start) if season_start else 2026
    urls: list[str] = []
    if spec and spec.get("understat"):
        urls.append(UNDERSTAT.format(code=spec["understat"], season=season))
        # 揭幕战本季页为空：同时给上季页，取该队对其他对手的正式近5场。
        urls.append(UNDERSTAT.format(code=spec["understat"], season=season - 1))
    if spec and spec.get("jleague"):
        urls.append(JLEAGUE)
    if spec and spec.get("kleague"):
        urls.extend([KLEAGUE_RANK, KLEAGUE_FIXTURES])
    if spec and spec.get("fotmob"):
        urls.append(FOTMOB_LEAGUES.format(id=spec["fotmob"]))
    if spec and spec.get("transfermarkt"):
        urls.append(spec["transfermarkt"])
    if not spec:
        urls.append(FOTMOB_CATALOG)
    urls.append(FLASHSCORE)
    return {
        "league": key,
        "known": spec is not None,
        "http_first": True,
        "urls": urls,
        "blocked": list(BLOCKED_FORM_HOSTS),
    }
