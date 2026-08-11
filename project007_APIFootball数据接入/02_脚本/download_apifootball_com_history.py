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
                     timezone_name: str = "Asia/Shanghai") -> dict:
    raw_dir = project / "04_素材" / "apifootball_com_raw" / slug
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows, failures, months_reused, months_downloaded = [], [], [], []
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
                    payload = adapter.request("get_events", {
                        "league_id": league_id, "from": str(lo), "to": str(hi), "timezone": timezone_name,
                    })
                    collected = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    raw = {"provider": "apifootball.com", "collected_at": collected,
                           "params": {"league_id": league_id, "from": str(lo), "to": str(hi), "timezone": timezone_name},
                           "response": payload}
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
        rows.extend(x for x in (normalize_event(e, collected_at) for e in adapter._result(payload)) if x)
        if delay_seconds and month in months_downloaded:
            time.sleep(delay_seconds)
    out = project / "04_素材" / "标准化" / f"{slug}_events.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(deduplicate(rows), key=lambda x: (x["kickoff"], x["match_id"]))
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    return {"rows": rows, "failures": failures, "months_reused": months_reused,
            "months_downloaded": months_downloaded, "output": str(out)}


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
    a = ap.parse_args()
    report = download_history(a.league_id, date.fromisoformat(a.from_date), date.fromisoformat(a.to_date),
                              Path(a.project), a.slug, a.refresh, a.retries, a.delay_seconds, a.timezone)
    print(json.dumps({"status": "partial" if report["failures"] else "ok", "count": len(report["rows"]),
                      "output": report["output"], "months_reused": report["months_reused"],
                      "months_downloaded": report["months_downloaded"], "failures": report["failures"]}, ensure_ascii=False))
    if report["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
