"""Merge browser evidence into the shared evidence chain without losing provenance."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


VALID = {"VALID", "PREDICTED", "OK", "AVAILABLE", "FRESH", "AGING", "PROXY_XG", "EXPLICIT_XG"}
FIELDS = ("team_stats", "recent_form", "injury", "suspensions", "starting_xi")


def _same(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (left.get("status"), left.get("source_id"), left.get("value")) == (
        right.get("status"), right.get("source_id"), right.get("value"))


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
        if not _same(current, browser):
            merged[name].setdefault("alternatives", []).append(deepcopy(browser))
            audit["conflicts"].append(name)
    return merged, audit
