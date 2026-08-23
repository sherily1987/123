"""Pure contracts for the K3 research track.

This module deliberately has no network, registry, or model dependencies.  It
normalizes match identity and makes evidence gaps explicit so callers can
persist an auditable manifest without turning missing data into assumptions.
"""

from __future__ import annotations

from typing import Any


REQUIRED_EVIDENCE_SECTIONS = ("recent_form", "crs", "ttg", "hafu", "injuries", "lineups")


def normalize_match_id(value: Any) -> str | None:
    """Return the canonical ``sporttery-<id>`` key or ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower().startswith("sporttery-"):
        suffix = text.split("-", 1)[1].strip()
        return f"sporttery-{suffix}" if suffix.isdigit() else None
    return f"sporttery-{text}" if text.isdigit() else None


def validate_prediction_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate the minimum auditable contract for one LLM prediction."""
    reasons: list[str] = []
    match_id = normalize_match_id(record.get("match_id"))
    if match_id is None:
        reasons.append("MISSING_OR_INVALID_MATCH_ID")

    models = record.get("models_used")
    if not isinstance(models, list) or not models or not all(isinstance(x, str) and x for x in models):
        reasons.append("MODEL_POOL_MISSING")
        model_id = None
    else:
        model_id = models[0] if len(models) == 1 else None

    if not record.get("prediction_as_of"):
        reasons.append("PREDICTION_AS_OF_MISSING")

    if len(models or []) == 1:
        if record.get("research_only") is not True:
            reasons.append("SINGLE_MODEL_NOT_RESEARCH_ONLY")
        if record.get("action") != "observe":
            reasons.append("SINGLE_MODEL_ACTION_NOT_OBSERVE")
        if record.get("reason") != "single_model_no_consensus":
            reasons.append("SINGLE_MODEL_REASON_INVALID")
    elif record.get("single_model") is True:
        reasons.append("SINGLE_MODEL_FLAG_POOL_MISMATCH")

    if record.get("consensus") is True and len(models or []) <= 1:
        reasons.append("SINGLE_MODEL_CANNOT_CLAIM_CONSENSUS")

    return {
        "valid": not reasons,
        "match_id": match_id,
        "model_id": model_id,
        "reason_codes": reasons,
        "research_only": record.get("research_only") is True,
    }


def _status_from_presence(value: Any, *, expected: int = 1) -> str:
    if value is None or value == "":
        return "UNAVAILABLE"
    if isinstance(value, (list, tuple, set, dict)):
        count = len(value)
        if count == 0:
            return "UNAVAILABLE"
        return "AVAILABLE" if count >= expected else "PARTIAL"
    return "AVAILABLE"


def _recent_form_status(value: Any) -> str:
    if not isinstance(value, dict):
        return "UNAVAILABLE"
    home = value.get("home") or value.get("home_form") or []
    away = value.get("away") or value.get("away_form") or []
    lengths = [len(x) for x in (home, away) if isinstance(x, (list, tuple))]
    if not lengths or max(lengths, default=0) == 0:
        return "UNAVAILABLE"
    return "AVAILABLE" if min(lengths) >= 5 else "PARTIAL"


def _section_status(name: str, evidence: dict[str, Any], raw_match: dict[str, Any]) -> str:
    if name == "recent_form":
        return _recent_form_status(evidence.get("recent_form") or evidence.get("h2h"))
    if name in {"crs", "ttg", "hafu"}:
        return _status_from_presence(raw_match.get(name) or evidence.get(name))
    status = str(evidence.get(f"{name}_status") or "").upper()
    if status == "PREDICTED":
        # A multi-source expected XI is usable pre-match evidence, but it is
        # not equivalent to an official team sheet.  Keep the distinction in
        # the manifest so prompts can cite the risk without calling it official.
        return "PREDICTED"
    if status in {"OK", "AVAILABLE", "VALID", "VALID_EMPTY"}:
        return "AVAILABLE"
    if status == "PARTIAL":
        return "PARTIAL"
    return _status_from_presence(evidence.get(name))


def build_evidence_manifest(raw_match: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Build a serializable evidence completeness manifest."""
    match_id = normalize_match_id(raw_match.get("match_id") or (raw_match.get("sporttery_meta") or {}).get("match_id"))
    sections = {
        name: {"status": _section_status(name, evidence, raw_match)}
        for name in REQUIRED_EVIDENCE_SECTIONS
    }
    # Predicted lineups are not a missing section.  They carry a separate risk
    # flag and keep the model from silently upgrading them to official XI.
    gaps = [name for name, item in sections.items()
            if item["status"] in {"UNAVAILABLE", "PARTIAL"}]
    risks = [name for name, item in sections.items() if item["status"] == "PREDICTED"]
    if not gaps:
        overall = "COMPLETE"
    elif all(item["status"] == "UNAVAILABLE" for item in sections.values()):
        overall = "UNAVAILABLE"
    else:
        overall = "PARTIAL"
    independent = [name for name, item in sections.items()
                   if name not in {"crs", "ttg", "hafu"}
                   and item["status"] in {"AVAILABLE", "PARTIAL", "PREDICTED"}]
    has_markets = any(raw_match.get(name) or evidence.get(name)
                      for name in ("crs", "ttg", "hafu"))
    if overall != "COMPLETE" and has_markets and not independent:
        collection_status = "ONLY_ODDS"
    else:
        collection_status = overall
    return {
        "match_id": match_id,
        "kickoff": raw_match.get("kickoff_iso") or raw_match.get("kickoff"),
        "collected_at": evidence.get("collected_at") or evidence.get("evidence_collected_at"),
        "overall_status": overall,
        "collection_mode": "single_pass",
        "collection_status": collection_status,
        "required_sections": list(REQUIRED_EVIDENCE_SECTIONS),
        "gap_sections": gaps,
        "risk_sections": risks,
        "sections": sections,
    }
