#!/usr/bin/env python3
"""Conservative parser for non-FotMob Scrapling Markdown snapshots.

Only explicitly labelled sections are promoted to evidence.  The parser is
source-agnostic, but it never claims that an arbitrary page is official.
"""
from __future__ import annotations

import re
from typing import Any


_VALID = {"VALID", "PREDICTED", "PARTIAL", "OK"}


def _entry(status: str, value: Any, *, url: str, collected_at: str,
           source_id: str, reason: str | None = None) -> dict[str, Any]:
    return {"status": status, "value": value, "source_id": source_id,
            "source_url": url, "refreshed_at": collected_at,
            "missing_reason": reason}


def _sections(text: str) -> dict[str, list[str]]:
    current = ""
    out: dict[str, list[str]] = {}
    for raw in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        heading = re.match(r"^#{1,6}\s+(.+?)\s*#*$", line)
        if heading:
            current = heading.group(1).strip().lower()
            out.setdefault(current, [])
        elif current and line:
            out[current].append(line)
    return out


def _find(sections: dict[str, list[str]], labels: tuple[str, ...]) -> list[str]:
    for title, rows in sections.items():
        if any(label in title for label in labels):
            return rows
    return []


def _form(rows: list[str]) -> list[str]:
    return [row for row in rows
            if re.search(r"\b\d+\s*[-:]\s*\d+\b", row)][:10]


def _clean_rows(rows: list[str]) -> list[str]:
    return [row for row in rows if not re.match(r"^[-*•]\s*$", row)][:30]


def parse_markdown(text: str, match: dict[str, Any], source_url: str,
                   collected_at: str, *, source_id: str, provider: str) -> dict[str, Any]:
    sections = _sections(text)
    form_rows = _form(_find(sections, ("recent form", "team form", "last matches", "recent results")))
    lineup_rows = _clean_rows(_find(sections, ("predicted lineup", "expected lineup", "starting xi", "line-up")))
    injury_rows = _clean_rows(_find(sections, ("injuries", "injury", "unavailable", "absences")))
    suspension_rows = _clean_rows(_find(sections, ("suspensions", "suspended")))
    entries = {
        "team_stats": _entry("UNAVAILABLE", None, url=source_url, collected_at=collected_at,
                              source_id=source_id, reason="GENERIC_PAGE_HAS_NO_STRUCTURED_XG"),
        "recent_form": _entry("VALID" if len(form_rows) >= 5 else "PARTIAL" if form_rows else "UNAVAILABLE",
                              {"raw_rows": form_rows}, url=source_url, collected_at=collected_at,
                              source_id=source_id,
                              reason=None if form_rows else "RECENT_FORM_SECTION_MISSING"),
        "injury": _entry("VALID" if injury_rows else "UNAVAILABLE", {"raw_rows": injury_rows},
                          url=source_url, collected_at=collected_at, source_id=source_id,
                          reason=None if injury_rows else "INJURY_SECTION_MISSING"),
        "suspensions": _entry("VALID" if suspension_rows else "UNAVAILABLE", {"raw_rows": suspension_rows},
                               url=source_url, collected_at=collected_at, source_id=source_id,
                               reason=None if suspension_rows else "SUSPENSION_SECTION_MISSING"),
        "starting_xi": _entry("PREDICTED" if lineup_rows else "UNAVAILABLE", {"raw_rows": lineup_rows},
                               url=source_url, collected_at=collected_at, source_id=source_id,
                               reason=None if lineup_rows else "PREDICTED_LINEUP_SECTION_MISSING"),
    }
    missing = [name for name, entry in entries.items() if entry["status"] not in _VALID]
    return {
        "schema_version": "scrapling-generic-evidence-1.0",
        "provider": provider,
        "research_only": True,
        "match_id": match.get("match_id"),
        "identity": {key: match.get(key) for key in ("home", "away", "competition", "kickoff")},
        "collected_at": collected_at,
        "source_url": source_url,
        "facts": {"recent_form": form_rows, "injuries": injury_rows,
                  "suspensions": suspension_rows, "predicted_lineup": lineup_rows},
        "evidence_audit": {
            "schema_version": "evidence-audit-1.1",
            "critical_fields": ["team_stats", "recent_form", "injury", "suspensions", "starting_xi"],
            "entries": entries,
            "missing_fields": missing,
            "evidence_gap": bool(missing),
            "evidence_status": "GAP" if missing else "OK",
            "evidence_gap_reasons": [f"{name.upper()}_{entries[name]['missing_reason'] or entries[name]['status']}"
                                     for name in missing],
            "source_policy": {"provider": "research_only", "sporttery": "production_market_only"},
        },
    }
