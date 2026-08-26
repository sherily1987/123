#!/usr/bin/env python3
"""Hybrid research sidecar v2 contract and frozen cohort identity."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


HYBRID_SIDECAR_SCHEMA_VERSION = "hybrid-sidecar-2.0"
EVALUATION_CONTRACT_VERSION = "hybrid-review-1.0"

REGISTERED_HYBRID_BACKTEST_V1 = "REGISTERED_HYBRID_BACKTEST_V1"
FROZEN_HYBRID_SIDECAR_AUDIT_20260824 = "FROZEN_HYBRID_SIDECAR_AUDIT_20260824"
LIVE_HYBRID_REVIEW_UNIQUE = "LIVE_HYBRID_REVIEW_UNIQUE"
HISTORICAL_HYBRID_REPLAY_CURRENT = "HISTORICAL_HYBRID_REPLAY_CURRENT"
DENOMINATOR_IDS = (
    REGISTERED_HYBRID_BACKTEST_V1,
    FROZEN_HYBRID_SIDECAR_AUDIT_20260824,
    LIVE_HYBRID_REVIEW_UNIQUE,
)

CONFIG = Path(__file__).resolve().parents[1] / "config"
COHORT_LOCK = CONFIG / "hybrid_review_cohort.json"
_SIGNATURE = re.compile(r"^[0-9a-f]{64}$")


def _aware_time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def make_cohort_key(model_version: str, probability_signature: str) -> str:
    return f"{model_version}::{probability_signature}"


def load_active_cohort_lock(path: Path | str = COHORT_LOCK) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stamp_success_sidecar(sidecar: dict, build_identity: dict) -> dict:
    """Stamp version identity before validation and the single atomic job write."""
    row = dict(sidecar)
    model_version = build_identity.get("model_version")
    signature = build_identity.get("probability_signature")
    row.update({
        "hybrid_sidecar_schema_version": HYBRID_SIDECAR_SCHEMA_VERSION,
        "evaluation_contract_version": EVALUATION_CONTRACT_VERSION,
        "model_version": model_version,
        "probability_signature": signature,
        "hybrid_cohort_key": make_cohort_key(model_version, signature)
        if model_version and signature else None,
    })
    return row


def validate_success_sidecar(sidecar: dict, input_obj: dict, cohort_lock: dict | None = None) -> list[str]:
    """Return stable error codes. Any error means the sidecar must not be written."""
    errors: list[str] = []
    if sidecar.get("hybrid_sidecar_schema_version") != HYBRID_SIDECAR_SCHEMA_VERSION:
        errors.append("HYBRID_SCHEMA_VERSION_INVALID")
    if sidecar.get("evaluation_contract_version") != EVALUATION_CONTRACT_VERSION:
        errors.append("HYBRID_EVALUATION_CONTRACT_INVALID")
    if sidecar.get("research_only") is not True:
        errors.append("HYBRID_RESEARCH_ONLY_REQUIRED")
    if sidecar.get("status") != "ok" or sidecar.get("mode") != "hybrid":
        errors.append("HYBRID_SUCCESS_MODE_INVALID")
    if sidecar.get("market_derived") is True:
        errors.append("HYBRID_INDEPENDENT_PRIOR_REQUIRED")
    if not isinstance(sidecar.get("lambda_prior"), dict):
        errors.append("HYBRID_LAMBDA_PRIOR_MISSING")

    model_version = sidecar.get("model_version")
    signature = sidecar.get("probability_signature")
    if not model_version:
        errors.append("HYBRID_MODEL_VERSION_MISSING")
    if not isinstance(signature, str) or not _SIGNATURE.fullmatch(signature):
        errors.append("HYBRID_PROBABILITY_SIGNATURE_MISSING")
    expected_key = make_cohort_key(model_version, signature) if model_version and signature else None
    if expected_key and sidecar.get("hybrid_cohort_key") != expected_key:
        errors.append("HYBRID_COHORT_KEY_INVALID")

    audit = sidecar.get("routing_audit")
    if not isinstance(audit, dict):
        errors.append("HYBRID_ROUTING_AUDIT_MISSING")
        audit = {}
    if not audit.get("route"):
        errors.append("HYBRID_ROUTE_MISSING")
    if audit.get("no_future_leakage") is not True:
        errors.append("HYBRID_NO_FUTURE_LEAKAGE_UNCONFIRMED")

    kickoff_raw = input_obj.get("kickoff") or input_obj.get("kickoff_iso")
    kickoff = _aware_time(kickoff_raw)
    if kickoff is None:
        errors.append("HYBRID_KICKOFF_TZ_REQUIRED")

    history_raw = audit.get("history_latest")
    history_latest = _aware_time(history_raw)
    if not history_raw:
        errors.append("HYBRID_HISTORY_LATEST_MISSING")
    elif history_latest is None:
        errors.append("HYBRID_HISTORY_LATEST_TZ_REQUIRED")
    elif kickoff is not None and history_latest >= kickoff:
        errors.append("HYBRID_HISTORY_NOT_PREMATCH")

    run_raw = sidecar.get("research_run_at")
    research_run_at = _aware_time(run_raw)
    if not run_raw:
        errors.append("HYBRID_RESEARCH_RUN_AT_MISSING")
    elif research_run_at is None:
        errors.append("HYBRID_RESEARCH_RUN_AT_TZ_REQUIRED")
    elif kickoff is not None and research_run_at >= kickoff:
        errors.append("HYBRID_RESEARCH_RUN_NOT_PREMATCH")

    market_raw = sidecar.get("market_input_as_of")
    market_as_of = _aware_time(market_raw)
    input_market_raw = input_obj.get("prediction_as_of") or input_obj.get("collected_at")
    if not market_raw:
        errors.append("HYBRID_MARKET_INPUT_AS_OF_MISSING")
    elif market_as_of is None:
        errors.append("HYBRID_MARKET_INPUT_AS_OF_TZ_REQUIRED")
    elif kickoff is not None and market_as_of >= kickoff:
        errors.append("HYBRID_MARKET_INPUT_NOT_PREMATCH")
    if input_market_raw and market_raw != input_market_raw:
        errors.append("HYBRID_MARKET_SNAPSHOT_MISMATCH")

    if cohort_lock:
        if (model_version != cohort_lock.get("model_version")
                or signature != cohort_lock.get("probability_signature")):
            errors.append("HYBRID_COHORT_DRIFT")
    return list(dict.fromkeys(errors))


def validate_historical_replay_sidecar(
        sidecar: dict, input_obj: dict, cohort_lock: dict | None = None) -> list[str]:
    """Validate an honest post-event replay without backdating wall-clock execution.

    Historical replay is deliberately not accepted by the live-sidecar validator:
    it has a real ``replay_generated_at`` and a separate pre-match
    ``simulation_as_of`` instead of pretending the process ran before kickoff.
    """
    errors: list[str] = []
    if sidecar.get("hybrid_sidecar_schema_version") != HYBRID_SIDECAR_SCHEMA_VERSION:
        errors.append("HYBRID_SCHEMA_VERSION_INVALID")
    if sidecar.get("evaluation_contract_version") != EVALUATION_CONTRACT_VERSION:
        errors.append("HYBRID_EVALUATION_CONTRACT_INVALID")
    if sidecar.get("execution_type") != "historical_replay":
        errors.append("HYBRID_REPLAY_EXECUTION_TYPE_REQUIRED")
    if sidecar.get("research_only") is not True or sidecar.get("status") != "ok":
        errors.append("HYBRID_REPLAY_SUCCESS_REQUIRED")
    if sidecar.get("mode") != "hybrid" or not isinstance(sidecar.get("lambda_prior"), dict):
        errors.append("HYBRID_LAMBDA_PRIOR_MISSING")

    model_version = sidecar.get("model_version")
    signature = sidecar.get("probability_signature")
    if not model_version:
        errors.append("HYBRID_MODEL_VERSION_MISSING")
    if not isinstance(signature, str) or not _SIGNATURE.fullmatch(signature):
        errors.append("HYBRID_PROBABILITY_SIGNATURE_MISSING")
    expected_key = make_cohort_key(model_version, signature) if model_version and signature else None
    if expected_key and sidecar.get("hybrid_cohort_key") != expected_key:
        errors.append("HYBRID_COHORT_KEY_INVALID")
    if cohort_lock and (model_version != cohort_lock.get("model_version")
                        or signature != cohort_lock.get("probability_signature")):
        errors.append("HYBRID_COHORT_DRIFT")

    kickoff = _aware_time(input_obj.get("kickoff") or input_obj.get("kickoff_iso"))
    if kickoff is None:
        errors.append("HYBRID_KICKOFF_TZ_REQUIRED")
    audit = sidecar.get("routing_audit")
    if not isinstance(audit, dict):
        errors.append("HYBRID_ROUTING_AUDIT_MISSING")
        audit = {}
    if not audit.get("route"):
        errors.append("HYBRID_ROUTE_MISSING")
    if audit.get("no_future_leakage") is not True:
        errors.append("HYBRID_NO_FUTURE_LEAKAGE_UNCONFIRMED")
    history = _aware_time(audit.get("history_latest"))
    if history is None:
        errors.append("HYBRID_HISTORY_LATEST_TZ_REQUIRED")
    elif kickoff is not None and history >= kickoff:
        errors.append("HYBRID_HISTORY_NOT_PREMATCH")

    simulation = _aware_time(sidecar.get("simulation_as_of"))
    if simulation is None:
        errors.append("HYBRID_SIMULATION_AS_OF_TZ_REQUIRED")
    elif kickoff is not None and simulation >= kickoff:
        errors.append("HYBRID_SIMULATION_NOT_PREMATCH")
    input_market = input_obj.get("prediction_as_of") or input_obj.get("collected_at")
    if sidecar.get("market_input_as_of") != input_market:
        errors.append("HYBRID_MARKET_SNAPSHOT_MISMATCH")
    market_time = _aware_time(sidecar.get("market_input_as_of"))
    if market_time is None:
        errors.append("HYBRID_MARKET_INPUT_AS_OF_TZ_REQUIRED")
    elif kickoff is not None and market_time >= kickoff:
        errors.append("HYBRID_MARKET_INPUT_NOT_PREMATCH")
    if simulation is not None and market_time is not None and simulation != market_time:
        errors.append("HYBRID_SIMULATION_MARKET_TIME_MISMATCH")
    if _aware_time(sidecar.get("replay_generated_at")) is None:
        errors.append("HYBRID_REPLAY_GENERATED_AT_TZ_REQUIRED")
    return list(dict.fromkeys(errors))
