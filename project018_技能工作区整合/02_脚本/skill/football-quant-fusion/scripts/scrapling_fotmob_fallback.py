#!/usr/bin/env python3
"""Conservative parser for Scrapling's dynamic FotMob markdown fallback."""
from __future__ import annotations

import re
from typing import Any


SOURCE_ID = "fotmob.scrapling.dynamic"


def _entry(status: str, value: Any, *, url: str, collected_at: str,
           reason: str | None = None) -> dict[str, Any]:
    return {"status": status, "value": value, "source_id": SOURCE_ID,
            "source_url": url, "refreshed_at": collected_at,
            "missing_reason": reason}


def _slice(text: str, start: str, ends: tuple[str, ...]) -> str:
    pos = text.lower().find(start.lower())
    if pos < 0:
        return ""
    part = text[pos + len(start):]
    stops = [part.lower().find(end.lower()) for end in ends]
    stops = [value for value in stops if value >= 0]
    return part[:min(stops)] if stops else part


def _slice_any(text: str, starts: tuple[str, ...], ends: tuple[str, ...]) -> str:
    positions = [(text.lower().find(start.lower()), start) for start in starts]
    positions = [(pos, start) for pos, start in positions if pos >= 0]
    if not positions:
        return ""
    _, start = min(positions)
    return _slice(text, start, ends)


def _players(section: str) -> list[str]:
    # Markdown links preserve player identity even when the page is rendered
    # dynamically.  Keep first occurrence only; duplicates are common in the
    # accessibility and visual representations of the same card.
    values = re.findall(r"(?:^|\n)(?:\d+)?([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]+)\]\(/players/", section)
    out: list[str] = []
    for value in values:
        name = re.sub(r"\s+", " ", value).strip()
        if name and name not in out:
            out.append(name)
    return out


def _injuries(section: str) -> list[str]:
    linked = re.findall(r"\[([^\]]+)\]\(/players/[^)]+\)\s*\((?:[^)]*injury|[^)]*suspend|[^)]*doubtful)[^)]*\)", section, re.I)
    if linked:
        return list(dict.fromkeys(
            name.strip() for name in linked
            if name.strip() and "http" not in name and "![](" not in name
        ))
    lines = [re.sub(r"\s+", " ", line).strip() for line in section.splitlines()]
    out: list[str] = []
    markers = re.compile(r"injury|injured|doubtful|suspended|day to day", re.I)
    for idx, line in enumerate(lines):
        if not markers.search(line):
            continue
        previous = next((lines[j] for j in range(idx - 1, -1, -1) if lines[j]), "")
        # Do not store the injury reason as a player when the page repeats it.
        if (previous and previous not in out and not markers.search(previous)
                and "http" not in previous and "![](" not in previous):
            out.append(previous.split("/")[0].strip())
    return out


def _form_rows(section: str) -> list[str]:
    rows = []
    for line in section.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if re.search(r"\b\d+\s*-\s*\d+\b", line) and line not in rows:
            rows.append(line)
    return rows[:10]


def parse_markdown(text: str, match: dict[str, Any], source_url: str,
                   collected_at: str) -> dict[str, Any]:
    body = str(text or "")
    lineup_section = _slice(body, "Predicted lineup", ("Team form", "Injuries", "Unavailable"))
    form_section = _slice(body, "Team form", ("Injuries", "Unavailable"))
    injury_section = _slice_any(
        body, ("Injuries", "Unavailable", "Injured and suspended players"),
        ("Team form", "Injuries", "News"),
    )
    players = _players(lineup_section)
    injuries = _injuries(injury_section)
    form_rows = _form_rows(form_section)
    entries = {
        "team_stats": _entry("UNAVAILABLE", None, url=source_url, collected_at=collected_at,
                              reason="SCRAPLING_FOTMOB_PAGE_HAS_NO_STRUCTURED_XG"),
        "recent_form": _entry("VALID" if len(form_rows) >= 5 else "PARTIAL" if form_rows else "UNAVAILABLE",
                              {"raw_rows": form_rows}, url=source_url, collected_at=collected_at,
                              reason=None if form_rows else "TEAM_FORM_SECTION_MISSING"),
        "injury": _entry("VALID" if injuries else "EMPTY_UNCONFIRMED",
                          {"players": injuries}, url=source_url, collected_at=collected_at,
                          reason=None if injuries else "NO_INJURY_ROWS_FOUND"),
        "suspensions": _entry("UNAVAILABLE", None, url=source_url, collected_at=collected_at,
                               reason="SCRAPLING_PAGE_DOES_NOT_SEPARATE_SUSPENSIONS"),
        "starting_xi": _entry("PREDICTED" if players else "UNAVAILABLE",
                               {"players": players, "source": "FotMob predicted lineup"},
                               url=source_url, collected_at=collected_at,
                               reason=None if players else "PREDICTED_LINEUP_SECTION_MISSING"),
    }
    missing = [name for name, entry in entries.items()
               if entry["status"] not in {"VALID", "PREDICTED", "PARTIAL", "OK"}]
    return {
        "schema_version": "scrapling-fotmob-evidence-1.0",
        "provider": "fotmob_via_scrapling_dynamic",
        "research_only": True,
        "match_id": match.get("match_id"),
        "identity": {"home": match.get("home"), "away": match.get("away"),
                     "competition": match.get("competition"), "kickoff": match.get("kickoff")},
        "collected_at": collected_at,
        "source_url": source_url,
        "facts": {"team_form": form_rows, "unavailable": injuries,
                  "lineup": {"source": "FotMob predicted lineup", "players": players}},
        "evidence_audit": {
            "schema_version": "evidence-audit-1.1",
            "critical_fields": ["team_stats", "recent_form", "injury", "suspensions", "starting_xi"],
            "entries": entries,
            "missing_fields": missing,
            "evidence_gap": bool(missing),
            "evidence_status": "GAP" if missing else "OK",
            "evidence_gap_reasons": [f"{name.upper()}_{entries[name]['missing_reason'] or entries[name]['status']}"
                                     for name in missing],
            "source_policy": {"fotmob": "research_only", "sporttery": "production_market_only"},
        },
    }
