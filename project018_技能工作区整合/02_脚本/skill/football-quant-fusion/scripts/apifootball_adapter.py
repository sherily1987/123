#!/usr/bin/env python3
"""apifootball_adapter — APIfootball.com (apiv3) enrichment & odds adapter.

数据源: https://apiv3.apifootball.com（老牌独立足球数据 API，与 api-sports.io 无关）
认证:   环境变量 API_FOOTBALL_KEY（query 参数 APIkey 发送），key 不写入任何文件。
响应:   JSON 数组（countries/leagues/events/odds）或 {error, message}。

已知限制（2026-08-07 实测，付费会员）:
- get_odds 日期区间最长 5 天（超过返回 error 201 "Date interval is to long!"）。
- 每场 get_odds 返回多家博彩公司（10Bet/bet365/WilliamHill/Marathon/Unibet/Betfair...）。
- 覆盖：55 联赛（欧洲主流+挪超/芬超/瑞超/苏超/土超等，2026/2027 当前赛季）；
  无韩国/巴西（韩职走 api-sports.io，巴西甲走 football-data.org 免费 BSA）。
- apiv3 服务器偶发 SSL 握手超时，本适配器内置重试（指数退避）。

子命令:
  status                    账号套餐信息（get_countries 数量作为可用性探针）
  countries                 可用国家列表
  leagues  [--country]      可用联赛列表（含 league_id / season）
  events   --league / --match-id [--from --to]   赛程/赛果
  standings --league                              积分榜
  statistics --match-id                           单场统计（射门/控球等）
  lineups --match-id                              单场首发/替补/缺阵
  predictions [--league --match-id --from --to]   官方数学预测概率（独立对照）
  odds     --league [--from --to] / --match-id    国际盘赔率（1X2/双胜彩/亚洲盘全档/大小球/BTTS）
  teams    --league                                球队列表（拿 team_key）

用法示例:
  python apifootball_adapter.py status
  python apifootball_adapter.py leagues --output leagues.json
  python apifootball_adapter.py events --league 307 --from 2026-08-02 --to 2026-08-07
  python apifootball_adapter.py odds --league 307 --from 2026-08-02 --to 2026-08-07 --output odds.json
  python apifootball_adapter.py odds --match-id 715561 --output odds.json
  python apifootball_adapter.py teams --league 307 --output teams.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://apiv3.apifootball.com/"
HEAD = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
MAX_ODDS_INTERVAL_DAYS = 5  # get_odds 硬限制


def api_key():
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        sys.exit("缺少环境变量 API_FOOTBALL_KEY（在 https://apifootball.com 后台获取）")
    return key


def get(action, params, retries=4):
    """GET apiv3；apiv3 偶发 SSL 超时，指数退避重试。"""
    qs = {"action": action, "APIkey": api_key(), **params}
    url = BASE + "?" + urllib.parse.urlencode(qs)
    for n in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEAD)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:
            if n == retries - 1:
                raise
            time.sleep(3 * (n + 1))
    raise RuntimeError("apifootball request failed")  # pragma: no cover


def fetch(action, params):
    data = get(action, params)
    if isinstance(data, dict) and data.get("error") is not None:
        raise RuntimeError(f"apifootball error {data.get('error')}: {data.get('message', '')}")
    return data if isinstance(data, list) else []


def fetch_raw(action, params):
    """返回API原始JSON；数组、match_id键控对象和error对象均保留。"""
    data = get(action, params)
    if isinstance(data, dict) and data.get("error") is not None:
        raise RuntimeError(f"apifootball error {data.get('error')}: {data.get('message', '')}")
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
    # get_countries 作为套餐可用性探针（能返回列表即 key 有效）
    try:
        countries = fetch("get_countries", {})
        n = len(countries)
    except RuntimeError as e:
        n = None
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)
    save(a.output, {"countries_count": n}, {
        "plan": "PAID" if n else "UNKNOWN",
        "countries_available": n,
        "note": "apifootball.com 会员；get_countries 数量即套餐覆盖国家数",
    })


def cmd_countries(a):
    data = fetch("get_countries", {})
    rows = [{"country_id": c.get("country_id"), "name": c.get("country_name")} for c in data]
    save(a.output, data, {"count": len(rows)}, rows)


def cmd_leagues(a):
    params = {}
    if a.country:
        params["country_id"] = a.country
    data = fetch("get_leagues", params)
    rows = [{"league_id": l.get("league_id"), "name": l.get("league_name"),
             "country": l.get("country_name"), "season": l.get("league_season")}
            for l in data]
    save(a.output, data, {"count": len(rows)}, rows)


def cmd_events(a):
    params = {}
    if a.league:
        params["league_id"] = a.league
    if a.match_id:
        params["match_id"] = a.match_id
    if a.from_date:
        params["from"] = a.from_date
    if a.to_date:
        params["to"] = a.to_date
    data = fetch("get_events", params)
    rows = [{
        "match_id": e.get("match_id"), "date": e.get("match_date"), "time": e.get("match_time"),
        "status": e.get("match_status"), "league": e.get("league_name"),
        "home": e.get("match_hometeam_name"), "home_id": e.get("match_hometeam_id"),
        "away": e.get("match_awayteam_name"), "away_id": e.get("match_awayteam_id"),
        "score_home": e.get("match_hometeam_score"), "score_away": e.get("match_awayteam_score"),
        "ht_home": e.get("match_hometeam_halftime_score"), "ht_away": e.get("match_awayteam_halftime_score"),
        "et_home": e.get("match_hometeam_extra_score"), "et_away": e.get("match_awayteam_extra_score"),
        "pen_home": e.get("match_hometeam_penalty_score"), "pen_away": e.get("match_awayteam_penalty_score"),
    } for e in data]
    save(a.output, data, {"count": len(rows)}, rows)


def cmd_standings(a):
    data = fetch_raw("get_standings", {"league_id": a.league})
    rows = data if isinstance(data, list) else []
    preview = [{
        "league_id": r.get("league_id"), "team_id": r.get("team_id"),
        "team_name": r.get("team_name"),
        "overall_position": r.get("overall_league_position"),
        "overall_played": r.get("overall_league_payed"),
        "overall_w": r.get("overall_league_W"), "overall_d": r.get("overall_league_D"),
        "overall_l": r.get("overall_league_L"), "overall_gf": r.get("overall_league_GF"),
        "overall_ga": r.get("overall_league_GA"), "overall_pts": r.get("overall_league_PTS"),
        "home_position": r.get("home_league_position"),
        "home_gf": r.get("home_league_GF"), "home_ga": r.get("home_league_GA"),
        "away_position": r.get("away_league_position"),
        "away_gf": r.get("away_league_GF"), "away_ga": r.get("away_league_GA"),
        "league_round": r.get("league_round"), "stage_name": r.get("stage_name"),
    } for r in rows]
    save(a.output, data, {"count": len(rows), "league_id": a.league}, preview)


def cmd_statistics(a):
    data = fetch_raw("get_statistics", {"match_id": a.match_id})
    stats = []
    if isinstance(data, dict):
        obj = data.get(str(a.match_id)) or data.get(a.match_id) or {}
        stats = (obj.get("statistics") or []) if isinstance(obj, dict) else []
    types = sorted({str(x.get("type")) for x in stats if isinstance(x, dict)})
    xg_hits = [x for x in stats if any(k in str(x).lower() for k in ("xg", "expected"))]
    save(a.output, data, {"match_id": a.match_id, "statistics_count": len(stats),
                          "statistics_types": types, "xg_hits": xg_hits}, stats)


def cmd_lineups(a):
    data = fetch_raw("get_lineups", {"match_id": a.match_id})
    obj = {}
    if isinstance(data, dict):
        obj = data.get(str(a.match_id)) or data.get(a.match_id) or {}
    lineup = obj.get("lineup") if isinstance(obj, dict) else {}
    lineup = lineup if isinstance(lineup, dict) else {}
    preview = {}
    for side in ("home", "away"):
        side_data = lineup.get(side) or {}
        preview[side] = {
            "starting_count": len(side_data.get("starting_lineups") or []),
            "substitute_count": len(side_data.get("substitutes") or []),
            "missing_count": len(side_data.get("missing_players") or []),
            "starting_lineups": side_data.get("starting_lineups") or [],
            "missing_players": side_data.get("missing_players") or [],
        }
    save(a.output, data, {"match_id": a.match_id, "lineup": preview})


def cmd_predictions(a):
    params = {}
    for key, value in (("from", a.from_date), ("to", a.to_date),
                       ("country_id", a.country), ("league_id", a.league),
                       ("match_id", a.match_id)):
        if value:
            params[key] = value
    data = fetch_raw("get_predictions", params)
    rows = data if isinstance(data, list) else []
    preview = [{k: r.get(k) for k in (
        "match_id", "match_date", "match_hometeam_name", "match_awayteam_name",
        "prob_HW", "prob_D", "prob_AW", "prob_HW_D", "prob_AW_D",
        "prob_O", "prob_U", "prob_bts", "prob_ots") if k in r} for r in rows]
    save(a.output, data, {"count": len(rows),
                          "note": "官方数学预测概率，仅作p_apifootball外部对照，不是xG"}, preview)


def _input_match_id(match):
    return (match.get("apifootball_match_id") or match.get("api_match_id")
            or (match.get("external_ids") or {}).get("apifootball"))


def _keyed_match(data, match_id):
    if not isinstance(data, dict):
        return {}
    value = data.get(str(match_id)) or data.get(match_id)
    return value if isinstance(value, dict) else {}


def _prediction_for_match(data, match_id):
    if not isinstance(data, list):
        return None
    for row in data:
        if str(row.get("match_id")) == str(match_id):
            return row
    return None


def _safe_fetch_raw(action, params):
    try:
        return fetch_raw(action, params)
    except RuntimeError as exc:
        return {"error": "client", "message": str(exc)}


def _pre_kickoff_status(match, collected_at):
    """判断采集时刻是否早于开球；无法解析时禁止当作赛前数据。"""
    kickoff = str(match.get("kickoff") or "").replace("Z", "+00:00")
    try:
        k = datetime.fromisoformat(kickoff)
        c = datetime.fromisoformat(collected_at)
        if k.tzinfo is None:
            k = k.replace(tzinfo=timezone.utc)
        if c.tzinfo is None:
            c = c.replace(tzinfo=timezone.utc)
        return {"usable": c < k, "kickoff": k.isoformat(), "collected_at": c.isoformat()}
    except (TypeError, ValueError):
        return {"usable": False, "kickoff": kickoff or None, "collected_at": collected_at,
                "reason": "kickoff无法解析"}


def enrich_match(match, include_predictions=True):
    """给单场输入挂载API原始数据；不把未经回测的字段硬写成模型系数。"""
    collected_at = datetime.now(timezone.utc).isoformat()
    mid = _input_match_id(match)
    api = {
        "provider": "apifootball.com",
        "api_version": "v3",
        "collected_at": collected_at,
        "match_id": mid,
        "as_of": _pre_kickoff_status(match, collected_at),
    }
    if not mid:
        api["status"] = "UNAVAILABLE"
        api["reason"] = "缺少apifootball_match_id；拒绝按队名猜测匹配"
        match.setdefault("field_meta", {})["apifootball"] = api
        return match

    stats = _safe_fetch_raw("get_statistics", {"match_id": mid})
    lineups = _safe_fetch_raw("get_lineups", {"match_id": mid})
    odds = _safe_fetch_raw("get_odds", {"match_id": mid})
    api["statistics_raw"] = stats
    api["lineups_raw"] = lineups
    api["external_market_raw"] = odds
    api["statistics_status"] = "VALID" if _keyed_match(stats, mid).get("statistics") is not None else "MISSING"
    api["lineups_status"] = "VALID" if _keyed_match(lineups, mid).get("lineup") is not None else "MISSING"
    api["external_market_status"] = "VALID" if isinstance(odds, list) and odds else "MISSING"

    league_id = match.get("apifootball_league_id") or (match.get("external_ids") or {}).get("apifootball_league")
    if league_id:
        standings = _safe_fetch_raw("get_standings", {"league_id": league_id})
        api["standings_raw"] = standings
        api["standings_status"] = "VALID" if isinstance(standings, list) else "MISSING"
    else:
        api["standings_status"] = "UNAVAILABLE"
        api["standings_reason"] = "缺少apifootball_league_id"

    if include_predictions:
        predictions = _safe_fetch_raw("get_predictions", {"match_id": mid})
        api["predictions_raw"] = predictions
        api["prediction"] = _prediction_for_match(predictions, mid)
        api["predictions_status"] = "VALID" if api["prediction"] else "MISSING"

    match["api_football"] = api
    match.setdefault("source_evidence", []).append("apifootball.com v3")
    match.setdefault("field_meta", {})["apifootball"] = {
        "status": "VALID",
        "provider": "apifootball.com",
        "api_version": "v3",
        "match_id": mid,
        "collected_at": collected_at,
        "statistics": api["statistics_status"],
        "lineups": api["lineups_status"],
        "standings": api["standings_status"],
        "predictions": api.get("predictions_status", "UNAVAILABLE"),
        "external_market": api["external_market_status"],
        "pre_kickoff_usable": api["as_of"]["usable"],
        "statistics_policy": "post_match_training_only",
        "note": "原始API数据已挂载；模型系数需经历史赛前快照回测后启用。",
    }
    return match


def cmd_enrich(a):
    data = json.loads(Path(a.input).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict) and isinstance(data.get("matches"), list):
        data["matches"] = [enrich_match(m, not a.no_predictions) for m in data["matches"]]
        count = len(data["matches"])
    else:
        data = enrich_match(data, not a.no_predictions)
        count = 1
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "count": count, "output": a.output,
                      "note": "API原始数据已落盘，未未经回测直接改变p_model"}, ensure_ascii=False))


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cmd_odds(a):
    params = {}
    if a.league:
        params["league_id"] = a.league
    if a.match_id:
        params["match_id"] = a.match_id
    if a.from_date:
        params["from"] = a.from_date
    if a.to_date:
        params["to"] = a.to_date
    # get_odds 日期区间最长 5 天，超限时前端报错提示
    if a.from_date and a.to_date:
        try:
            from datetime import datetime
            days = (datetime.strptime(a.to_date, "%Y-%m-%d") - datetime.strptime(a.from_date, "%Y-%m-%d")).days
            if days > MAX_ODDS_INTERVAL_DAYS:
                sys.exit(f"get_odds 日期区间最长 {MAX_ODDS_INTERVAL_DAYS} 天（当前 {days} 天），请分段查询")
        except ValueError:
            pass
    data = fetch("get_odds", params)
    rows = []
    for o in data:
        row = {
            "match_id": o.get("match_id"),
            "bookmaker": o.get("odd_bookmakers"),
            "odds_date": o.get("odd_date"),
            "home_win": _float(o.get("odd_1")), "draw": _float(o.get("odd_x")), "away_win": _float(o.get("odd_2")),
            "double_chance": {"1x": _float(o.get("odd_1x")), "12": _float(o.get("odd_12")), "x2": _float(o.get("odd_x2"))},
            "asian_handicap": {},
            "ou": {},
            "btts": {"yes": _float(o.get("bts_yes")), "no": _float(o.get("bts_no"))},
        }
        for k, v in o.items():
            if k.startswith("ah") and v not in ("", None):
                row["asian_handicap"][k] = _float(v)
            elif k.startswith(("o+", "u+")) and v not in ("", None):
                row["ou"][k] = _float(v)
        rows.append(row)
    save(a.output, data, {"count": len(rows)}, rows)


def cmd_teams(a):
    params = {"league_id": a.league} if a.league else {}
    data = fetch("get_teams", params)
    rows = [{"team_key": t.get("team_key"), "name": t.get("team_name"),
             "country": t.get("team_country"), "founded": t.get("team_founded")}
            for t in data]
    save(a.output, data, {"count": len(rows)}, rows)


def main():
    ap = argparse.ArgumentParser(description="APIfootball.com v3 adapter (key: API_FOOTBALL_KEY env)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_output(p):
        p.add_argument("--output", help="写入的 JSON 文件路径")

    p = sub.add_parser("status")
    add_output(p)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("countries")
    add_output(p)
    p.set_defaults(fn=cmd_countries)

    p = sub.add_parser("leagues")
    p.add_argument("--country", help="国家 ID（get_countries 返回的 country_id）")
    add_output(p)
    p.set_defaults(fn=cmd_leagues)

    p = sub.add_parser("events")
    p.add_argument("--league", help="联赛 ID（get_leagues 返回的 league_id）")
    p.add_argument("--match-id", help="单场 match_id")
    p.add_argument("--from", dest="from_date", help="起始日期 YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", help="结束日期 YYYY-MM-DD")
    p.add_argument("--timezone", default="Asia/Shanghai", help="输出时区，默认Asia/Shanghai")
    p.add_argument("--match-live", action="store_true", help="只返回进行中的比赛")
    p.add_argument("--with-player-stats", action="store_true", help="请求球员统计")
    add_output(p)
    p.set_defaults(fn=cmd_events)

    p = sub.add_parser("standings")
    p.add_argument("--league", required=True, help="联赛 ID")
    add_output(p)
    p.set_defaults(fn=cmd_standings)

    p = sub.add_parser("statistics")
    p.add_argument("--match-id", required=True, help="单场 match_id")
    add_output(p)
    p.set_defaults(fn=cmd_statistics)

    p = sub.add_parser("lineups")
    p.add_argument("--match-id", required=True, help="单场 match_id")
    add_output(p)
    p.set_defaults(fn=cmd_lineups)

    p = sub.add_parser("predictions")
    p.add_argument("--country", help="国家 ID")
    p.add_argument("--league", help="联赛 ID")
    p.add_argument("--match-id", help="单场 match_id")
    p.add_argument("--from", dest="from_date", help="起始日期 YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", help="结束日期 YYYY-MM-DD")
    add_output(p)
    p.set_defaults(fn=cmd_predictions)

    p = sub.add_parser("enrich")
    p.add_argument("--input", required=True, help="单场或{matches:[...]}输入JSON")
    p.add_argument("--output", required=True, help="增强后的输入JSON")
    p.add_argument("--no-predictions", action="store_true", help="不请求get_predictions")
    p.set_defaults(fn=cmd_enrich)

    p = sub.add_parser("odds")
    p.add_argument("--league", help="联赛 ID")
    p.add_argument("--match-id", help="单场 match_id")
    p.add_argument("--from", dest="from_date", help="起始日期 YYYY-MM-DD（区间≤5天）")
    p.add_argument("--to", dest="to_date", help="结束日期 YYYY-MM-DD（区间≤5天）")
    add_output(p)
    p.set_defaults(fn=cmd_odds)

    p = sub.add_parser("teams")
    p.add_argument("--league", help="联赛 ID")
    add_output(p)
    p.set_defaults(fn=cmd_teams)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
