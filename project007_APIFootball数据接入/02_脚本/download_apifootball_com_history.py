#!/usr/bin/env python3
"""Download apifootball.com event history into a prematch-safe training schema."""
from __future__ import annotations

import argparse
import importlib.util
import json
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


def normalize_event(event: dict[str, Any], collected_at: str) -> dict[str, Any] | None:
    home, away = _int(event.get("match_hometeam_score")), _int(event.get("match_awayteam_score"))
    if event.get("match_status") != "Finished" or home is None or away is None:
        return None
    return {
        "provider": "apifootball.com", "source_type": "event_result", "match_id": _int(event.get("match_id")),
        "league_id": _int(event.get("league_id")), "league_name": event.get("league_name"),
        "season": event.get("league_year") or event.get("league_season"),
        "kickoff": f"{event.get('match_date')}T{event.get('match_time') or '00:00'}:00",
        "home_id": _int(event.get("match_hometeam_id")), "home": event.get("match_hometeam_name"),
        "away_id": _int(event.get("match_awayteam_id")), "away": event.get("match_awayteam_name"),
        "actual": [home, away], "status": "Finished", "collected_at": collected_at,
        "field_availability": {"statistics": "POST_MATCH", "lineup": "POST_MATCH", "player_statistics": "POST_MATCH"},
    }


def deduplicate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for row in rows:
        key = (row.get("provider"), row.get("match_id"))
        if key in seen or key[1] is None:
            continue
        seen.add(key); out.append(row)
    return out


def months(start: date, end: date):
    current = start.replace(day=1)
    while current <= end:
        next_month = date(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1)
        yield max(start, current), min(end, next_month.fromordinal(next_month.toordinal() - 1))
        current = next_month


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league-id", type=int, required=True); ap.add_argument("--slug", required=True)
    ap.add_argument("--project", required=True); ap.add_argument("--from-date", required=True); ap.add_argument("--to-date", required=True)
    ap.add_argument("--timezone", default="Asia/Shanghai")
    a = ap.parse_args(); project = Path(a.project); start = date.fromisoformat(a.from_date); end = date.fromisoformat(a.to_date)
    raw_dir = project / "04_素材" / "apifootball_com_raw" / a.slug; raw_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for lo, hi in months(start, end):
        collected = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = adapter.request("get_events", {"league_id": a.league_id, "from": str(lo), "to": str(hi), "timezone": a.timezone})
        raw = {"provider": "apifootball.com", "collected_at": collected, "params": {"league_id": a.league_id, "from": str(lo), "to": str(hi), "timezone": a.timezone}, "response": payload}
        (raw_dir / f"{lo:%Y-%m}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.extend(x for x in (normalize_event(e, collected) for e in adapter._result(payload)) if x)
    out = project / "04_素材" / "标准化" / f"{a.slug}_events.jsonl"; out.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(deduplicate(rows), key=lambda x: (x["kickoff"], x["match_id"]))
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    print(json.dumps({"status": "ok", "count": len(rows), "output": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
