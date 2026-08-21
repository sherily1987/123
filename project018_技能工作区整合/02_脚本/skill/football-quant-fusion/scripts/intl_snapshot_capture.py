#!/usr/bin/env python3
"""按开球倒计时采集国际赔率研究快照。

T-24h、T-6h、T-75m 只是国际盘口/CLV 研究节点。体彩仍是唯一生产盘口，
本脚本不读取或写入生产概率、模型版本或推荐门控。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from odds_api_adapter import OddsApiAdapter, load_api_key, load_config


SLOTS = (("T-24h", 24 * 60), ("T-6h", 6 * 60), ("T-75m", 75))


def parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def match_id(match: dict) -> str:
    meta = match.get("sporttery_meta") or match.get("team_ids") or {}
    raw = meta.get("match_id") or match.get("match_id") or "?"
    return raw if str(raw).startswith("sporttery-") else f"sporttery-{raw}"


def build_plan(raw: dict, now: datetime, window_minutes: int = 15) -> dict:
    """构造到点场次；边界外和无时区时间都不会触发网络请求。"""
    due, invalid, outside = [], 0, 0
    for match in raw.get("matches", []):
        kickoff = parse_time(match.get("kickoff") or match.get("kickoff_iso"))
        if kickoff is None:
            invalid += 1
            continue
        minutes_to_kickoff = (kickoff - now).total_seconds() / 60.0
        labels = [label for label, target in SLOTS
                  if abs(minutes_to_kickoff - target) <= window_minutes]
        if not labels:
            outside += 1
            continue
        for label in labels:
            due.append({
                "match_id": match_id(match), "capture_label": label,
                "kickoff": kickoff.isoformat(), "league": match.get("league") or match.get("competition") or "",
                "minutes_to_kickoff": round(minutes_to_kickoff, 1), "match": match,
            })
    return {
        "schema": "intl-odds-capture-plan-1.0",
        "research_only": True,
        "planned_at": now.isoformat(),
        "window_minutes": window_minutes,
        "status": "READY" if due else "NO_DUE_MATCHES",
        "due_matches": due,
        "invalid_kickoff_count": invalid,
        "outside_window_count": outside,
    }


def capture(plan: dict, config: dict, store: Path, dry_run: bool) -> list[dict]:
    """按槽位调用既有适配器；无到点场次时显式不请求。"""
    if not plan["due_matches"]:
        return []
    if config.get("provider", "the-odds-api") != "the-odds-api":
        # 当前编排器按 The Odds API 的 sport key 做批量请求；不能把另一个 provider
        # 误当兼容接口。显式跳过比静默换 key/消耗额度安全。
        return [{"status": "skipped", "reason": "unsupported_provider_for_scheduled_capture"}]
    adapter = OddsApiAdapter(config, load_api_key())
    reports = []
    for label, _minutes in SLOTS:
        group = [row["match"] for row in plan["due_matches"] if row["capture_label"] == label]
        if not group:
            continue
        keys = sorted({adapter.sport_key_for_league(m.get("league") or m.get("competition") or "")
                       for m in group} - {None})
        if not keys:
            reports.append({"capture_label": label, "status": "skipped",
                            "reason": "no_configured_sport_key", "match_count": len(group)})
            continue
        reports.append(adapter.run(None, None, store, keys, adapter.default_markets, dry_run,
                                   capture_label=label, matches_override=group))
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description="国际赔率 T-24/T-6/T-75 研究快照")
    parser.add_argument("--match-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--now", help="仅用于可复现计划；ISO8601 且必须带时区")
    parser.add_argument("--window-minutes", type=int, default=15)
    parser.add_argument("--dry-run", action="store_true", help="仅生成计划，不请求 API、不写赔率库")
    args = parser.parse_args()
    if args.window_minutes < 0:
        raise SystemExit("--window-minutes must be non-negative")
    raw = json.loads(args.match_file.read_text(encoding="utf-8"))
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        raise SystemExit("--now must be ISO8601 with timezone")
    plan = build_plan(raw, now, args.window_minutes)
    plan["capture_reports"] = capture(plan, load_config(args.config), args.store, args.dry_run)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
