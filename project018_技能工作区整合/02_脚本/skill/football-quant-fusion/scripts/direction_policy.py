#!/usr/bin/env python3
"""Build immutable, versioned prematch direction-policy decisions.

This module deliberately labels directions from an already-produced 1X2
probability vector.  It never recalibrates, rescales, registers, settles, or
uses the decision as a recommendation input.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
POLICY_FILE = HERE.parent / "config" / "direction_policy.json"
POLICY_IMPLEMENTATION_FILE = Path(__file__).resolve()
DIRECTIONS = ("H", "D", "A")
SUM_TOLERANCE_PP = 0.5
REQUIRED_POLICY_FIELDS = (
    "schema_version",
    "rule_version",
    "primary_only_min_gap_pp",
    "cover_min_gap_pp",
    "cover_max_gap_pp",
    "alternative_min_probability",
    "draw_tie_band_pp",
    "unclear_max_gap_pp",
)


def canonical_json(value: Any) -> str:
    """Return the stable JSON form used for an auditable policy signature."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def policy_signature_components(policy: dict[str, Any]) -> dict[str, str]:
    """Return the complete, non-runtime inputs to a policy signature."""
    return {
        "policy_canonical_sha256": hashlib.sha256(
            canonical_json(policy).encode("utf-8")
        ).hexdigest(),
        "implementation_sha256": hashlib.sha256(
            POLICY_IMPLEMENTATION_FILE.read_bytes()
        ).hexdigest(),
    }


def canonical_policy_signature(policy: dict[str, Any]) -> str:
    """Hash the actual policy values and the governing implementation bytes."""
    return hashlib.sha256(
        canonical_json(policy_signature_components(policy)).encode("utf-8")
    ).hexdigest()


def load_policy(path: Path | None = None) -> dict[str, Any]:
    """Load the versioned decision policy without silently supplying defaults."""
    source = Path(path) if path is not None else POLICY_FILE
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"direction policy cannot be read: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError("direction policy must be a JSON object")
    validate_policy(payload)
    return payload


def validate_policy(policy: dict[str, Any]) -> None:
    """Reject incomplete or internally inconsistent policy configurations."""
    if not isinstance(policy, dict):
        raise ValueError("policy must be an object")
    for field in REQUIRED_POLICY_FIELDS:
        if field not in policy:
            raise ValueError(f"policy missing {field}")
    for field in ("schema_version", "rule_version"):
        value = policy[field]
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError(f"policy {field} must be a non-empty string")
    numeric_fields = REQUIRED_POLICY_FIELDS[2:]
    for field in numeric_fields:
        value = policy[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"policy {field} must be finite")
    if not (0.0 <= float(policy["unclear_max_gap_pp"])
            <= float(policy["cover_min_gap_pp"])
            <= float(policy["cover_max_gap_pp"])
            <= float(policy["primary_only_min_gap_pp"])):
        raise ValueError("policy gap thresholds are inconsistent")
    if not 0.0 <= float(policy["alternative_min_probability"]) <= 1.0:
        raise ValueError("policy alternative_min_probability must be in [0, 1]")
    if float(policy["draw_tie_band_pp"]) < 0.0:
        raise ValueError("policy draw_tie_band_pp must be non-negative")


