#!/usr/bin/env python3
"""Strictly match prediction records to APIFootball settlement candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_name(value: Any) -> str:
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def is_champions_league(value: Any) -> bool:
    normalized = normalize_name(value)
    return "uefachampionsleague" in normalized or "欧冠" in str(value or "")


def _provider_ref(record: dict[str, Any]) -> Any:
    direct = (record.get("provider_refs") or {}).get("apifootball_match_id")
    nested = (((record.get("input") or {}).get("provider_refs") or {})
              .get("apifootball_match_id"))
    return direct if direct is not None else nested


def match_record(
    record: dict[str, Any],
    candidates: list[dict[str, Any]],
    aliases: dict[str, str],
    tolerance_minutes: int = 30,
) -> dict[str, Any]:
    """Match by provider id, otherwise by a unique audited identity tuple."""

    ref = _provider_ref(record)
    if ref is not None:
        exact = [row for row in candidates
                 if str(row.get("provider_match_id")) == str(ref)]
        if len(exact) == 1:
            return {"status": "matched", "matched_by": "provider_match_id",
                    "candidate": exact[0]}
        return {"status": "ambiguous_match" if len(exact) > 1 else "no_match",
                "candidates": len(exact)}

    match = record.get("match") or {}
    home = aliases.get(str(match.get("home")), str(match.get("home") or ""))
    away = aliases.get(str(match.get("away")), str(match.get("away") or ""))
    kickoff = parse_time(match.get("kickoff"))
    eligible: list[dict[str, Any]] = []
    for row in candidates:
        provider_kickoff = parse_time(row.get("kickoff"))
        if kickoff is None or provider_kickoff is None:
            continue
        if not is_champions_league(row.get("competition")):
            continue
        if normalize_name((row.get("home") or {}).get("name")) != normalize_name(home):
            continue
        if normalize_name((row.get("away") or {}).get("name")) != normalize_name(away):
            continue
        if abs((provider_kickoff - kickoff).total_seconds()) > tolerance_minutes * 60:
            continue
        eligible.append(row)

    if len(eligible) == 1:
        return {"status": "matched", "matched_by": "identity_unique",
                "candidate": eligible[0]}
    return {"status": "ambiguous_match" if len(eligible) > 1 else "no_match",
            "candidates": len(eligible)}
