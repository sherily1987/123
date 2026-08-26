#!/usr/bin/env python3
"""Settle immutable prematch direction policies independently of model metrics."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from backtest_dual_track import validate_90min_settlement


DIRECTIONS = frozenset({"H", "D", "A"})
SCOREABLE_CLASSIFICATIONS = frozenset({"PRIMARY_ONLY", "PRIMARY_WITH_COVER"})
REGISTRATION_STATUSES = frozenset({"REGISTERED", "NOT_REGISTERED", "UNAVAILABLE"})


def _aware_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _score_direction(score: Any) -> str | None:
    if isinstance(score, dict):
        home, away = score.get("home"), score.get("away")
    elif isinstance(score, (list, tuple)) and len(score) == 2:
        home, away = score
    else:
        return None
    if (isinstance(home, bool) or isinstance(away, bool)
            or not isinstance(home, int) or not isinstance(away, int)
            or home < 0 or away < 0):
        return None
    return "H" if home > away else ("D" if home == away else "A")


def is_verified_official_90min_result(value: Any) -> bool:
    """Return whether a payload satisfies the shared formal result boundary."""
    if not isinstance(value, dict):
        return False
    if any(value.get(field) not in (None, "", False) for field in (
            "score_et", "score_extra_time", "penalty_winner", "score_penalties")):
        return False
    if ("score_90_status" in value
            and value.get("score_90_status") != "verified"):
        return False
    return bool(validate_90min_settlement(value).get("eligible"))


def _official_direction(value: Any) -> str | None:
    """Return a verified 90-minute H/D/A result, never a full-match outcome."""
    if not is_verified_official_90min_result(value):
        return None
    return _score_direction(value.get("score_90"))


def _empty_settlement(status: str, official_result: str | None) -> dict[str, Any]:
    return {
        "primary_hit": None,
        "alternative_hit": None,
        "direction_policy_hit": None,
        "official_result": official_result,
        "settlement_status": status,
    }


def settle_direction_policy(
    policy: Any,
    official_result: Any,
    *,
    registration_status: str | None = None,
    kickoff: str | None = None,
) -> dict[str, Any]:
    """Settle only a registered, valid prematch policy against official 90 minutes.

    Result objects must satisfy the repository's formal official 90-minute
    settlement contract.  Bare directions and offline scores are never formal
    evidence and therefore never enter direction denominators.
    """
    official = _official_direction(official_result)
    if registration_status is None:
        if policy is None:
            registration_status = "NOT_REGISTERED"
        elif isinstance(policy, dict) and (
                policy.get("status") == "UNAVAILABLE"
                or policy.get("classification") == "UNAVAILABLE"):
            registration_status = "UNAVAILABLE"
        else:
            registration_status = "REGISTERED"
    if registration_status not in REGISTRATION_STATUSES:
        registration_status = "UNAVAILABLE"
    if registration_status != "REGISTERED":
        return _empty_settlement(registration_status, official)
    if not isinstance(policy, dict) or policy.get("status") != "AVAILABLE":
        return _empty_settlement("UNAVAILABLE", official)

    prediction_as_of = _aware_time(policy.get("prediction_as_of"))
    kickoff_at = _aware_time(kickoff)
    if (prediction_as_of is None or kickoff_at is None
            or prediction_as_of >= kickoff_at):
        return _empty_settlement("UNAVAILABLE", official)

    classification = policy.get("classification")
    if classification == "UNCLEAR":
        return _empty_settlement("UNCLEAR", official)
    if classification not in SCOREABLE_CLASSIFICATIONS:
        return _empty_settlement("UNAVAILABLE", official)
    primary = policy.get("primary_direction")
    alternative = policy.get("alternative_direction")
    if primary not in DIRECTIONS:
        return _empty_settlement("UNAVAILABLE", official)
    if classification == "PRIMARY_ONLY":
        if alternative is not None:
            return _empty_settlement("UNAVAILABLE", official)
    elif alternative not in DIRECTIONS or alternative == primary:
        return _empty_settlement("UNAVAILABLE", official)
    if official is None:
        return _empty_settlement("UNSETTLED", None)

    primary_hit = primary == official
    alternative_hit = alternative == official if classification == "PRIMARY_WITH_COVER" else None
    return {
        "primary_hit": primary_hit,
        "alternative_hit": alternative_hit,
        "direction_policy_hit": primary_hit or bool(alternative_hit),
        "official_result": official,
        "settlement_status": "SETTLED",
    }


def _hit_metric(settlements: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [row.get(field) for row in settlements if isinstance(row.get(field), bool)]
    hits = sum(values)
    return {"hits": hits, "n": len(values), "rate": hits / len(values) if values else None}


def summarize_direction_policy_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate policy counts and three deliberately independent hit rates."""
    registration_counts: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    settlements = []
    for row in rows:
        registration = str(row.get("direction_policy_status") or "NOT_REGISTERED")
        if registration not in REGISTRATION_STATUSES:
            registration = "UNAVAILABLE"
        registration_counts[registration] += 1
        policy = row.get("direction_policy")
        if registration == "NOT_REGISTERED":
            classification = "NOT_REGISTERED"
        elif registration == "UNAVAILABLE":
            classification = "UNAVAILABLE"
        else:
            classification = (policy or {}).get("classification")
            if classification not in SCOREABLE_CLASSIFICATIONS | {"UNCLEAR"}:
                classification = "UNAVAILABLE"
        classification_counts[classification] += 1
        settlement = row.get("direction_settlement")
        if isinstance(settlement, dict) and settlement.get("settlement_status") == "SETTLED":
            settlements.append(settlement)
    return {
        "registration_status_counts": dict(sorted(registration_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "primary_hit": _hit_metric(settlements, "primary_hit"),
        "alternative_hit": _hit_metric(settlements, "alternative_hit"),
        "direction_policy_hit": _hit_metric(settlements, "direction_policy_hit"),
        "denominator_isolation": {
            "top1_1x2_unchanged": True,
            "brier_ece_unchanged": True,
            "ev_kelly_unchanged": True,
            "coverage_is_not_primary_correctness": True,
        },
    }
