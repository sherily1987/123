"""Evaluate an explicit four-model LLM shadow-sample JSON payload.

This module never discovers, scans, writes, or settles historical prediction/result
folders.  It accepts only the caller-provided JSON records and returns a report.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

MODEL_POOL = (
    "zhipu/glm-4-flash",
    "qwen/qwen-flash",
    "deepseek/deepseek-chat",
    "moonshot/kimi-k2.6",
)
NON_ORDINARY_TERMS = ("extra time", "penalt", "postpon", "cancel", "award", "forfeit", "加时", "点球", "延期", "取消", "弃权")


def _null_metrics() -> dict[str, Any]:
    return {
        "json_failure_rate": None,
        "evidence_rejection_rate": None,
        "model_disagreement_rate": None,
        "collapse_rate": None,
        "direction_accuracy": None,
    }


def _result_reason(record: dict[str, Any]) -> str | None:
    result = record.get("result")
    if not isinstance(result, dict):
        return "missing_result"
    status = str(result.get("status", "")).lower()
    if any(term in status for term in NON_ORDINARY_TERMS):
        return "non_ordinary_90min_status"
    if result.get("status") != "finished":
        return "result_not_finished"
    if result.get("settlement_scope") != "90min":
        return "settlement_scope_not_90min"
    score = result.get("score_90")
    if not isinstance(score, dict) or not all(isinstance(score.get(k), int) and score[k] >= 0 for k in ("home", "away")):
        return "missing_valid_90min_score"
    provenance = result.get("source_provenance_class")
    if provenance == "official_formal":
        return None
    if provenance == "user_confirmed_official":
        required = {
            "verified_by": "user_confirmed_official_sporttery_result",
            "verification_note": None,
            "evidence_reference": None,
        }
        if result.get("verified_by") != required["verified_by"]:
            return "unconfirmed_user_official_result"
        if not isinstance(result.get("verification_note"), str) or not result["verification_note"].strip():
            return "missing_user_confirmation_note"
        if not isinstance(result.get("evidence_reference"), str) or not result["evidence_reference"].strip():
            return "missing_user_confirmation_evidence"
        return None
    return "source_not_official_formal_or_complete_user_confirmed"


def _stage(sample_count: int) -> str:
    if sample_count < 30:
        return "under_30_quality_only"
    if sample_count < 100:
        return "30_to_99_descriptive_only"
    if sample_count < 200:
        return "100_to_199_no_production_weight_conclusion"
    return "200_plus_descriptive_review_required"


def _cohort_report(cohort_key: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    included: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    identities = {model: {"model_id": model, "included": 0, "excluded": 0, "prediction_identity": None} for model in MODEL_POOL}
    for record in records:
        model = record.get("model_id")
        reason = "unknown_model" if model not in MODEL_POOL else _result_reason(record)
        item = {"match_id": record.get("match_id"), "model_id": model, "reason": reason}
        if reason is None:
            included.append(record)
            identities[model]["included"] += 1
            identity = record.get("prediction_identity")
            if identities[model]["prediction_identity"] is None and isinstance(identity, dict):
                identities[model]["prediction_identity"] = identity
        else:
            exclusions.append(item)
            if model in identities:
                identities[model]["excluded"] += 1

    metrics = _null_metrics()
    if included:
        predictions = [r.get("prediction") if isinstance(r.get("prediction"), dict) else {} for r in included]
        metrics["json_failure_rate"] = sum(p.get("json_valid") is False for p in predictions) / len(included)
    if records:
        metrics["evidence_rejection_rate"] = sum(e["reason"] != "unknown_model" for e in exclusions) / len(records)

    by_match: dict[Any, list[str]] = defaultdict(list)
    directions: list[str] = []
    for record in included:
        prediction = record.get("prediction") if isinstance(record.get("prediction"), dict) else {}
        direction = prediction.get("direction")
        if isinstance(direction, str) and direction:
            directions.append(direction)
            by_match[record.get("match_id")].append(direction)
    comparable = [values for values in by_match.values() if len(values) >= 2]
    if comparable:
        metrics["model_disagreement_rate"] = sum(len(set(values)) > 1 for values in comparable) / len(comparable)
    if len(directions) >= 2:
        metrics["collapse_rate"] = Counter(directions).most_common(1)[0][1] / len(directions)

    sample_count = len(included)
    stage = _stage(sample_count)
    return {
        "cohort_key": cohort_key,
        "stage": stage,
        "input_records": len(records),
        "included_records": sample_count,
        "excluded_records": len(exclusions),
        "exclusions": exclusions,
        "identities": identities,
        "metrics": metrics,
        "winner_conclusion": None,
        "model_weight_adjustment": None,
        "production_weight_change_conclusion": None,
        "guardrails": {
            "under_30": "quality metrics only; no winner conclusion",
            "under_100": "no model weight adjustment",
            "under_200": "no production weight change conclusion",
        },
    }


def evaluate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate only ``payload['records']``; missing data is represented as null."""
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in records:
        if isinstance(raw, dict):
            groups[str(raw.get("cohort_key")) if raw.get("cohort_key") is not None else "__missing_cohort_key__"].append(raw)
    return {
        "status": "collecting",
        "model_pool": list(MODEL_POOL),
        "sample_thresholds": {"quality_only_under": 30, "weight_adjustment_at": 100, "production_weight_conclusion_at": 200},
        "production_quant_route": "MARKET_BASELINE/market_only",
        "formal_banker_count": 0,
        "input_contract": "explicit JSON records only; no historical-directory scan or mutation",
        "cohorts": {key: _cohort_report(key, value) for key, value in groups.items()},
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit("usage: evaluate_llm_shadow.py INPUT.json OUTPUT.json")
    input_path, output_path = Path(argv[1]), Path(argv[2])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    report = evaluate_payload(payload)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
