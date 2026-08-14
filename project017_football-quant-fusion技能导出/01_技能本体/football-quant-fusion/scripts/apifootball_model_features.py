#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""APIfootball赛前特征构建器。

功能：
1. 用APIfootball历史完赛赛果拟合时间衰减Dixon-Coles球队强度；
2. 从历史比赛统计生成赛前滚动射门/射正/禁区内射门特征；
3. 挂载赛前积分榜、首发/缺阵、官方预测和国际赔率的分层数据；
4. 可选把独立球队λ作为lambda_prior注入fusion输入。

重要规则：
- 历史数据按kickoff排序，先生成当前场快照，再加入当前场结果，禁止未来信息泄漏；
- get_statistics默认只作为历史滚动训练观测，不把当前场赛后统计当赛前特征；
- 默认mode保持输入原值；只有显式--mode hybrid/model_first才改变模型路径；
- 任何xG字段只有实际存在时才读取，缺失不填0。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from runtime_paths import core_scripts_dir

ZUYU = core_scripts_dir()
if str(ZUYU) not in sys.path:
    sys.path.insert(0, str(ZUYU))

import team_strength  # noqa: E402

STAT_ALIASES = {
    "shots_total": {"shots total", "shots total"},
    "shots_on_target": {"shots on goal", "on target", "shots on target"},
    "shots_inside_box": {"shots inside box"},
    "shots_outside_box": {"shots outside box"},
    "shots_blocked": {"shots blocked"},
    "dangerous_attacks": {"dangerous attacks"},
    "attacks": {"attacks"},
    "possession": {"ball possession", "possession"},
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def parse_dt(value):
    if not value:
        return None
    s = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value)[:19], fmt)
            except ValueError:
                pass
    return None


def parse_day(value):
    dt = parse_dt(value)
    return dt.date().toordinal() if dt else None


def as_list(data, key=None):
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and key and isinstance(data.get(key), list):
        return data[key]
    if isinstance(data, dict) and isinstance(data.get("events"), list):
        return data["events"]
    return []


def number(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("%", ""))
    except (TypeError, ValueError):
        return None


def event_row(event):
    status = str(event.get("match_status") or event.get("status") or "").lower()
    if status and status not in {"finished", "after et", "after pen.", "after pen", "awarded"}:
        return None
    home = event.get("match_hometeam_name") or event.get("home") or event.get("home_team")
    away = event.get("match_awayteam_name") or event.get("away") or event.get("away_team")
    gh = (event.get("match_hometeam_ft_score") or event.get("match_hometeam_score")
          or event.get("score_home") or event.get("home_goals"))
    ga = (event.get("match_awayteam_ft_score") or event.get("match_awayteam_score")
          or event.get("score_away") or event.get("away_goals"))
    day = parse_day(event.get("match_date") or event.get("date") or event.get("kickoff"))
    if not home or not away or gh in (None, "") or ga in (None, "") or day is None:
        return None
    try:
        gh, ga = int(float(gh)), int(float(ga))
    except (TypeError, ValueError):
        return None
    return {
        "match_id": str(event.get("match_id") or event.get("id") or ""),
        "home": str(home), "away": str(away), "gh": gh, "ga": ga,
        "day": day, "kickoff": event.get("match_date") or event.get("date") or event.get("kickoff"),
        "league_id": str(event.get("league_id") or ""),
        "league": event.get("league_name") or event.get("league") or "",
    }


def stats_by_match(data):
    """把get_statistics原始JSON转成match_id -> type/value。"""
    rows = data.get("records", data) if isinstance(data, dict) else data
    out = {}
    if isinstance(rows, dict):
        rows = [{"match_id": k, **(v if isinstance(v, dict) else {})} for k, v in rows.items()]
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("match_id") or row.get("id") or "")
        payload = row.get("statistics_raw") or row.get("statistics") or row
        if isinstance(payload, dict):
            payload = payload.get(mid, payload)
        values = payload.get("statistics") if isinstance(payload, dict) else payload
        if not isinstance(values, list):
            continue
        parsed = {}
        for item in values:
            if not isinstance(item, dict):
                continue
            name = str(item.get("type") or "").strip().lower()
            for field, aliases in STAT_ALIASES.items():
                if name in aliases:
                    parsed[field] = {"home": number(item.get("home")), "away": number(item.get("away"))}
        if mid:
            out[mid] = parsed
    return out


