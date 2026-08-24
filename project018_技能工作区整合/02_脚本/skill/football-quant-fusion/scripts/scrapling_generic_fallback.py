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
           source_id: str, source_tier: str = "C",
           reason: str | None = None) -> dict[str, Any]:
    return {"status": status, "value": value, "source_id": source_id,
            "source_tier": source_tier,
            "source_url": url, "refreshed_at": collected_at,
            "missing_reason": reason}


def _sections(text: str) -> dict[str, list[str]]:
    current = ""
    out: dict[str, list[str]] = {}
    lines = str(text or "").splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        line = re.sub(r"\s+", " ", raw).strip()
        heading = re.match(r"^#{1,6}\s+(.+?)\s*#*$", line)
        # Scrapling's Markdown output for some editorial sites uses Setext
        # headings ("Team News" followed by dashes) instead of ATX headings.
        if (not heading and index + 1 < len(lines) and line and
                re.match(r"^\s*[-=]{3,}\s*$", lines[index + 1])):
            heading = re.match(r"^(.+?)$", line)
            index += 1
        # Predicted-XI labels are often emitted as a bold paragraph rather
        # than a heading.  Treat only a label-only line as a section boundary.
        if not heading:
            bold = re.match(r"^\*\*(.+?)\*\*\s*:?\s*$", line)
            if bold:
                heading = bold
        # A few preview templates emit plain colon-terminated labels such as
        # "Bologna pre-season form:" without Markdown heading syntax.
        if not heading and re.search(r"(?:form|team news|squad news)\s*:\s*$", line,
                                     re.IGNORECASE):
            heading = re.match(r"^(.+?)$", line)
        if heading:
            current = heading.group(1).strip().lower()
            out.setdefault(current, [])
        elif current and line:
            out[current].append(line)
        index += 1
    return out


def _find(sections: dict[str, list[str]], labels: tuple[str, ...]) -> list[str]:
    # Prefer an exact/leading section title over a broad substring match.  An
    # article title such as "Preview: ... prediction, team news, lineups"
    # otherwise shadows the actual ``Team News`` section below it.
    for label in labels:
        needle = label.lower()
        for title, rows in sections.items():
            if title == needle or title.startswith(needle):
                return rows
    for title, rows in sections.items():
        if any(label in title for label in labels):
            return rows
    return []


def _form(rows: list[str]) -> list[str]:
    score_rows = [row for row in rows
                  if re.search(r"\b\d+\s*[-:：]\s*\d+\b", row)]
    if score_rows:
        return score_rows[:10]
    # Some previews expose only W/D/L form markers.  They are still explicit
    # recent-form evidence when collected under a labelled form section.
    return [row for row in rows
            if re.fullmatch(r"[*•\-\s]*(?:W|D|L)(?:\s|[✅❌➖])*", row,
                            re.IGNORECASE)
            ] [:10]


def _clean_rows(rows: list[str]) -> list[str]:
    return [row for row in rows if not re.match(r"^[-*•]\s*$", row)][:30]


def parse_markdown(text: str, match: dict[str, Any], source_url: str,
                   collected_at: str, *, source_id: str, provider: str,
                   source_tier: str = "C") -> dict[str, Any]:
    sections = _sections(text)
    form_rows = _form(_find(sections, ("recent form", "team form", "pre-season form", "form (all competitions)", "form",
                                        "last matches", "recent results",
                                        "近期状态", "近期战绩", "近况", "最近比赛", "近5场", "近十场")))
    lineup_rows = _clean_rows(_find(sections, ("predicted lineup", "expected lineup", "starting lineup", "starting xi", "line-up",
                                                "预计首发", "预测首发", "首发阵容", "首发")))
    injury_rows = _clean_rows(_find(sections, ("injuries", "injury", "unavailable", "absences",
                                                "伤停", "伤病", "缺阵", "伤缺")))
    if not injury_rows:
        # Sports previews commonly put explicit fitness doubts under a
        # broader Team News heading.  Keep only lines with an absence cue;
        # unrelated transfers/news are not promoted to injury evidence.
        team_news = _find(sections, ("team news", "squad news"))
        injury_rows = _clean_rows([row for row in team_news if re.search(
            r"(?:injur|fitness|doubt|missing|absent|unavailable|sidelined|could be missing|伤|缺阵|停赛|伤停)",
            row, re.IGNORECASE)])
    suspension_rows = _clean_rows(_find(sections, ("suspensions", "suspended", "停赛", "禁赛")))
    team_stats_rows = _clean_rows(_find(sections, ("xg", "expected goals", "attack strength", "defence strength",
                                                   "进攻强度", "防守强度", "预期进球", "球队统计", "数据统计")))
    media_prediction = str(provider).lower() in {"discovered_media_preview", "media_preview"} or source_tier == "B"
    injury_status = "PREDICTED" if media_prediction and injury_rows else "VALID" if injury_rows else "UNAVAILABLE"
    suspension_status = "PREDICTED" if media_prediction and suspension_rows else "VALID" if suspension_rows else "UNAVAILABLE"
    entries = {
        "team_stats": _entry("VALID" if team_stats_rows else "UNAVAILABLE",
                              {"raw_rows": team_stats_rows}, url=source_url, collected_at=collected_at,
                              source_id=source_id, source_tier=source_tier,
                              reason=None if team_stats_rows else "GENERIC_PAGE_HAS_NO_EXPLICIT_XG_OR_STRENGTH"),
        "recent_form": _entry("VALID" if len(form_rows) >= 5 else "PARTIAL" if form_rows else "UNAVAILABLE",
                              {"raw_rows": form_rows}, url=source_url, collected_at=collected_at,
                              source_id=source_id, source_tier=source_tier,
                              reason=None if form_rows else "RECENT_FORM_SECTION_MISSING"),
        "injury": _entry(injury_status, {"raw_rows": injury_rows},
                          url=source_url, collected_at=collected_at, source_id=source_id, source_tier=source_tier,
                          reason=None if injury_rows else "INJURY_SECTION_MISSING"),
        "suspensions": _entry(suspension_status, {"raw_rows": suspension_rows},
                               url=source_url, collected_at=collected_at, source_id=source_id, source_tier=source_tier,
                               reason=None if suspension_rows else "SUSPENSION_SECTION_MISSING"),
        "starting_xi": _entry("PREDICTED" if lineup_rows else "UNAVAILABLE", {"raw_rows": lineup_rows},
                               url=source_url, collected_at=collected_at, source_id=source_id, source_tier=source_tier,
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
        "facts": {"team_stats": team_stats_rows, "recent_form": form_rows, "injuries": injury_rows,
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
