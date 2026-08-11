#!/usr/bin/env python3
"""生产模型按联赛分流路由器。

安全边界：
- Understat只使用目标开球前的历史滚动xG，不使用目标比赛自身的赛后xG。
- APIfootball只使用目标开球前的Finished历史90分钟进球。
- 任一数据源缺失、队名不匹配或样本不足，回退MARKET_BASELINE。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
from typing import Any

BIG5 = {"英超": "EPL", "西甲": "La_liga", "意甲": "Serie_A", "德甲": "Bundesliga", "法甲": "Ligue_1"}
GOALS_ONLY = {
    "荷甲": 244, "Eredivisie": 244,
    "葡超": 266, "Primeira Liga": 266,
    "土超": 322, "Super Lig": 322, "Süper Lig": 322,
    "苏格兰超": 279, "苏格兰 Premiership": 279, "Scottish Premiership": 279,
    "瑞士超": 308, "瑞士 Super League": 308, "Swiss Super League": 308,
    "挪超": 253, "Eliteserien": 253,
}

_ALIAS_CONFIG = Path(__file__).resolve().parent.parent / "config" / "intl_odds_sources.json"
try:
    _TEAM_ALIASES = json.loads(_ALIAS_CONFIG.read_text(encoding="utf-8-sig")).get("team_aliases", {})
except (OSError, json.JSONDecodeError):
    _TEAM_ALIASES = {}


def _same_team(actual: Any, target: str) -> bool:
    """支持体彩中文短名与APIfootball英文队名的受控匹配。"""
    if actual is None:
        return False
    def normalize(value: Any) -> str:
        return " ".join(str(value).casefold().replace("-", " ").split())
    candidates = [target, *_TEAM_ALIASES.get(target, [])]
    return normalize(actual) in {normalize(candidate) for candidate in candidates}


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _kickoff(match: dict) -> datetime | None:
    return _dt(match.get("kickoff") or match.get("kickoff_iso"))


def _audit(route: str, kickoff: datetime | None, **extra: Any) -> dict:
    out = {
        "route": route,
        "as_of": kickoff.isoformat() if kickoff else None,
        "no_future_leakage": True,
        "fallback_reason": None,
    }
    out.update(extra)
    return out


def _set_fallback(match: dict, reason: str, kickoff: datetime | None) -> dict:
    match["mode"] = "market_only"
    meta = match.setdefault("field_meta", {})
    meta["production_router"] = _audit("market_baseline", kickoff, fallback_reason=reason)
    match.setdefault("assumptions", []).append(f"生产路由回退MARKET_BASELINE：{reason}")
    return match


def _eligible_xg(rows: list[dict], home: str, away: str, kickoff: datetime) -> list[dict]:
    eligible = []
    for row in rows:
        when = _dt(row.get("datetime") or row.get("kickoff"))
        if not when or when >= kickoff:
            continue
        if row.get("home_xg") is None or row.get("away_xg") is None:
            continue
        if any(_same_team(row.get(side), target) for side in ("home", "away") for target in (home, away)):
            eligible.append(row)
    return eligible


def _rolling_xg(rows: list[dict], home: str, away: str, kickoff: datetime, min_history: int) -> dict | None:
    eligible = _eligible_xg(rows, home, away, kickoff)
    if len(eligible) < min_history:
        return None

    home_for, home_against, away_for, away_against = [], [], [], []
    for row in eligible:
        rh, ra = str(row.get("home")), str(row.get("away"))
        hxg, axg = float(row["home_xg"]), float(row["away_xg"])
        if _same_team(rh, home):
            home_for.append(hxg); home_against.append(axg)
        elif _same_team(ra, home):
            home_for.append(axg); home_against.append(hxg)
        if _same_team(rh, away):
            away_for.append(hxg); away_against.append(axg)
        elif _same_team(ra, away):
            away_for.append(axg); away_against.append(hxg)
    if not home_for or not away_for or not home_against or not away_against:
        return None
    # 先取近期过程均值，再用对手防守均值合成λ；保留保守缩放，避免单场极端值。
    lh = max(0.05, min(6.0, 0.9 * mean((mean(home_for), mean(away_against)))))
    la = max(0.05, min(6.0, 0.9 * mean((mean(away_for), mean(home_against)))))
    return {
        "lambda_home": round(lh, 6),
        "lambda_away": round(la, 6),
        "sample_legs": len(eligible),
        "history_latest": max(_dt(r.get("datetime") or r.get("kickoff")) for r in eligible).isoformat(),
    }


def _event_time(row: dict) -> datetime | None:
    return _dt(row.get("kickoff") or row.get("date"))


def _rolling_goals(events: list[dict], home: str, away: str, kickoff: datetime, league_id: int, min_history: int) -> dict | None:
    eligible = []
    for row in events:
        when = _event_time(row)
        if not when or when >= kickoff:
            continue
        if row.get("league_id") is not None and int(row["league_id"]) != int(league_id):
            continue
        if str(row.get("status", "")).lower() != "finished":
            continue
        if any(_same_team(row.get(side), target) for side in ("home", "away") for target in (home, away)):
            try:
                hs, aws = int(row["score_home"]), int(row["score_away"])
            except (KeyError, TypeError, ValueError):
                continue
            eligible.append((row, hs, aws))
    if len(eligible) < min_history:
        return None
    home_for, home_against, away_for, away_against = [], [], [], []
    for row, hs, aws in eligible:
        if _same_team(row.get("home"), home):
            home_for.append(hs); home_against.append(aws)
        elif _same_team(row.get("away"), home):
            home_for.append(aws); home_against.append(hs)
        if _same_team(row.get("home"), away):
            away_for.append(hs); away_against.append(aws)
        elif _same_team(row.get("away"), away):
            away_for.append(aws); away_against.append(hs)
    if not home_for or not away_for:
        return None
    lh = max(0.05, min(6.0, mean((mean(home_for), mean(away_against)))))
    la = max(0.05, min(6.0, mean((mean(away_for), mean(home_against)))))
    return {
        "lambda_home": round(lh, 6),
        "lambda_away": round(la, 6),
        "sample_legs": len(eligible),
        "history_latest": max(_event_time(r[0]) for r in eligible).isoformat(),
    }


def _apply_prior(match: dict, prior: dict, source: str, route: str, kickoff: datetime, note: str) -> dict:
    match["mode"] = "hybrid"
    match["lambda_prior"] = {
        "lambda_home": prior["lambda_home"],
        "lambda_away": prior["lambda_away"],
        "weight": 0.05 if source == "understat_rolling_xg" else 0.02,
        "source": source,
        "sample_legs": prior["sample_legs"],
        "note": note,
    }
    match.setdefault("field_meta", {})["production_router"] = _audit(
        route, kickoff, source=source, sample_legs=prior["sample_legs"], history_latest=prior["history_latest"]
    )
    match["field_meta"]["lambda_prior"] = {
        "status": "VALID",
        "source": source,
        "as_of": kickoff.isoformat(),
        "sample_legs": prior["sample_legs"],
        "no_future_leakage": True,
    }
    match.setdefault("adjustment_ledger", []).append({
        "field": "lambda_prior",
        "fact": note,
        "source": source,
        "mapping_basis": "production_router uses only historical rows before kickoff",
        "calibration": "EXPERIMENTAL_NOT_PROMOTED",
        "system_generated": True,
        "sample_legs": prior["sample_legs"],
    })
    match.setdefault("assumptions", []).append(f"生产路由：{route}；权重仍为实验权重")
    return match


def route_match(match: dict, understat_rows: list[dict], events: list[dict], min_history: int = 5) -> dict:
    match = deepcopy(match)
    kickoff = _kickoff(match)
    if kickoff is None:
        return _set_fallback(match, "missing_or_invalid_kickoff", kickoff)
    competition = str(match.get("competition") or match.get("stage") or "").strip()
    home, away = str(match.get("home") or ""), str(match.get("away") or "")
    if not home or not away:
        return _set_fallback(match, "missing_team_name", kickoff)
    if competition in BIG5:
        prior = _rolling_xg(understat_rows, home, away, kickoff, min_history)
        if prior:
            return _apply_prior(match, prior, "understat_rolling_xg", "understat_xg", kickoff, "开球前历史滚动xG生成λ先验")
        return _set_fallback(match, "understat_pre_kickoff_history_unavailable", kickoff)
    league_id = GOALS_ONLY.get(competition)
    if league_id is not None:
        prior = _rolling_goals(events, home, away, kickoff, league_id, min_history)
        if prior:
            return _apply_prior(match, prior, "apifootball_events_goals_only", "apifootball_goals_only", kickoff, "开球前APIfootball Finished历史进球生成λ先验")
        return _set_fallback(match, "apifootball_pre_kickoff_history_unavailable", kickoff)
    return _set_fallback(match, "league_not_in_production_experiment_scope", kickoff)


def route_matches(data: dict | list, understat_rows: list[dict], events: list[dict], min_history: int = 5) -> dict | list:
    if isinstance(data, dict) and isinstance(data.get("matches"), list):
        out = deepcopy(data)
        out["matches"] = [route_match(m, understat_rows, events, min_history) for m in data["matches"]]
        out["production_route"] = {
            "status": "enabled",
            "fallback": "MARKET_BASELINE",
            "understat_rows": len(understat_rows),
            "apifootball_event_rows": len(events),
            "no_future_leakage": True,
        }
        return out
    return route_match(data, understat_rows, events, min_history)