def rolling_stats(events, stats, window=5):
    """计算每队历史滚动过程特征；当前场在加入前读取。"""
    history = defaultdict(lambda: defaultdict(lambda: deque(maxlen=window)))
    snapshots = {}
    ordered = sorted(events, key=lambda x: (x["day"], x.get("match_id", "")))
    for e in ordered:
        snap = {"home": {}, "away": {}}
        for side, team in (("home", e["home"]), ("away", e["away"])):
            for field in STAT_ALIASES:
                vals = list(history[team][field])
                snap[side][field] = round(sum(vals) / len(vals), 4) if vals else None
        snapshots[e["match_id"]] = snap
        current = stats.get(e["match_id"], {})
        for side, team in (("home", e["home"]), ("away", e["away"])):
            for field, value in current.items():
                val = value.get(side) if isinstance(value, dict) else None
                if val is not None:
                    history[team][field].append(val)
        # 进球过程也必须只使用过去比赛
        history[e["home"]]["goals_for"].append(e["gh"])
        history[e["home"]]["goals_against"].append(e["ga"])
        history[e["away"]]["goals_for"].append(e["ga"])
        history[e["away"]]["goals_against"].append(e["gh"])
    return snapshots


def fit_goal_model(events, half_life):
    matches = [{"home": e["home"], "away": e["away"], "gh": e["gh"], "ga": e["ga"], "day": e["day"], "league": e.get("league", "")} for e in events]
    if len(matches) < 2:
        return None
    return team_strength.fit_model(matches, half_life=half_life)


def attach_external_features(match, standings=None, lineups=None):
    api = match.get("api_football") or {}
    as_of = api.get("as_of") or {}
    pre_kickoff = bool(as_of.get("usable"))
    mid = str(api.get("match_id") or match.get("apifootball_match_id") or "")

    def keyed(raw):
        if isinstance(raw, dict):
            value = raw.get(mid) or raw.get(str(mid))
            return value if isinstance(value, dict) else raw
        return {}

    def lineup_summary(raw):
        obj = keyed(raw)
        lineup = obj.get("lineup") if isinstance(obj, dict) else {}
        lineup = lineup if isinstance(lineup, dict) else {}
        result = {}
        for side in ("home", "away"):
            side_data = lineup.get(side) or {}
            result[side] = {
                "starting_count": len(side_data.get("starting_lineups") or []),
                "substitute_count": len(side_data.get("substitutes") or []),
                "missing_count": len(side_data.get("missing_players") or []),
                "missing_players": side_data.get("missing_players") or [],
            }
        return result

    feature = {
        "provider": "apifootball.com",
        "as_of": as_of,
        "pre_kickoff_usable": pre_kickoff,
        "statistics": None,
        "standings": None,
        "lineups": None,
        "official_prediction": None,
        "external_market": None,
    }
    # 赛后过程数据保留在原始层，但不能回流当前比赛的赛前特征。
    if api.get("statistics_raw") is not None:
        feature["statistics_status"] = (
            api.get("statistics_status", "MISSING") if pre_kickoff else "POST_MATCH_NOT_USABLE"
        )
    if pre_kickoff and api.get("statistics_raw") is not None:
        feature["statistics"] = {"raw_available": True, "policy": "pregame_only"}

    standings_raw = standings if standings is not None else api.get("standings_raw")
    if standings_raw is not None:
        feature["standings_status"] = "VALID" if pre_kickoff else "POST_MATCH_NOT_USABLE"
        if pre_kickoff:
            feature["standings"] = standings_raw

    lineups_raw = lineups if lineups is not None else api.get("lineups_raw")
    if lineups_raw is not None:
        feature["lineups_status"] = "VALID" if pre_kickoff else "POST_MATCH_NOT_USABLE"
        if pre_kickoff:
            feature["lineups"] = lineup_summary(lineups_raw)

    prediction = api.get("prediction")
    if prediction is not None:
        feature["official_prediction_status"] = "VALID" if pre_kickoff else "POST_MATCH_NOT_USABLE"
        if pre_kickoff:
            feature["official_prediction"] = {
                "prob_home": number(prediction.get("prob_HW")),
                "prob_draw": number(prediction.get("prob_D")),
                "prob_away": number(prediction.get("prob_AW")),
                "source": "apifootball.com get_predictions",
                "not_xg": True,
            }

    market_raw = api.get("external_market_raw")
    if market_raw is not None:
        feature["external_market_status"] = "VALID" if pre_kickoff else "POST_MATCH_NOT_USABLE"
        if pre_kickoff:
            feature["external_market"] = {"bookmaker_rows": len(market_raw) if isinstance(market_raw, list) else None}
    match["api_features"] = feature
    return match


