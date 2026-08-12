#!/usr/bin/env python3
"""Normalize APIFootball results without guessing 90-minute scores."""

from __future__ import annotations

from typing import Any


SCORE_FIELDS = (
    "match_hometeam_score",
    "match_awayteam_score",
    "match_hometeam_halftime_score",
    "match_awayteam_halftime_score",
    "match_hometeam_extra_score",
    "match_awayteam_extra_score",
    "match_hometeam_penalty_score",
    "match_awayteam_penalty_score",
)


def _int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _pair(event: dict[str, Any], home_key: str, away_key: str) -> dict[str, int] | None:
    home, away = _int(event.get(home_key)), _int(event.get(away_key))
    return {"home": home, "away": away} if home is not None and away is not None else None


def normalize_event(event: dict[str, Any], collected_at: str) -> dict[str, Any]:
    """Return an auditable settlement candidate.

    APIFootball does not reliably expose the 90-minute boundary when extra
    time or penalties are present, so those matches deliberately remain
    unresolved instead of deriving a score from the final total.
    """

    final = _pair(event, "match_hometeam_score", "match_awayteam_score")
    extra = _pair(event, "match_hometeam_extra_score", "match_awayteam_extra_score")
    penalties = _pair(event, "match_hometeam_penalty_score", "match_awayteam_penalty_score")
    finished = str(event.get("match_status", "")).strip().lower() == "finished"

    if not finished:
        score_90, state = None, "not_finished"
    elif final is None:
        score_90, state = None, "invalid_score"
    elif penalties is not None:
        score_90, state = None, "ambiguous_penalties"
    elif extra is not None:
        score_90, state = None, "ambiguous_extra_time"
    else:
        score_90, state = final, "verified"

    return {
        "schema": "apifootball-settlement-candidate-1.0",
        "provider": "apifootball.com",
        "provider_match_id": _int(event.get("match_id")),
        "provider_league_id": _int(event.get("league_id")),
        "competition": event.get("league_name"),
        "kickoff": f"{event.get('match_date')}T{event.get('match_time') or '00:00'}:00+08:00",
        "home": {
            "id": _int(event.get("match_hometeam_id")),
            "name": event.get("match_hometeam_name"),
        },
        "away": {
            "id": _int(event.get("match_awayteam_id")),
            "name": event.get("match_awayteam_name"),
        },
        "status": "finished" if finished else "not_finished",
        "score_90": score_90,
        "score_extra_time": extra,
        "score_penalties": penalties,
        "score_90_status": state,
        "raw_score_fields": {key: event.get(key) for key in SCORE_FIELDS},
        "collected_at": collected_at,
    }
