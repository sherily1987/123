#!/usr/bin/env python3
"""Read-only grouped attestations for probability-signature drift.

Machine replay can establish only ``PENDING_REVIEW``.  This module has no
alias, manifest, registry, release-lock, or probability-file write path.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fusion_backtest import load_jsonl, resolve_path
from probability_replay_check import (COMPARE_FIELDS, FLOAT_TOLERANCE,
                                      canonical_json, registered_route, replay_one)


def _identity(record: dict[str, Any]) -> tuple[str, str]:
    model = record.get("model") or {}
    return (str(model.get("model_version") or ""),
            str(model.get("probability_signature") or ""))


def group_records(records: list[dict]) -> dict[tuple[str, str, str], list[dict]]:
    """Group strictly by stored model version, complete signature, and route."""
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for record in records:
        model_version, signature = _identity(record)
        # A missing route stays isolated and unreplayable.  It is never filled
        # from what today's prediction happens to output.
        route = registered_route(record) or ""
        groups.setdefault((model_version, signature, route), []).append(record)
    return groups


def group_status(results: list[dict]) -> str:
    if any(row.get("status") == "differs" for row in results):
        return "CHANGED_REQUIRES_VERSION_BUMP"
    if not results or any(row.get("status") == "UNREPLAYABLE" for row in results):
        return "UNREPLAYABLE"
    if all(row.get("status") == "identical" for row in results):
        return "PENDING_REVIEW"
    return "UNREPLAYABLE"


def evaluate_group(records: list[dict], *, current_identity: dict) -> dict:
    """Evaluate an immutable group under an all-or-nothing state machine."""
    if not records:
        raise ValueError("cannot evaluate an empty signature-drift group")
    model_version, signature = _identity(records[0])
    route = registered_route(records[0]) or ""
    expected_key = (model_version, signature, route)
    results = []
    for record in records:
        actual_key = (*_identity(record), registered_route(record) or "")
        if actual_key != expected_key:
            result = {
                "match_id": record.get("match_id"), "status": "UNREPLAYABLE",
                "route": actual_key[2] or None,
                "prediction_as_of": record.get("prediction_as_of"), "input_sha256": None,
                "diffs": {},
                "time_audit": {"usable": False, "reason": "group_identity_mismatch"},
            }
        elif not isinstance(record.get("input"), dict):
            result = {
                "match_id": record.get("match_id"), "status": "UNREPLAYABLE",
                "route": route or None, "prediction_as_of": record.get("prediction_as_of"),
                "input_sha256": None, "diffs": {},
                "time_audit": {"usable": False, "reason": "registered_input_missing"},
            }
        else:
            result = replay_one(record)
        # Group state binds time evidence even when a future implementation of
        # replay_one accidentally labels a failed audit as identical.
        if not (result.get("time_audit") or {}).get("usable"):
            result = dict(result)
            result["status"] = "UNREPLAYABLE"
        results.append(result)
    status = group_status(results)
    return {
        "schema_version": "signature-drift-attestation-1.0",
        "old_identity": {"model_version": model_version, "probability_signature": signature},
        "route": route or None,
        "current_identity": {"model_version": str(current_identity.get("model_version") or ""),
                             "probability_signature": str(current_identity.get("probability_signature") or "")},
        "compare_fields": list(COMPARE_FIELDS), "float_tolerance": FLOAT_TOLERANCE,
        "record_count": len(records), "results": results, "status": status,
        # Human approval and release-lock verification are intentionally a
        # separate later task.  An attestation cannot approve itself.
        "alias_eligible": False,
    }


def load_registered_records(root: Path) -> list[dict]:
    """Read registry-referenced prediction snapshots without modifying them."""
    records = []
    for entry in load_jsonl(root / "registry.jsonl"):
        path = resolve_path(entry.get("path", ""), root)
        if not path.exists():
            continue
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def _attestation_dir(root: Path) -> Path:
    return root / "signature-drift-attestations" / datetime.now(timezone.utc).date().isoformat()


def build_drift_attestations(root: Path, current_identity: dict) -> list[dict]:
    """Write evidence only beneath the caller-selected root; never alter input data."""
    reports = []
    output_dir = _attestation_dir(root)
    for key, records in sorted(group_records(load_registered_records(root)).items()):
        report = evaluate_group(records, current_identity=current_identity)
        report_hash_input = {key: value for key, value in report.items() if key not in {
            "generated_at", "report_sha256", "report_hash_input", "attestation_path",
        }}
        report["report_hash_input"] = report_hash_input
        report["report_sha256"] = hashlib.sha256(
            canonical_json(report_hash_input).encode("utf-8")
        ).hexdigest()
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        model_version, signature, route = key
        filename = f"{model_version or 'missing'}_{signature or 'missing'}_{route or 'missing'}.json"
        path = output_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        report["attestation_path"] = str(path)
        path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
        reports.append(report)
    return reports