def main():
    ap = argparse.ArgumentParser(description="构建APIfootball赛前滚动特征和可选lambda_prior")
    ap.add_argument("--events", required=True, help="APIfootball get_events原始JSON")
    ap.add_argument("--input", required=True, help="fusion单场或批量输入JSON")
    ap.add_argument("--output", required=True)
    ap.add_argument("--statistics", help="可选统计记录JSON（按match_id挂载）")
    ap.add_argument("--half-life", type=float, default=500.0)
    ap.add_argument("--window", type=int, default=5)
    ap.add_argument("--min-matches", type=int, default=20)
    ap.add_argument("--weight", type=float, default=0.02)
    ap.add_argument("--mode", choices=("keep", "market_only", "hybrid", "model_first"), default="keep")
    args = ap.parse_args()

    raw_events = as_list(read_json(args.events), "events")
    events = [x for x in (event_row(e) for e in raw_events) if x]
    events.sort(key=lambda x: (x["day"], x.get("match_id", "")))
    stats = stats_by_match(read_json(args.statistics)) if args.statistics else {}
    snapshots = rolling_stats(events, stats, args.window)
    model = fit_goal_model(events, args.half_life) if len(events) >= args.min_matches else None

    data = read_json(args.input)
    matches = data.get("matches") if isinstance(data, dict) and isinstance(data.get("matches"), list) else [data]
    injected = 0
    for match in matches:
        target_day = parse_day(match.get("kickoff"))
        eligible = [e for e in events if target_day is not None and e["day"] < target_day]
        local_model = fit_goal_model(eligible, args.half_life) if len(eligible) >= args.min_matches else None
        home, away = str(match.get("home", "")), str(match.get("away", ""))
        feat = {"as_of": match.get("kickoff"), "history_matches": len(eligible), "window": args.window}
        # 只使用目标开球日前历史；球队不在样本中则明确MISSING。
        if local_model and home in local_model["teams"] and away in local_model["teams"]:
            pred = team_strength.predict_match(local_model, home, away, target_day)
            feat["team_strength"] = pred
            if args.mode in ("hybrid", "model_first") and pred.get("status") == "VALID":
                match["lambda_prior"] = {
                    "lambda_home": pred["lambda_home"], "lambda_away": pred["lambda_away"],
                    "weight": args.weight, "source": "apifootball_events_dynamic_dc",
                    "sample_legs": len(eligible), "note": "严格使用kickoff前历史赛果；权重需联赛OOS校准",
                }
                match.setdefault("field_meta", {})["lambda_prior"] = {
                    "status": "VALID",
                    "source": "apifootball_events_dynamic_dc",
                    "observed_at": match.get("kickoff"),
                    "sample_legs": len(eligible),
                    "calibration": "UNFITTED",
                }
                match.setdefault("adjustment_ledger", []).append({
                    "field": "lambda_prior",
                    "fact": "APIfootball历史赛果拟合的时间衰减Dixon-Coles球队λ",
                    "source": "apifootball.com get_events",
                    "mapping_basis": "kickoff前历史赛果，半衰期500天，联赛内拟合",
                    "calibration": "UNFITTED",
                    "system_generated": True,
                    "sample_legs": len(eligible),
                })
                if args.mode == "model_first":
                    match["lambda_home"] = pred["lambda_home"]
                    match["lambda_away"] = pred["lambda_away"]
                match["mode"] = args.mode
                injected += 1
        else:
            feat["team_strength"] = {"status": "UNAVAILABLE", "reason": "历史样本不足或球队不在覆盖"}
        # 目标队在历史赛果中的最后可见滚动过程统计。
        team_snap = {}
        for e in reversed(eligible):
            if e["home"] == home or e["away"] == home:
                team_snap["home_team_history"] = snapshots.get(e["match_id"])
                break
        feat["rolling_statistics"] = team_snap or {"status": "UNAVAILABLE"}
        attach_external_features(match)
        match.setdefault("field_meta", {})["api_features"] = {
            "status": "VALID" if feat.get("team_strength", {}).get("status") == "VALID" else "PARTIAL",
            "as_of": match.get("kickoff"), "history_matches": len(eligible),
            "no_future_leakage": True, "xg_status": "MISSING_UNLESS_EXPLICIT",
            "note": "统计/首发/积分榜仍保留原始分层；未回测不自动改写系数。",
        }
        match["api_features"].update(feat)
        match["api_features"]["no_future_leakage"] = True
    if isinstance(data, dict) and "matches" in data:
        data["matches"] = matches
    else:
        data = matches[0]
    data.setdefault("feature_build", {})["provider"] = "apifootball.com"
    data["feature_build"].update({"events": len(events), "statistics_records": len(stats), "injected_lambda_prior": injected, "mode": args.mode})
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "events": len(events), "statistics_records": len(stats), "injected_lambda_prior": injected, "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
