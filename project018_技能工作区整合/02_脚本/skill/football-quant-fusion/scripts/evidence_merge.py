"""Merge browser evidence into the shared evidence chain without losing provenance."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any


VALID = {"VALID", "VALID_EMPTY", "PREDICTED", "OK", "AVAILABLE", "FRESH", "AGING", "PROXY_XG", "EXPLICIT_XG"}
FIELDS = ("team_stats", "recent_form", "injury", "suspensions", "starting_xi")
VALID_EVENT_STATUSES = {"VALID", "PREDICTED", "OK", "AVAILABLE", "FRESH", "AGING"}


def _same(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (left.get("status"), left.get("source_id"), left.get("value")) == (
        right.get("status"), right.get("source_id"), right.get("value"))


def _newer(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    """True only when both timestamps parse and candidate is strictly newer."""
    try:
        left = datetime.fromisoformat(str(candidate.get("refreshed_at")).replace("Z", "+00:00"))
        right = datetime.fromisoformat(str(current.get("refreshed_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if left.tzinfo is None or right.tzinfo is None:
        return False
    return left > right


def merge_browser_audit(chain: dict[str, Any] | None, browser_audit: dict[str, Any] | None):
    """Return ``(merged_chain, audit)`` for a browser evidence snapshot.

    A browser field fills an unavailable/partial mobile field.  If both
    sources are usable but disagree, the existing production-side field stays
    primary and the browser field is retained under ``alternatives``.
    """
    merged = deepcopy(chain or {})
    entries = (browser_audit or {}).get("entries") or {}
    audit = {"browser_fields_merged": [], "conflicts": [], "browser_fields_seen": []}
    for name in FIELDS:
        browser = entries.get(name)
        if not isinstance(browser, dict):
            continue
        audit["browser_fields_seen"].append(name)
        current = merged.get(name)
        if not isinstance(current, dict):
            merged[name] = deepcopy(browser)
            audit["browser_fields_merged"].append(name)
            continue
        current_status = str(current.get("status") or "").upper()
        browser_status = str(browser.get("status") or "").upper()
        if current_status not in VALID and browser_status in VALID:
            old = deepcopy(current)
            merged[name] = deepcopy(browser)
            merged[name]["alternatives"] = [old]
            audit["browser_fields_merged"].append(name)
            continue
        # A later API-Sports snapshot is a refreshed observation, not merely a
        # conflicting browser opinion. Promote it while retaining the prior
        # value for audit/replay. Untimestamped legacy conflicts keep the
        # original primary source for backwards compatibility.
        if (browser_status in VALID and browser.get("source_id") == "api-sports.io"
                and _newer(browser, current)):
            old = deepcopy(current)
            merged[name] = deepcopy(browser)
            merged[name]["alternatives"] = [old]
            audit["browser_fields_merged"].append(name)
            continue
        if not _same(current, browser):
            merged[name].setdefault("alternatives", []).append(deepcopy(browser))
            audit["conflicts"].append(name)
    return merged, audit


def merge_late_info_events(chain: dict[str, Any] | None, events: list[dict[str, Any]] | None):
    """Merge pre-kickoff late-info events into an evidence chain.

    Late-info is research-only and may arrive from a different provider than
    the initial preview.  A valid event replaces only a missing/unusable field;
    disagreements are retained as alternatives.  Events observed at or after
    kickoff are ignored to prevent post-match leakage.
    """
    merged = deepcopy(chain or {})
    audit = {"events_seen": 0, "fields_merged": [], "conflicts": [], "ignored_post_kickoff": 0}
    for event in events or []:
        if not isinstance(event, dict):
            continue
        audit["events_seen"] += 1
        gate = event.get("gate") or {}
        minutes = gate.get("minutes_to_kickoff")
        try:
            if minutes is not None and float(minutes) <= 0:
                audit["ignored_post_kickoff"] += 1
                continue
        except (TypeError, ValueError):
            pass
        kind = str(event.get("kind") or "").lower()
        field = {"injury": "injury", "lineup": "starting_xi"}.get(kind)
        if not field:
            continue
        status = str(event.get("status") or "UNAVAILABLE").upper()
        value = event.get("absence") if kind == "injury" else event.get("lineup")
        fixture_id = event.get("api_sports_fixture_id")
        if kind == "injury":
            source_url = f"https://m.sporttery.cn/zqlszl/bssj/?mid={event.get('match_id')}"
        elif fixture_id:
            source_url = f"https://v3.football.api-sports.io/fixtures/lineups?fixture={fixture_id}"
        else:
            source_url = None
        entry = {
            "status": status,
            "value": value,
            "source_id": "sporttery.late_info" if kind == "injury" else "api-sports.io",
            "source_url": source_url,
            "refreshed_at": event.get("collected_at"),
            "event_snapshot": event.get("snapshot"),
        }
        current = merged.get(field)
        current_status = str((current or {}).get("status") or "").upper() if isinstance(current, dict) else ""
        if not isinstance(current, dict) or (current_status not in VALID_EVENT_STATUSES and status in VALID_EVENT_STATUSES):
            if isinstance(current, dict):
                entry["alternatives"] = [deepcopy(current)]
            merged[field] = entry
            audit["fields_merged"].append(field)
        elif not _same(current, entry):
            merged[field].setdefault("alternatives", []).append(deepcopy(entry))
            audit["conflicts"].append(field)
    return merged, audit
