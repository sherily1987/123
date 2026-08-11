#!/usr/bin/env python3
"""Build an auditable Sporttery historical snapshot dataset.

Input: fetch_sporttery_history.py / sporttery_big5_cups_2026.json output.
For each match, keep opening (first valid), T-24h, T-6h, T-1h (latest snapshot
at or before those cutoffs), and closing (latest valid snapshot strictly before
kickoff). No future snapshot is used to fill an earlier target.
"""
from __future__ import annotations
import argparse, json, math
from datetime import datetime, timezone, timedelta
from pathlib import Path

CN_TZ = timezone(timedelta(hours=8))
POOLS = {"hadList": "HAD", "hhadList": "HHAD", "ttgList": "TTG", "crsList": "CRS", "hafuList": "HAFU"}


# [中文功能] 解析多种时间格式为datetime
def parse_dt(value, date_value=None):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if date_value and "T" not in text and " " not in text and len(text) <= 12:
        text = f"{date_value} {text}"
    text = text.replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T")):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt.replace(tzinfo=CN_TZ) if dt.tzinfo is None else dt
        except ValueError:
            pass
    return None


# [中文功能] 从输入提取开球时间
def kickoff(m):
    for value in (m.get("kickoff_iso"), m.get("kickoff")):
        dt = parse_dt(value)
        if dt:
            return dt
    return parse_dt(m.get("matchTime"), m.get("matchDate"))


# [中文功能] 校验HAD盘口行是否有效
def valid_had(row):
    if not isinstance(row, dict):
        return False
    try:
        return all(math.isfinite(float(row[k])) and float(row[k]) > 1 for k in ("h", "d", "a"))
    except (KeyError, TypeError, ValueError):
        return False


# [中文功能] 取盘口行的更新时间
def row_dt(row):
    return parse_dt(row.get("updateDate") + " " + str(row.get("updateTime") or "00:00:00")) if isinstance(row, dict) and row.get("updateDate") else None


# [中文功能] 从有效行提取三项赔率
def odds3(row):
    if not valid_had(row):
        return None
    return [float(row[k]) for k in ("h", "d", "a")]


# [中文功能] 把比分字符串转成(主,客)整数
def parse_score(value):
    text = str(value or "").strip().replace("：", ":").replace("-", ":")
    bits = text.split(":")
    if len(bits) != 2:
        return None
    try:
        h, a = int(bits[0]), int(bits[1])
        return [h, a] if h >= 0 and a >= 0 else None
    except (TypeError, ValueError):
        return None


# [中文功能] 为单场抽取指定时刻附近的盘口快照
def snapshot_for(rows, target=None, strict_before=False):
    parsed = []
    for row in rows or []:
        dt = row_dt(row)
        odds = odds3(row)
        if dt and odds:
            parsed.append((dt, row, odds))
    parsed.sort(key=lambda x: x[0])
    if not parsed:
        return None
    if target is None:
        dt, row, odds = parsed[0]
    else:
        eligible = [x for x in parsed if (x[0] < target if strict_before else x[0] <= target)]
        if not eligible:
            return None
        dt, row, odds = eligible[-1]
    return {"observed_at": dt.isoformat(), "odds": odds,
            "raw": {k: row.get(k) for k in ("h", "d", "a", "updateDate", "updateTime", "hf", "df", "af")}}


# [中文功能] 把原始采集行组装成训练样本
def build_match(m):
    ko = kickoff(m)
    history = m.get("odds_history") or {}
    had_rows = history.get("hadList") or []
    opening = snapshot_for(had_rows)
    t24 = snapshot_for(had_rows, ko - timedelta(hours=24)) if ko else None
    t6 = snapshot_for(had_rows, ko - timedelta(hours=6)) if ko else None
    t1 = snapshot_for(had_rows, ko - timedelta(hours=1)) if ko else None
    closing = snapshot_for(had_rows, ko, strict_before=True) if ko else None
    score = m.get("sections_no999") or m.get("sectionsNo999")
    score_90 = parse_score(score)
    return {
        "schema_version": "sporttery-snapshots-1.1",
        "match_id": f"sporttery-{m.get('matchId')}" if m.get("matchId") not in (None, "") else None,
        "sporttery_match_id": m.get("matchId"),
        "match_num": m.get("matchNumStr") or m.get("matchNum"),
        "home": m.get("homeTeamAllName") or m.get("homeTeamAbbName") or m.get("home"),
        "away": m.get("awayTeamAllName") or m.get("awayTeamAbbName") or m.get("away"),
        "competition": m.get("leagueAllName") or m.get("leagueAbbName") or m.get("league"),
        "league_id": m.get("leagueId"),
        "kickoff": ko.isoformat() if ko else None,
        "score_90_raw": score,
        "score_90": score_90,
        "result_1x2": None if score_90 is None else ("H" if score_90[0] > score_90[1] else ("D" if score_90[0] == score_90[1] else "A")),
        "total_goals": None if score_90 is None else sum(score_90),
        "over25": None if score_90 is None else sum(score_90) > 2,
        "btts": None if score_90 is None else score_90[0] > 0 and score_90[1] > 0,
        "snapshots": {"opening": opening, "t_minus_24h": t24, "t_minus_6h": t6, "t_minus_1h": t1, "closing": closing},
        "snapshot_available": {"opening": bool(opening), "t_minus_24h": bool(t24), "t_minus_6h": bool(t6), "t_minus_1h": bool(t1), "closing": bool(closing)},
        "history_counts": {k: len(history.get(k) or []) for k in POOLS},
        "source": "中国体彩官方移动端 oddsHistory / getFixedBonusV1",
        "notes": [
            "T-24h/T-6h/T-1h取目标时点之前最后一条，不用未来赔率填补",
            "closing取严格早于开球时间的最后一条HAD",
            "score_90_raw来自sectionsNo999，需由清洗器解析并核验90分钟口径"
        ]
    }


# [中文功能] 生成体彩快照数据集（JSONL）
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True, help="JSONL output")
    ap.add_argument("--report", required=True)
    args = ap.parse_args()
    src = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    matches = src.get("matches") or []
    rows = [build_match(m) for m in matches]
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output).open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    fields = ["opening", "t_minus_24h", "t_minus_6h", "t_minus_1h", "closing"]
    legacy4 = ["opening", "t_minus_24h", "t_minus_6h", "closing"]
    report = {
        "schema_version": "sporttery-snapshots-report-1.1",
        "source": args.input,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matches": len(rows),
        "with_match_id": sum(r.get("sporttery_match_id") not in (None, "") for r in rows),
        "with_kickoff": sum(bool(r.get("kickoff")) for r in rows),
        "with_score_raw": sum(bool(r.get("score_90_raw")) for r in rows),
        "with_had_history": sum(bool(r["history_counts"].get("hadList")) for r in rows),
        "snapshot_coverage": {k: sum(r["snapshot_available"].get(k, False) for r in rows) for k in fields},
        "complete_four_snapshot": sum(all(r["snapshot_available"].get(k, False) for k in legacy4) for r in rows),
        "complete_five_snapshot": sum(all(r["snapshot_available"].get(k, False) for k in fields) for r in rows),
        "definition": {
            "opening": "first valid HAD history row",
            "t_minus_24h": "latest row <= kickoff-24h",
            "t_minus_6h": "latest row <= kickoff-6h",
            "t_minus_1h": "latest row <= kickoff-1h",
            "closing": "latest row < kickoff",
        },
        "outputs": {"jsonl": args.output, "report": args.report}
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
