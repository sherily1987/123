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
# 值可以是 league_id，或带 provider/league_name 的字典。
# 沙职 api-sports 307 与瑞超 apifootball 307 撞号，必须用 provider/联赛名拆开。
GOALS_ONLY = {
    "荷甲": 244, "Eredivisie": 244,
    "葡超": 266, "Primeira Liga": 266,
    "土超": 322, "Super Lig": 322, "Süper Lig": 322,
    "苏格兰超": 279, "苏超": 279, "苏格兰 Premiership": 279, "Scottish Premiership": 279,
    "瑞士超": 308, "瑞士 Super League": 308, "Swiss Super League": 308,
    "挪超": {"league_id": 253, "provider": "apifootball.com", "league_name_contains": "Eliteserien"},
    "Eliteserien": {"league_id": 253, "provider": "apifootball.com", "league_name_contains": "Eliteserien"},
    "芬超": 352, "Veikkausliiga": 352,
    "瑞超": {"league_id": 307, "provider": "apifootball.com", "league_name_contains": "Allsvenskan"},
    "Allsvenskan": {"league_id": 307, "provider": "apifootball.com", "league_name_contains": "Allsvenskan"},
    "沙职": {"league_id": 307, "provider": "api-sports.io", "league_name_contains": "Pro League"},
    "韩职": 292, "K League 1": 292,
    "日职": 98, "J1 League": 98,
    "巴甲": "BRA", "巴西甲": "BRA",
    "英冠": "E1", "Championship": "E1",
    "法乙": "F2", "Ligue 2": "F2",
    "比甲": 63, "First Division A": 63,
    "奥超": 56,
    "波甲": 259, "Ekstraklasa": 259,
    "丹超": 135, "Superliga": 135,
    "希超": 178,
    "欧冠": 3, "欧冠杯": 3, "UEFA Champions League": 3, "Champions League": 3,
    "欧罗巴": 4, "欧联": 4, "欧罗巴联赛": 4, "UEFA Europa League": 4, "Europa League": 4,
    "欧协联": 683, "欧协": 683, "UEFA Europa Conference League": 683,
    "UEFA Conference League": 683, "Conference League": 683,
    "欧超杯": {"league_ids": [372, 531], "league_name_contains": "Super Cup"},
    "UEFA Super Cup": {"league_ids": [372, 531], "league_name_contains": "Super Cup"},
    "世界杯": 28, "World Cup": 28,
    "世预赛": {"league_ids": [24, 32], "league_name_contains": "World Cup - Qualification"},
    "解放者杯": 13, "CONMEBOL Libertadores": 13, "Copa Libertadores": 13,
    "南美杯": 11, "CONMEBOL Sudamericana": 11,
    "亚冠精英": 17, "亚冠": 17, "AFC Champions League Elite": 17, "AFC Champions League": 17,
    "亚冠乙": 18, "AFC Champions League Two": 18,
    "阿甲": "ARG", "阿根廷甲": "ARG", "Liga Profesional Argentina": "ARG",
    "美职": {"league_ids": [253, "USA"], "league_name_contains": "Major League Soccer"},
    "MLS": {"league_ids": [253, "USA"], "league_name_contains": "Major League Soccer"},
    "荷乙": {"league_ids": [89, 245], "league_name_contains": "Eerste"},
    "Eerste Divisie": {"league_ids": [89, 245], "league_name_contains": "Eerste"},
    "日乙": 99, "J2 League": 99,
    "德乙": {"league_ids": [79, 176, "D2"], "league_name_contains": "2. Bundesliga"},
    "澳超": 188, "A-League": 188,
    "英甲": {"league_ids": [41, "E2"]},
    "英社区盾": 528, "Community Shield": 528,
    "中超": 169,
    "捷甲": 134, "捷克甲": 134,
    "克亚": 124, "克罗地亚甲": 124,
    "匈甲": 191,
    "罗甲": 272,
    "俄超": 344,
    "白俄超": 61,
    "波黑甲": 71,
    "保超": {"league_ids": [111, 172]}, "保甲": {"league_ids": [111, 172]},
    "塞浦甲": {"league_ids": [130, 318]},
    "塞超": {"league_ids": [288, 286]},
    "乌超": {"league_ids": [325, 333]},
    "爱沙超": 156,
    "冰岛甲": 395,
    "以超": 202,
    "以甲": 201,
    "爱超": 200,
    "拉脱维亚甲": 222,
    "立甲": 226,
    "卢森堡甲": 228,
    "摩超": 237,
    "黑山甲": 398,
    "斯洛伐克超": 293,
    "斯洛文尼亚甲": 296,
    "英足总杯": {"league_ids": [45, 146]},
    "英联赛杯": 48,
    "西国王杯": 143,
    "意大利杯": 137,
    "德国杯": 81,
    "法国杯": {"league_ids": [66, 147]},
    "荷兰杯": {"league_ids": [90, 246]},
    "非洲杯": 6,
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
    if len(home_for) < min_history or len(away_for) < min_history:
        return None
    # 透明候选：本队进攻与对手防守均值合成。只作研究影子，不使用未验证缩放。
    lh = max(0.05, min(6.0, mean((mean(home_for), mean(away_against)))))
    la = max(0.05, min(6.0, mean((mean(away_for), mean(home_against)))))
    return {
        "lambda_home": round(lh, 6),
        "lambda_away": round(la, 6),
        "sample_legs": len(eligible),
        "team_sample_sizes": {"home": len(home_for), "away": len(away_for)},
        "history_latest": max(_dt(r.get("datetime") or r.get("kickoff")) for r in eligible).isoformat(),
    }


def _event_time(row: dict) -> datetime | None:
    return _dt(row.get("kickoff") or row.get("date"))


def _event_score(row: dict) -> tuple[int, int] | None:
    actual = row.get("actual")
    if isinstance(actual, (list, tuple)) and len(actual) == 2:
        try:
            return int(actual[0]), int(actual[1])
        except (TypeError, ValueError):
            return None
    for home_key, away_key in (
        ("score_home", "score_away"),
        ("home_goals", "away_goals"),
        ("gh", "ga"),
    ):
        if row.get(home_key) is None or row.get(away_key) is None:
            continue
        try:
            return int(row[home_key]), int(row[away_key])
        except (TypeError, ValueError):
            return None
    return None


def _league_spec(spec: Any) -> dict:
    if isinstance(spec, dict):
        return spec
    return {"league_id": spec}


def _event_in_league(row: dict, spec: Any) -> bool:
    cfg = _league_spec(spec)
    targets = cfg.get("league_ids")
    if targets is None and cfg.get("league_id") is not None:
        targets = [cfg["league_id"]]
    row_id = row.get("league_id")
    if targets is not None and row_id is not None:
        allowed = {str(item).strip() for item in targets}
        if str(row_id).strip() not in allowed:
            return False
    provider = cfg.get("provider")
    needle = str(cfg.get("league_name_contains") or "").casefold()
    if provider:
        row_provider = str(row.get("provider") or "")
        row_name = str(row.get("league_name") or row.get("league") or "")
        if row_provider:
            if row_provider != provider:
                return False
        elif needle:
            if needle not in row_name.casefold():
                return False
        else:
            return False
    elif needle:
        row_name = str(row.get("league_name") or row.get("league") or "")
        if needle not in row_name.casefold():
            return False
    return True


def load_event_rows(path: str | Path | None) -> list[dict]:
    """Load Finished-capable event rows from a JSON/JSONL file or a directory of *_events.jsonl."""
    if not path:
        return []
    text = str(path)
    candidate = Path(text)
    if ("," in text) and not candidate.exists():
        rows: list[dict] = []
        for part in text.split(","):
            rows.extend(load_event_rows(part.strip()))
        return rows
    if not candidate.exists():
        return []
    if candidate.is_dir():
        rows = []
        files = sorted(candidate.glob("*_events.jsonl")) + sorted(candidate.glob("*_events.json"))
        for file_path in files:
            rows.extend(load_event_rows(file_path))
        return rows
    raw = candidate.read_text(encoding="utf-8-sig")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value.get("events") or value.get("matches") or []
    return []


def _rolling_goals(events: list[dict], home: str, away: str, kickoff: datetime, spec: Any, min_history: int) -> dict | None:
    eligible = []
    for row in events:
        when = _event_time(row)
        if not when or when >= kickoff:
            continue
        if not _event_in_league(row, spec):
            continue
        if str(row.get("status", "")).lower() != "finished":
            continue
        if any(_same_team(row.get(side), target) for side in ("home", "away") for target in (home, away)):
            score = _event_score(row)
            if score is None:
                continue
            hs, aws = score
            eligible.append((row, hs, aws))
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
    if len(home_for) < min_history or len(away_for) < min_history:
        return None
    lh = max(0.05, min(6.0, mean((mean(home_for), mean(away_against)))))
    la = max(0.05, min(6.0, mean((mean(away_for), mean(home_against)))))
    return {
        "lambda_home": round(lh, 6),
        "lambda_away": round(la, 6),
        "sample_legs": len(eligible),
        "team_sample_sizes": {"home": len(home_for), "away": len(away_for)},
        "history_latest": max(_event_time(r[0]) for r in eligible).isoformat(),
    }


def _apply_prior(match: dict, prior: dict, source: str, route: str, kickoff: datetime, note: str) -> dict:
    match["mode"] = "hybrid"
    match["research_only"] = True
    match["lambda_prior"] = {
        "lambda_home": prior["lambda_home"],
        "lambda_away": prior["lambda_away"],
        "weight": 0.05 if source == "understat_rolling_xg" else 0.02,
        "source": source,
        "sample_legs": prior["sample_legs"],
        "team_sample_sizes": prior["team_sample_sizes"],
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


def _attach_shadow_candidate(match: dict, prior: dict, source: str, route: str,
                             kickoff: datetime, note: str) -> dict:
    """Attach an auditable candidate without changing production inputs or mode."""
    match["research_candidate"] = {
        "status": "SHADOW_ONLY",
        "lambda_prior": {
            "lambda_home": prior["lambda_home"],
            "lambda_away": prior["lambda_away"],
            "proposed_weight": 0.05 if source == "understat_rolling_xg" else 0.02,
            "source": source,
            "sample_legs": prior["sample_legs"],
            "team_sample_sizes": prior["team_sample_sizes"],
            "note": note,
        },
    }
    match.setdefault("field_meta", {})["production_router"] = _audit(
        route, kickoff, source=source, sample_legs=prior["sample_legs"],
        team_sample_sizes=prior["team_sample_sizes"], history_latest=prior["history_latest"],
        candidate_status="SHADOW_ONLY",
    )
    match.setdefault("assumptions", []).append(
        f"研究影子候选：{route}；未注入lambda_prior，未改变生产概率"
    )
    return match


def route_match(match: dict, understat_rows: list[dict], events: list[dict], min_history: int = 5,
                enable_experimental: bool = False) -> dict:
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
            fn = _apply_prior if enable_experimental else _attach_shadow_candidate
            return fn(match, prior, "understat_rolling_xg", "understat_xg", kickoff, "开球前历史滚动xG生成λ候选")
        return _set_fallback(match, "understat_pre_kickoff_history_unavailable", kickoff)
    league_id = GOALS_ONLY.get(competition)
    if league_id is not None:
        prior = _rolling_goals(events, home, away, kickoff, league_id, min_history)
        if prior:
            fn = _apply_prior if enable_experimental else _attach_shadow_candidate
            return fn(match, prior, "apifootball_events_goals_only", "apifootball_goals_only", kickoff, "开球前APIfootball Finished历史进球生成λ候选")
        return _set_fallback(match, "apifootball_pre_kickoff_history_unavailable", kickoff)
    return _set_fallback(match, "league_not_in_production_experiment_scope", kickoff)


def route_matches(data: dict | list, understat_rows: list[dict], events: list[dict], min_history: int = 5,
                  enable_experimental: bool = False) -> dict | list:
    if isinstance(data, dict) and isinstance(data.get("matches"), list):
        out = deepcopy(data)
        out["matches"] = [route_match(m, understat_rows, events, min_history, enable_experimental)
                          for m in data["matches"]]
        out["production_route"] = {
            "status": "research_only" if enable_experimental else "shadow_only",
            "fallback": "MARKET_BASELINE",
            "understat_rows": len(understat_rows),
            "apifootball_event_rows": len(events),
            "no_future_leakage": True,
        }
        return out
    return route_match(data, understat_rows, events, min_history, enable_experimental)
