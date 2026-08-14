#!/usr/bin/env python3
"""Download api-sports.io (API-Football v3) event + shot-statistics history
into the same prematch-safe training schema used by apifootball.com /
football-data.co.uk adapters, so it plugs directly into build_league_xg.py /
run_full_backtest.py without any downstream changes.

与 apifootball.com 是两个不同供应商（不要混用/合并）：本源没有历史赔率
（沙职历史赛季 odds coverage 全为 false，实测过，不是漏查），provider_market
仍需另外接体彩历史数据或跳过——本脚本只负责 events + match_stats。

用法：
  python download_api_football_history.py --league-id 307 --slug saudi_pro_league \
      --seasons 2021 2022 2023 2024 2025 \
      --project <project021路径>
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("api_football_adapter", HERE / "api_football_adapter.py")
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(adapter)

STAT_MAP = {
    "Shots on Goal": "shots_on_goal",
    "Shots off Goal": "shots_off_goal",
    "Total Shots": "shots_total",
    "Blocked Shots": "shots_blocked",
    "Shots insidebox": "shots_inside_box",
    "Shots outsidebox": "shots_outside_box",
    "Corner Kicks": "corners",
    "Ball Possession": "possession_pct",
}


def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.rstrip("%").strip()
        if value == "":
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_with_retry(path: str, params: dict, retries: int = 3, delay: float = 2.0) -> dict:
    """网络/SSL 瞬时故障重试——2026-08-13 实测保加利亚甲拉到一半因 SSL EOF 崩溃过，
    单次故障不该丢掉已缓存的进度，重跑脚本本身能续传，但这里加重试减少中断次数。"""
    last_error = None
    for attempt in range(retries + 1):
        try:
            return adapter.get(path, params)
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay * (attempt + 1))
    raise last_error


def fetch_season_fixtures(league_id: int, season: int, cache_dir: Path, refresh: bool) -> list[dict]:
    cache = cache_dir / f"fixtures_{league_id}_{season}.json"
    if cache.exists() and not refresh:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        payload = _get_with_retry("/fixtures", {"league": league_id, "season": season, "timezone": "Asia/Shanghai"})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload.get("response", [])


def fetch_fixture_statistics(fixture_id: int, cache_dir: Path, refresh: bool) -> list[dict] | None:
    cache = cache_dir / f"stats_{fixture_id}.json"
    if cache.exists() and not refresh:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        payload = _get_with_retry("/fixtures/statistics", {"fixture": fixture_id})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    resp = payload.get("response") or []
    return resp if len(resp) == 2 else None


# 淘汰赛制赛事打进加时/点球时 status.short 是 "AET"/"PEN"，不是 "FT"；联赛赛制没有
# 加时，不受影响。2026-08-13 实测世界杯决赛（阿根廷点球淘汰法国）status="PEN"。
FINISHED_STATUS_CODES = {"FT", "AET", "PEN"}


def normalize_event(f: dict, collected_at: str) -> dict | None:
    fx, lg, teams = f["fixture"], f["league"], f["teams"]
    if fx.get("status", {}).get("short") not in FINISHED_STATUS_CODES:
        return None
    # goals.home/away 在打了加时/点球的比赛里是加时/点球战后的最终比分（实测阿根廷vs
    # 法国 goals=3:3，是90分钟2-2+加时1-1的合计）；score.fulltime 才是体彩结算口径要的
    # 90分钟比分。普通比赛两者相等，用 fulltime 不影响。
    fulltime = (f.get("score") or {}).get("fulltime") or {}
    home, away = fulltime.get("home"), fulltime.get("away")
    if home is None or away is None:
        home, away = (f.get("goals") or {}).get("home"), (f.get("goals") or {}).get("away")
    if home is None or away is None:
        return None
    return {
        "provider": "api-sports.io", "source_type": "event_result", "match_id": fx["id"],
        "league_id": lg.get("id"), "league_name": lg.get("name"), "season": lg.get("season"),
        "kickoff": fx.get("date", "").replace("+08:00", "").split("+")[0],
        "home_id": teams["home"].get("id"), "home": teams["home"].get("name"),
        "away_id": teams["away"].get("id"), "away": teams["away"].get("name"),
        "actual": [home, away], "status": "Finished", "collected_at": collected_at,
        "settlement_basis": "90min_fulltime_score", "raw_status": fx.get("status", {}).get("short"),
        "field_availability": {"statistics": "POST_MATCH", "lineup": "UNKNOWN", "player_statistics": "UNKNOWN"},
    }


def normalize_stats(fixture_id: int, league_id: int, kickoff: str, home_id: int, away_id: int,
                     raw: list[dict], collected_at: str) -> dict:
    by_team = {block["team"]["id"]: {STAT_MAP[s["type"]]: _num(s["value"])
                                      for s in block["statistics"] if s["type"] in STAT_MAP}
               for block in raw}
    h, a = by_team.get(home_id, {}), by_team.get(away_id, {})

    def pair(key: str) -> list[float | None]:
        return [h.get(key), a.get(key)]

    inside, outside = pair("shots_inside_box"), pair("shots_outside_box")
    on_goal, total = pair("shots_on_goal"), pair("shots_total")
    split_available = all(v is not None for v in inside + outside)
    xg_usable = split_available or all(v is not None for v in on_goal + total)
    return {
        "provider": "api-sports.io", "source_type": "match_statistics", "match_id": fixture_id,
        "league_id": league_id, "kickoff": kickoff, "collected_at": collected_at, "data_class": "POST_MATCH",
        "shots_total": total, "shots_on_goal": on_goal, "shots_off_goal": pair("shots_off_goal"),
        "shots_blocked": pair("shots_blocked"), "shots_inside_box": inside, "shots_outside_box": outside,
        "corners": pair("corners"), "possession_pct": pair("possession_pct"),
        "split_available": split_available, "consistent": None, "xg_usable": xg_usable,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league-id", type=int, required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seasons", type=int, nargs="+", required=True)
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--max-requests", type=int, default=7000, help="本次运行请求预算，留余量给当日其它调用")
    a = ap.parse_args()

    norm = a.project / "04_素材" / "标准化"
    norm.mkdir(parents=True, exist_ok=True)
    raw_dir = a.project / "04_素材" / "api_football_raw" / a.slug
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    requests_made = 0
    events, stats = [], []

    for season in a.seasons:
        fixtures = fetch_season_fixtures(a.league_id, season, raw_dir, a.refresh)
        requests_made += 1
        finished = [normalize_event(f, now) for f in fixtures]
        finished = [e for e in finished if e]
        events.extend(finished)
        print(f"season {season}: {len(finished)} finished fixtures", flush=True)
        for e in finished:
            if requests_made >= a.max_requests:
                print(f"达到本次请求预算 {a.max_requests}，剩余场次下次 --refresh 之外重跑即可自动续传（已缓存的不会重取）", flush=True)
                break
            raw = fetch_fixture_statistics(e["match_id"], raw_dir, a.refresh)
            requests_made += 1
            if raw is None:
                continue
            stats.append(normalize_stats(e["match_id"], e["league_id"], e["kickoff"],
                                          e["home_id"], e["away_id"], raw, now))
        else:
            continue
        break

    # 按 match_id 与已有文件合并，而不是整份覆盖——否则只传部分赛季重跑一次，
    # 会把之前已经拉到的其它赛季数据静默冲掉（2026-08-12 实测踩过一次）。
    ev_path = norm / f"{a.slug}_events.jsonl"
    st_path = norm / f"{a.slug}_match_stats.jsonl"

    def merge(path: Path, new_rows: list[dict]) -> list[dict]:
        by_id: dict[int, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    by_id[row["match_id"]] = row
        for row in new_rows:
            by_id[row["match_id"]] = row
        return [by_id[k] for k in sorted(by_id)]

    merged_events = merge(ev_path, events)
    merged_stats = merge(st_path, stats)
    ev_path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in merged_events), encoding="utf-8")
    st_path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in merged_stats), encoding="utf-8")
    result = {"status": "ok", "league_id": a.league_id, "slug": a.slug, "seasons": a.seasons,
              "events_this_run": len(events), "stats_this_run": len(stats),
              "events_total": len(merged_events), "stats_total": len(merged_stats),
              "requests_made": requests_made,
              "events_output": str(ev_path), "stats_output": str(st_path)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