def _aware_time(value: Any) -> str | None:
    if isinstance(value, datetime):
        parsed = value
        rendered = value.isoformat()
    elif isinstance(value, str) and value.strip():
        rendered = value.strip()
        try:
            parsed = datetime.fromisoformat(rendered.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return rendered


def _valid_identity(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    model_version = value.get("model_version")
    probability_signature = value.get("probability_signature")
    if (not isinstance(model_version, str) or not model_version.strip()
            or model_version != model_version.strip()):
        return None
    if (not isinstance(probability_signature, str) or len(probability_signature) != 64
            or any(character not in "0123456789abcdef" for character in probability_signature.lower())):
        return None
    return model_version, probability_signature


def _raw_probability_mapping(probabilities: Any) -> dict[str, Any] | None:
    if not isinstance(probabilities, (list, tuple)) or len(probabilities) != 3:
        return None
    return dict(zip(DIRECTIONS, probabilities))


def _probability_values(probabilities: Any) -> tuple[list[float], str] | None:
    raw = _raw_probability_mapping(probabilities)
    if raw is None:
        return None
    values = list(raw.values())
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value < 0.0 for value in values):
        return None
    numbers = [float(value) for value in values]
    if all(value <= 1.0 for value in numbers):
        if abs(sum(numbers) - 1.0) <= SUM_TOLERANCE_PP / 100.0:
            return numbers, "fraction"
        return None
    if all(value <= 100.0 for value in numbers):
        if abs(sum(numbers) - 100.0) <= SUM_TOLERANCE_PP:
            return numbers, "percent"
    return None


def _unavailable(*, policy: Any, probabilities: Any, prediction_as_of: Any,
                 model_identity: Any, reason: str) -> dict[str, Any]:
    raw_probabilities = _raw_probability_mapping(probabilities)
    rule_version = policy.get("rule_version") if isinstance(policy, dict) else None
    schema_version = policy.get("schema_version") if isinstance(policy, dict) else None
    signature = None
    signature_components = None
    if isinstance(policy, dict):
        try:
            signature_components = policy_signature_components(policy)
            signature = canonical_policy_signature(policy)
        except (TypeError, ValueError):
            signature = None
    identity = _valid_identity(model_identity)
    return {
        "schema_version": schema_version,
        "rule_version": rule_version,
        "policy_version": rule_version,
        "status": "UNAVAILABLE",
        "classification": "UNAVAILABLE",
        "primary_direction": None,
        "alternative_direction": None,
        "probabilities": raw_probabilities,
        "probability_unit": None,
        "probability_source": "final_1x2_pct",
        "trigger": None,
        "gap_pp": None,
        "prediction_as_of": _aware_time(prediction_as_of),
        "model_version": identity[0] if identity else None,
        "probability_signature": identity[1] if identity else None,
        "decision_policy_signature": signature,
        "decision_policy_signature_components": signature_components,
        "reason": reason,
    }


def build_direction_policy(probabilities: Any, *, prediction_as_of: Any,
                           model_identity: dict[str, Any], policy: dict[str, Any],
                           probability_source: str = "final_1x2_pct") -> dict[str, Any]:
    """Classify one valid prematch H/D/A probability snapshot.

    Input probabilities may be fractions or percentages.  Their source values
    are stored unchanged; only an internal percentage view is used to compare
    the policy thresholds.
    """
    try:
        validate_policy(policy)
    except ValueError:
        return _unavailable(policy=policy, probabilities=probabilities,
                            prediction_as_of=prediction_as_of,
                            model_identity=model_identity, reason="policy_invalid")
    if not isinstance(probability_source, str) or not probability_source.strip():
        return _unavailable(policy=policy, probabilities=probabilities,
                            prediction_as_of=prediction_as_of,
                            model_identity=model_identity, reason="probability_source_invalid")
    time_value = _aware_time(prediction_as_of)
    if time_value is None:
        return _unavailable(policy=policy, probabilities=probabilities,
                            prediction_as_of=prediction_as_of,
                            model_identity=model_identity,
                            reason="prediction_as_of_must_be_timezone_aware")
    identity = _valid_identity(model_identity)
    if identity is None:
        return _unavailable(policy=policy, probabilities=probabilities,
                            prediction_as_of=prediction_as_of,
                            model_identity=model_identity, reason="model_identity_invalid")
    parsed = _probability_values(probabilities)
    if parsed is None:
        return _unavailable(policy=policy, probabilities=probabilities,
                            prediction_as_of=prediction_as_of,
                            model_identity=model_identity,
                            reason="probabilities_must_sum_to_100")
    values, unit = parsed
    values_pp = [value * 100.0 if unit == "fraction" else value for value in values]
    order = sorted(range(3), key=lambda index: (-values_pp[index], index))
    primary_index, runner_up_index = order[:2]
    primary_margin_pp = values_pp[primary_index] - values_pp[runner_up_index]
    primary_direction: str | None = None
    alternative_direction: str | None = None
    classification = "UNCLEAR"
    selected_alternative_index = runner_up_index

    if primary_margin_pp < float(policy["unclear_max_gap_pp"]):
        classification = "UNCLEAR"
    elif primary_margin_pp >= float(policy["primary_only_min_gap_pp"]):
        classification = "PRIMARY_ONLY"
        primary_direction = DIRECTIONS[primary_index]
    elif (float(policy["cover_min_gap_pp"]) <= primary_margin_pp
          < float(policy["cover_max_gap_pp"])):
        draw_index = DIRECTIONS.index("D")
        if (draw_index != primary_index
                and abs(values_pp[draw_index] - values_pp[runner_up_index])
                <= float(policy["draw_tie_band_pp"])):
            selected_alternative_index = draw_index
        if values_pp[selected_alternative_index] / 100.0 >= float(policy["alternative_min_probability"]):
            classification = "PRIMARY_WITH_COVER"
            primary_direction = DIRECTIONS[primary_index]
            alternative_direction = DIRECTIONS[selected_alternative_index]

    primary_vs_alternative_pp = (
        values_pp[primary_index] - values_pp[selected_alternative_index]
        if alternative_direction is not None else None
    )
    signature_components = policy_signature_components(policy)
    return {
        "schema_version": policy["schema_version"],
        "rule_version": policy["rule_version"],
        "policy_version": policy["rule_version"],
        "status": "AVAILABLE",
        "classification": classification,
        "primary_direction": primary_direction,
        "alternative_direction": alternative_direction,
        "probabilities": _raw_probability_mapping(probabilities),
        "probability_unit": unit,
        "probability_source": probability_source.strip(),
        "trigger": {
            "rule_version": policy["rule_version"],
            "primary_margin_pp": round(primary_margin_pp, 10),
            "primary_vs_alternative_pp": (
                round(primary_vs_alternative_pp, 10)
                if primary_vs_alternative_pp is not None else None
            ),
            "primary_only_min_gap_pp": float(policy["primary_only_min_gap_pp"]),
            "cover_min_gap_pp": float(policy["cover_min_gap_pp"]),
            "cover_max_gap_pp": float(policy["cover_max_gap_pp"]),
            "alternative_min_probability": float(policy["alternative_min_probability"]),
            "draw_tie_band_pp": float(policy["draw_tie_band_pp"]),
            "unclear_max_gap_pp": float(policy["unclear_max_gap_pp"]),
        },
        "gap_pp": round(primary_margin_pp, 10),
        "prediction_as_of": time_value,
        "model_version": identity[0],
        "probability_signature": identity[1],
        "decision_policy_signature": canonical_policy_signature(policy),
        "decision_policy_signature_components": signature_components,
        "reason": None,
    }
