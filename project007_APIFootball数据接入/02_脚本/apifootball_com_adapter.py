#!/usr/bin/env python3
"""Adapter for the *API-Sports Football* service at apifootball.com.

This is intentionally separate from ``api_football_adapter.py``.  The two
providers have different base URLs, authentication schemes and response
contracts.  The key is read only from ``APIFOOTBALL_COM_KEY`` and is never
written to an output file or included in an exception message.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

BASE = "https://apiv3.apifootball.com/"
KEY_ENV = "APIFOOTBALL_COM_KEY"
HEAD = {"User-Agent": "football-quant-fusion/apifootball-com", "Accept": "application/json"}


def client() -> str:
    """Return the provider key, failing closed when only the other provider is set."""
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise SystemExit(f"缺少环境变量 {KEY_ENV}（apifootball.com 的 API key）")
    return key


def build_url(action: str, params: dict[str, Any] | None, key: str) -> str:
    query = {"action": action, **(params or {}), "APIkey": key}
    return BASE + "?" + urllib.parse.urlencode(query)


def redact_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    safe = [(k, "[REDACTED]" if k.lower() == "apikey" else v) for k, v in query]
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(safe), parts.fragment))


def request(action: str, params: dict[str, Any] | None = None,
            opener: Callable[..., Any] | None = None) -> Any:
    key = client()
    url = build_url(action, params, key)
    opener = opener or urllib.request.urlopen
    try:
        req = urllib.request.Request(url, headers=HEAD)
        with opener(req, timeout=30) as resp:
            payload = json.load(resp)
    except Exception as exc:
        raise RuntimeError(f"apifootball.com 请求失败（{redact_url(url)}）：{exc}") from exc
    if not isinstance(payload, (dict, list)):
        raise RuntimeError("apifootball.com 返回格式不是 JSON 对象或数组")
    if isinstance(payload, dict) and (str(payload.get("success", "1")) in {"0", "false", "False"} or payload.get("error")):
        detail = payload.get("error") or payload.get("message") or "provider returned success=0"
        raise RuntimeError(f"apifootball.com 返回错误：{detail}")
    return payload


def _int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _result(payload: Any) -> list[dict[str, Any]]:
    rows = payload if isinstance(payload, list) else payload.get("result", [])
    if isinstance(rows, dict):
        rows = [rows]
    return [x for x in rows if isinstance(x, dict)]


def normalize_countries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"country_id": _int(x.get("country_id")), "country_name": x.get("country_name")}
            for x in _result(payload)]


def normalize_leagues(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"league_id": _int(x.get("league_key", x.get("league_id"))), "league_name": x.get("league_name"),
             "country_id": _int(x.get("country_key", x.get("country_id"))), "country_name": x.get("country_name")}
            for x in _result(payload)]


def normalize_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for x in _result(payload):
        rows.append({
            "match_id": _int(x.get("match_id")), "date": x.get("match_date"),
            "time": x.get("match_time"), "status": x.get("match_status"),
            "league_id": _int(x.get("league_id")), "league_name": x.get("league_name"),
            "home": x.get("match_hometeam_name"), "home_id": _int(x.get("match_hometeam_id")),
            "away": x.get("match_awayteam_name"), "away_id": _int(x.get("match_awayteam_id")),
            "goals": {"home": _int(x.get("match_hometeam_score")),
                      "away": _int(x.get("match_awayteam_score"))},
        })
    return rows


def normalize_standings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for x in _result(payload):
        gf = _int(x.get("overall_league_GF", x.get("standing_GF")))
        ga = _int(x.get("overall_league_GA", x.get("standing_GA")))
        rows.append({
            "rank": _int(x.get("overall_league_position", x.get("standing_place"))),
            "team_id": _int(x.get("team_id", x.get("team_key"))),
            "team": x.get("team_name", x.get("standing_team")),
            "played": _int(x.get("overall_league_payed", x.get("overall_league_played", x.get("standing_P")))),
            "wins": _int(x.get("overall_league_W", x.get("standing_W"))),
            "draws": _int(x.get("overall_league_D", x.get("standing_D"))),
            "losses": _int(x.get("overall_league_L", x.get("standing_L"))),
            "points": _int(x.get("overall_league_PTS", x.get("standing_PTS"))),
            "goals_for": gf, "goals_against": ga,
            "goals_diff": _int(x.get("standing_GD")) if x.get("standing_GD") is not None else (gf - ga if gf is not None and ga is not None else None),
        })
    return rows


def normalize_teams(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"team_id": _int(x.get("team_key")), "team": x.get("team_name"),
             "country": x.get("team_country"), "logo": x.get("team_badge", x.get("team_logo"))} for x in _result(payload)]


def normalize_match_objects(payload: Any) -> list[dict[str, Any]]:
    """Unwrap endpoints such as get_statistics/get_lineups keyed by match_id."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    if "result" in payload:
        return _result(payload)
    rows = []
    for key, value in payload.items():
        if isinstance(value, dict):
            item = dict(value)
            if str(key).isdigit():
                item.setdefault("match_id", _int(key))
            rows.append(item)
    return rows or [payload]


