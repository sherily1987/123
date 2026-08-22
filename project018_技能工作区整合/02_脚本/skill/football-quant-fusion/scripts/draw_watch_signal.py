"""Research-only draw labels derived from existing 1X2 and TTG market inputs."""
from __future__ import annotations

import math
from typing import Any, Iterable


DRAW_MARGIN_PP = 11.5
FOCUS_TTG_UNDER2_MIN = 0.45
TTG_SHADOW_DRAW_K = 1.25


def _odds_vector(ttg: Any) -> list[float] | None:
    if not isinstance(ttg, dict):
        return None
    raw = ttg.get("odds")
    if isinstance(raw, (list, tuple)):
        values = raw
    else:
        try:
            values = [ttg[f"s{index}"] for index in range(8)]
        except KeyError:
            return None
    try:
        odds = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    if len(odds) != 8 or any(not math.isfinite(value) or value <= 1.0 for value in odds):
        return None
    return odds


def ttg_under2_probability(ttg: Any) -> float | None:
    """Return no-vig probability for the official TTG 0/1/2-goal cells only."""
    odds = _odds_vector(ttg)
    if odds is None:
        return None
    implied = [1.0 / value for value in odds]
    return sum(implied[:3]) / sum(implied)


def build_draw_research(final_1x2_pct: Iterable[float] | None, ttg: Any) -> dict:
    """Create an observational draw tier without altering 1X2 probability values."""
    try:
        values = tuple(float(value) for value in (final_1x2_pct or ()))
    except (TypeError, ValueError):
        values = ()
    if len(values) != 3 or any(not math.isfinite(value) or value < 0 for value in values):
        return {
            "research_only": True,
            "action": "unavailable",
            "tier": "none",
            "reason_code": "MISSING_FINAL_1X2",
            "probability_adjustment_applied": False,
            "ttg_under2_probability": None,
        }
    draw_gap_pp = max(values[0], values[2]) - values[1]
    ttg_under2 = ttg_under2_probability(ttg)
    label = {
        "research_policy_version": "draw-watch-research-1.0",
        "research_only": True,
        "action": "observe",
        "tier": "none",
        "reason_code": "DRAW_OUTSIDE_WATCH_MARGIN",
        "draw_probability_pct": values[1],
        "draw_gap_to_leader_pp": draw_gap_pp,
        "watch_margin_pp": DRAW_MARGIN_PP,
        "ttg_under2_probability": ttg_under2,
        "ttg_focus_minimum": FOCUS_TTG_UNDER2_MIN,
        "source_policy": "existing_final_1x2_plus_same_book_ttg_no_vig; not independent evidence",
        "probability_adjustment_applied": False,
    }
    if draw_gap_pp > DRAW_MARGIN_PP:
        return label
    label["tier"] = "watch"
    label["reason_code"] = "DRAW_WITHIN_WATCH_MARGIN"
    if ttg_under2 is not None and ttg_under2 >= FOCUS_TTG_UNDER2_MIN:
        label["tier"] = "focus"
        label["reason_code"] = "DRAW_WITHIN_MARGIN_AND_TTG_UNDER2"
    return label


def build_draw_calibration_shadow(final_1x2_pct: Iterable[float] | None, ttg: Any) -> dict:
    """Return the TTG-conditioned draw-probability candidate as research only.

    This candidate is intentionally not admitted: its historical holdout point
    estimates improved, but paired confidence intervals still cross zero.
    """
    try:
        values = tuple(float(value) for value in (final_1x2_pct or ()))
    except (TypeError, ValueError):
        values = ()
    under2 = ttg_under2_probability(ttg)
    base = {
        "research_only": True,
        "calibration_status": "UNFITTED_SHADOW",
        "admission": "hold",
        "source_policy": "existing_final_1x2_plus_same_book_ttg_no_vig; not independent evidence",
        "ttg_under2_probability": under2,
        "ttg_under2_threshold": FOCUS_TTG_UNDER2_MIN,
        "draw_weight_if_threshold_met": TTG_SHADOW_DRAW_K,
        "production_probability_adjustment_applied": False,
    }
    if len(values) != 3 or any(not math.isfinite(value) or value < 0 for value in values):
        return {**base, "status": "unavailable", "reason_code": "MISSING_FINAL_1X2"}
    if under2 is None:
        return {**base, "status": "unavailable", "reason_code": "MISSING_TTG"}
    draw_weight = TTG_SHADOW_DRAW_K if under2 >= FOCUS_TTG_UNDER2_MIN else 1.0
    weighted = (values[0], values[1] * draw_weight, values[2])
    total = sum(weighted)
    probability = [value * 100.0 / total for value in weighted]
    return {
        **base,
        "status": "ok",
        "reason_code": "TTG_THRESHOLD_MET" if draw_weight > 1.0 else "TTG_THRESHOLD_NOT_MET",
        "shadow_final_1x2_pct": probability,
    }
