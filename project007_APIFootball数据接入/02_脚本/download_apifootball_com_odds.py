#!/usr/bin/env python3
"""Download APIFootball odds once per event date and attach prematch consensus."""
from __future__ import annotations

import importlib.util
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("apifootball_com_adapter", HERE / "apifootball_com_adapter.py")
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(adapter)
BERLIN = ZoneInfo("Europe/Berlin")
TIMESTAMP_BASIS = "provider_undocumented_assumed_europe_berlin"


def _cached(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload.get("response") if isinstance(payload, dict) and "response" in payload else payload


def _redact_error(exc: Exception) -> str:
    return re.sub(r"(?i)(apikey=)[^&\s]+", r"\1[REDACTED]", str(exc))


def _moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BERLIN)


def _fair(odds: list[float]) -> list[float] | None:
    if len(odds) != 3 or any(x is None or x <= 1 for x in odds):
        return None
    inverse = [1 / x for x in odds]
    total = sum(inverse)
    return [x / total for x in inverse]


def download_odds_for_dates(dates: set[date], project: Path, refresh: bool = False,
                            retries: int = 2, delay_seconds: float = 0.7) -> dict:
    raw_dir = project / "04_素材" / "apifootball_com_odds_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows, failures, reused, downloaded = [], [], [], []
    for day in sorted(dates):
        path = raw_dir / f"{day:%Y-%m-%d}.json"
        payload = None if refresh else _cached(path) if path.exists() else None
        if payload is not None:
            reused.append(str(day))
        else:
            last_error = None
            for attempt in range(retries + 1):
                try:
                    payload = adapter.request("get_odds", {"from": str(day), "to": str(day)})
                    path.write_text(json.dumps({"provider": "apifootball.com", "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "params": {"from": str(day), "to": str(day)}, "response": payload}, ensure_ascii=False), encoding="utf-8")
                    downloaded.append(str(day))
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < retries and delay_seconds:
                        time.sleep(delay_seconds * (attempt + 1))
            if payload is None:
                failures.append({"date": str(day), "error_type": type(last_error).__name__, "error": _redact_error(last_error)})
                continue
        rows.extend(adapter.normalize_odds(payload))
        if delay_seconds and str(day) in downloaded:
            time.sleep(delay_seconds)
    return {"rows": rows, "failures": failures, "dates_reused": reused, "dates_downloaded": downloaded}


def attach_provider_market(events: list[dict], odds_rows: list[dict]) -> tuple[list[dict], dict]:
    by_match: dict[int, list[dict]] = {}
    for row in odds_rows:
        if row.get("match_id") is not None:
            by_match.setdefault(int(row["match_id"]), []).append(row)
    audit = {"event_count": len(events), "matched_events": 0, "unmatched_events": 0, "rejected_after_kickoff": 0, "rejected_invalid_odds": 0, "rejected_unparseable_time": 0}
    enriched = []
    for event in events:
        item = dict(event)
        kickoff = _moment(event.get("kickoff"))
        selected: dict[str, tuple[datetime, list[float], dict]] = {}
        for quote in by_match.get(event.get("match_id"), []):
            observed, fair = _moment(quote.get("observed_at")), _fair(quote.get("odds_1x2", []))
            if fair is None:
                audit["rejected_invalid_odds"] += 1
                continue
            if kickoff is None or observed is None:
                audit["rejected_unparseable_time"] += 1
                continue
            if observed >= kickoff:
                audit["rejected_after_kickoff"] += 1
                continue
            book = quote.get("bookmaker") or "unknown"
            if book not in selected or observed > selected[book][0]:
                selected[book] = (observed, fair, quote)
        if not selected:
            item["provider_market_1x2"] = None
            item["provider_market_meta"] = {"provider": "apifootball.com", "provider_only": True, "sporttery_compatible": False, "timestamp_basis": TIMESTAMP_BASIS, "selection_rule": "no_valid_pre_kickoff_quote"}
            audit["unmatched_events"] += 1
        else:
            vectors = [x[1] for x in selected.values()]
            consensus = [median([v[i] for v in vectors]) for i in range(3)]
            total = sum(consensus)
            item["provider_market_1x2"] = [round(x / total, 8) for x in consensus]
            item["provider_market_meta"] = {"provider": "apifootball.com", "provider_only": True, "sporttery_compatible": False, "timestamp_basis": TIMESTAMP_BASIS, "selection_rule": "latest_pre_kickoff_per_bookmaker_then_component_median", "bookmakers": sorted(selected), "bookmaker_count": len(selected), "selected_observed_at": {book: value[0].isoformat() for book, value in selected.items()}}
            audit["matched_events"] += 1
        enriched.append(item)
    return enriched, audit