def normalize_passthrough(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep provider-specific lineups/statistics intact until their schema is verified."""
    return _result(payload)


def save(output: str | None, payload: Any, rows: list[dict[str, Any]]) -> None:
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary: dict[str, Any] = {"status": "ok", "provider": "apifootball.com", "count": len(rows), "preview": rows[:10]}
    if output and len(rows) > 10:
        summary["note"] = "完整 provider 信封已写入 --output，预览仅前 10 条"
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def run(a: argparse.Namespace) -> None:
    params: dict[str, Any] = {}
    if a.cmd == "countries":
        action, normalizer = "get_countries", normalize_countries
    elif a.cmd == "leagues":
        action, normalizer = "get_leagues", normalize_leagues
        if a.country_id: params["country_id"] = a.country_id
    elif a.cmd == "events":
        action, normalizer = "get_events", normalize_events
        for dest, key in (("from_date", "from"), ("to_date", "to"), ("timezone", "timezone"),
                          ("country_id", "country_id"), ("league_id", "league_id"),
                          ("match_id", "match_id"), ("team_id", "team_id"), ("live", "match_live")):
            value = getattr(a, dest, None)
            if value is not None: params[key] = value
        if a.with_player_stats:
            params["withPlayerStats"] = "1"
    elif a.cmd == "standings":
        action, normalizer = "get_standings", normalize_standings
        params["league_id"] = a.league_id
    elif a.cmd == "teams":
        action, normalizer = "get_teams", normalize_teams
        if a.league_id: params["league_id"] = a.league_id
        if a.team_id: params["team_id"] = a.team_id
    elif a.cmd == "lineups":
        action, normalizer = "get_lineups", normalize_match_objects
        params["match_id"] = a.match_id
    elif a.cmd == "statistics":
        action, normalizer = "get_statistics", normalize_match_objects
        params["match_id"] = a.match_id
    else:
        raise SystemExit(f"未知命令: {a.cmd}")
    payload = request(action, params)
    save(a.output, payload, normalizer(payload))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="apifootball.com adapter (key: APIFOOTBALL_COM_KEY env)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def output(p: argparse.ArgumentParser) -> None:
        p.add_argument("--output", help="写入完整 provider JSON 信封；stdout 仅输出脱敏预览")

    p = sub.add_parser("countries"); output(p); p.set_defaults(fn=run)
    p = sub.add_parser("leagues"); p.add_argument("--country-id", type=int); output(p); p.set_defaults(fn=run)
    p = sub.add_parser("events"); p.add_argument("--from-date"); p.add_argument("--to-date"); p.add_argument("--timezone"); p.add_argument("--country-id", type=int); p.add_argument("--league-id", type=int); p.add_argument("--match-id", type=int); p.add_argument("--team-id", type=int); p.add_argument("--live"); p.add_argument("--with-player-stats", action="store_true"); output(p); p.set_defaults(fn=run)
    p = sub.add_parser("standings"); p.add_argument("--league-id", type=int, required=True); output(p); p.set_defaults(fn=run)
    p = sub.add_parser("teams"); g = p.add_mutually_exclusive_group(); g.add_argument("--league-id", type=int); g.add_argument("--team-id", type=int); output(p); p.set_defaults(fn=run)
    p = sub.add_parser("lineups"); p.add_argument("--match-id", type=int, required=True); output(p); p.set_defaults(fn=run)
    p = sub.add_parser("statistics"); p.add_argument("--match-id", type=int, required=True); output(p); p.set_defaults(fn=run)
    a = ap.parse_args(argv); a.fn(a)


if __name__ == "__main__":
    main()
