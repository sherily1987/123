#!/usr/bin/env python3
"""Download apifootball.com event history into a prematch-safe training schema."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("apifootball_com_adapter", HERE / "apifootball_com_adapter.py")
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(adapter)


def _int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


# 淘汰赛制赛事（世界杯/欧冠/欧联等）打进加时/点球时 match_status 不是 "Finished"，
# 是 "After Extra Time"/"After Pen." 这类值——2026-08-13 实测世界杯决赛（阿根廷点球
# 淘汰法国）因此被 normalize_event 整场丢弃。联赛赛制没有加时，不受影响。
FINISHED_STATUSES = {"Finished", "After Extra Time", "After Pen."}


def normalize_event(event: dict[str, Any], collected_at: str) -> dict[str, Any] | None:
    # ft_score 才是体彩结算口径要的 90 分钟比分；match_hometeam_score 在打了加时/点球的
    # 比赛里是加时/点球战后的最终比分（2026-08-13 实测：阿根廷vs法国 score=4:3 点球战后，
    # ft_score=2:2 才是90分钟战平的真实比分）。普通比赛两个字段相等，用 ft_score 不影响。
    home = _int(event.get("match_hometeam_ft_score"))
    away = _int(event.get("match_awayteam_ft_score"))
    if home is None or away is None:
        home, away = _int(event.get("match_hometeam_score")), _int(event.get("match_awayteam_score"))
    if event.get("match_status") not in FINISHED_STATUSES or home is None or away is None:
        return None
    return {
        "provider": "apifootball.com", "source_type": "event_result", "match_id": _int(event.get("match_id")),
        "league_id": _int(event.get("league_id")), "league_name": event.get("league_name"),
        "season": event.get("league_year") or event.get("league_season"),
        "kickoff": f"{event.get('match_date')}T{event.get('match_time') or '00:00'}:00",
        "home_id": _int(event.get("match_hometeam_id")), "home": event.get("match_hometeam_name"),
        "away_id": _int(event.get("match_awayteam_id")), "away": event.get("match_awayteam_name"),
        "actual": [home, away], "status": "Finished", "collected_at": collected_at,
        "settlement_basis": "90min_ft_score", "raw_status": event.get("match_status"),
        "field_availability": {"statistics": "POST_MATCH", "lineup": "POST_MATCH", "player_statistics": "POST_MATCH"},
    }


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def stat_map(statistics: list[dict[str, Any]] | None) -> dict[str, tuple[float | None, float | None]]:
    """把 statistics 数组折成 {type: (home, away)}，**取首次出现**。

    供应商会重复输出同一个 type，且重复项是 0（实测 `Attacks 96:137` 后面跟
    `Attacks 0:0`）。用字典推导会取到最后一条也就是 0，必须首次出现优先。
    """
    out: dict[str, tuple[float | None, float | None]] = {}
    for item in statistics or []:
        key = item.get("type")
        if not key or key in out:
            continue
        out[key] = (_num(item.get("home")), _num(item.get("away")))
    return out


SHOT_FIELDS = {
    "shots_total": "Shots Total", "shots_on_goal": "Shots On Goal",
    "shots_off_goal": "Shots Off Goal", "shots_blocked": "Shots Blocked",
    "shots_inside_box": "Shots Inside Box", "shots_outside_box": "Shots Outside Box",
    "corners": "Corners", "possession_pct": "Ball Possession",
}


def penalties_of(players: Any) -> tuple[int, int]:
    """从球员统计汇总（判罚次数, 打进次数）。

    点球只占禁区内射门约 1.8%，却贡献约 11% 的进球（转化率 79%），
    会系统性抬高代理 xG 的禁区内系数，故单独抽出以便剔除。
    """
    scored = missed = 0
    for p in players or []:
        if not isinstance(p, dict):
            continue
        for key, target in (("player_pen_score", "s"), ("player_pen_miss", "m")):
            try:
                value = int(p.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if target == "s":
                scored += value
            else:
                missed += value
    return scored + missed, scored


def normalize_statistics(event: dict[str, Any], collected_at: str) -> dict[str, Any] | None:
    """抽出球队级统计。赛后事实，必须与赛前训练集分文件存放。"""
    stats = stat_map(event.get("statistics"))
    if not stats or "Shots Total" not in stats:
        return None
    row: dict[str, Any] = {
        "provider": "apifootball.com", "source_type": "match_statistics",
        "match_id": _int(event.get("match_id")), "league_id": _int(event.get("league_id")),
        "kickoff": f"{event.get('match_date')}T{event.get('match_time') or '00:00'}:00",
        "collected_at": collected_at, "data_class": "POST_MATCH",
    }
    for field, key in SHOT_FIELDS.items():
        home, away = stats.get(key, (None, None))
        row[field] = [home, away]
    total, inside, outside = row["shots_total"], row["shots_inside_box"], row["shots_outside_box"]
    # 两种坏数据要分开记：切分整个缺失（实测有场次只有主队的 inside/outside）
    # 与切分存在但加不回总数。前者只是不能用于 xG，后者说明供应商数据自相矛盾。
    ps = event.get("player_stats")
    if isinstance(ps, dict):
        taken_h, scored_h = penalties_of(ps.get("home"))
        taken_a, scored_a = penalties_of(ps.get("away"))
        row["penalties_taken"] = [taken_h, taken_a]
        row["penalties_scored"] = [scored_h, scored_a]
    else:
        row["penalties_taken"] = row["penalties_scored"] = [None, None]
    row["split_available"] = all(v is not None for v in (*total, *inside, *outside))
    row["consistent"] = row["split_available"] and all(
        abs(i + o - t) < 1e-6 for t, i, o in zip(total, inside, outside))
    row["xg_usable"] = row["split_available"] and row["consistent"]
    return row


def deduplicate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for row in rows:
        key = (row.get("provider"), row.get("match_id"))
        if key in seen or key[1] is None:
            continue
        seen.add(key)
        out.append(row)
    return out


def months(start: date, end: date):
    current = start.replace(day=1)
    while current <= end:
        next_month = date(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1)
        yield max(start, current), min(end, next_month.fromordinal(next_month.toordinal() - 1))
        current = next_month


def _redact_error(exc: Exception) -> str:
    return re.sub(r"(?i)(apikey=)[^&\s]+", r"\1[REDACTED]", str(exc))


def _cached_response(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload.get("response") if isinstance(payload, dict) and "response" in payload else payload


def download_history(league_id: int, start: date, end: date, project: Path, slug: str,
                     refresh: bool = False, retries: int = 2, delay_seconds: float = 0.7,
                     timezone_name: str = "Asia/Shanghai", with_player_stats: bool = False) -> dict:
    # 带 withPlayerStats 的响应含赛后统计，与不带 flag 的既有缓存分目录存放，
    # 否则旧缓存会被误当作"含统计"复用（实测旧缓存里没有 statistics 字段）。
    raw_dir = project / "04_素材" / ("apifootball_com_raw_stats" if with_player_stats else "apifootball_com_raw") / slug
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows, failures, months_reused, months_downloaded = [], [], [], []
    stat_rows: list[dict[str, Any]] = []
    stats_missing = 0
    for lo, hi in months(start, end):
        month = f"{lo:%Y-%m}"
        path = raw_dir / f"{month}.json"
        payload = None if refresh else _cached_response(path) if path.exists() else None
        if payload is not None:
            months_reused.append(month)
        else:
            last_error = None
            for attempt in range(retries + 1):
                try:
                    params = {"league_id": league_id, "from": str(lo), "to": str(hi), "timezone": timezone_name}
                    if with_player_stats:
                        params["withPlayerStats"] = 1
                    payload = adapter.request("get_events", params)
                    collected = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    raw = {"provider": "apifootball.com", "collected_at": collected,
                           "params": params, "response": payload}
                    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
                    months_downloaded.append(month)
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < retries and delay_seconds:
                        time.sleep(delay_seconds * (attempt + 1))
            if payload is None:
                failures.append({"month": month, "error_type": type(last_error).__name__, "error": _redact_error(last_error)})
                continue
        collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        events = adapter._result(payload)
        rows.extend(x for x in (normalize_event(e, collected_at) for e in events) if x)
        if with_player_stats:
            for e in events:
                if normalize_event(e, collected_at) is None:
                    continue  # 未完赛的场次不统计缺失
                stat = normalize_statistics(e, collected_at)
                if stat is None:
                    stats_missing += 1
                else:
                    stat_rows.append(stat)
        if delay_seconds and month in months_downloaded:
            time.sleep(delay_seconds)
    out = project / "04_素材" / "标准化" / f"{slug}_events.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(deduplicate(rows), key=lambda x: (x["kickoff"], x["match_id"]))
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    report = {"rows": rows, "failures": failures, "months_reused": months_reused,
              "months_downloaded": months_downloaded, "output": str(out)}
    if with_player_stats:
        stat_rows = sorted(deduplicate(stat_rows), key=lambda x: (x["kickoff"], x["match_id"]))
        stats_out = project / "04_素材" / "标准化" / f"{slug}_match_stats.jsonl"
        stats_out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in stat_rows), encoding="utf-8")
        finished = len(rows)
        usable = sum(1 for x in stat_rows if x["xg_usable"])
        report["statistics"] = {
            "output": str(stats_out), "count": len(stat_rows), "missing": stats_missing,
            "partial_split": sum(1 for x in stat_rows if not x["split_available"]),
            "inconsistent": sum(1 for x in stat_rows if x["split_available"] and not x["consistent"]),
            "xg_usable": usable,
            "coverage_pct": round(usable / finished * 100, 2) if finished else None,
        }
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league-id", type=int, required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--timezone", default="Asia/Shanghai")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--delay-seconds", type=float, default=0.7)
    ap.add_argument("--with-player-stats", action="store_true",
                    help="同时抓取球队级赛后统计，写入 <slug>_match_stats.jsonl（原始响应另存目录）")
    a = ap.parse_args()
    report = download_history(a.league_id, date.fromisoformat(a.from_date), date.fromisoformat(a.to_date),
                              Path(a.project), a.slug, a.refresh, a.retries, a.delay_seconds, a.timezone,
                              a.with_player_stats)
    print(json.dumps({"status": "partial" if report["failures"] else "ok", "count": len(report["rows"]),
                      "output": report["output"], "months_reused": report["months_reused"],
                      "months_downloaded": report["months_downloaded"], "failures": report["failures"],
                      **({"statistics": report["statistics"]} if "statistics" in report else {})}, ensure_ascii=False))
    if report["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
