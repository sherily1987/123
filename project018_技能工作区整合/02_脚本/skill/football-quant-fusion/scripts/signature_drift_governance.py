#!/usr/bin/env python3
"""Read-only grouped attestations for probability-signature drift.

Machine replay can establish only ``PENDING_REVIEW``.  This module has no
alias, manifest, registry, release-lock, or probability-file write path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re
import sys

from fusion_backtest import load_jsonl, resolve_path
from fusion_predict_core import build_identity
from probability_replay_check import (COMPARE_FIELDS, FLOAT_TOLERANCE,
                                      canonical_json, is_complete_signature,
                                      registered_route, replay_one)


_ROUTE_UNSET = object()
_PROTECTED_OUTPUT_TOKENS = {"store", "history", "registry", "results", "lock", "policy"}


class ReplaySelectionError(RuntimeError):
    """The strict replay selector did not resolve one complete expected group."""


def _identity(record: dict[str, Any]) -> tuple[str, Any]:
    model = record.get("model") or {}
    return (str(model.get("model_version") or ""),
            model.get("probability_signature"))


def _signature_group_key(signature: Any) -> tuple[str, str]:
    """Return a deterministic sortable key without erasing raw JSON types."""
    json_type = {
        type(None): "null",
        bool: "boolean",
        int: "integer",
        float: "number",
        str: "string",
        list: "array",
        dict: "object",
    }.get(type(signature), f"invalid-{type(signature).__name__}")
    try:
        encoded = canonical_json(signature)
    except (TypeError, ValueError):
        # Registry snapshots are JSON, so this is only a defense for a
        # corrupted in-memory value.  The type tag prevents it from colliding
        # with a genuine JSON string that happens to share the same text.
        encoded = canonical_json(str(signature))
    return json_type, encoded


def group_records(records: list[dict]) -> dict[tuple[str, tuple[str, str], str], list[dict]]:
    """Group strictly by stored model version, complete signature, and route."""
    groups: dict[tuple[str, tuple[str, str], str], list[dict]] = {}
    for record in records:
        model_version, signature = _identity(record)
        # A missing route stays isolated and unreplayable.  It is never filled
        # from what today's prediction happens to output.
        route = registered_route(record) or ""
        groups.setdefault((model_version, _signature_group_key(signature), route), []).append(record)
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
    expected_key = (model_version, _signature_group_key(signature), route)
    current_signature = current_identity.get("probability_signature")
    current_identity_valid = bool(str(current_identity.get("model_version") or "")) and \
        is_complete_signature(current_signature)
    results = []
    for record in records:
        actual_identity = _identity(record)
        actual_key = (actual_identity[0], _signature_group_key(actual_identity[1]),
                      registered_route(record) or "")
        record_signature_valid = is_complete_signature(actual_identity[1])
        raw_model_version = ((record.get("model") or {}).get("model_version")
                             if isinstance(record.get("model") or {}, dict) else None)
        if (not isinstance(raw_model_version, str) or not raw_model_version.strip()
                or raw_model_version != raw_model_version.strip()):
            result = {
                "match_id": record.get("match_id"), "status": "UNREPLAYABLE",
                "route": actual_key[2] or None,
                "prediction_as_of": record.get("prediction_as_of"), "input_sha256": None,
                "diffs": {},
                "time_audit": {"usable": False, "reason": "model_version_invalid"},
            }
        elif not record_signature_valid:
            result = {
                "match_id": record.get("match_id"), "status": "UNREPLAYABLE",
                "route": actual_key[2] or None,
                "prediction_as_of": record.get("prediction_as_of"), "input_sha256": None,
                "diffs": {},
                "time_audit": {"usable": False, "reason": "probability_signature_invalid"},
            }
        elif not current_identity_valid:
            result = {
                "match_id": record.get("match_id"), "status": "UNREPLAYABLE",
                "route": actual_key[2] or None,
                "prediction_as_of": record.get("prediction_as_of"), "input_sha256": None,
                "diffs": {},
                "time_audit": {"usable": False, "reason": "current_identity_invalid"},
            }
        elif actual_key != expected_key:
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


def _attestation_filename(group_key: tuple[str, tuple[str, str], str]) -> str:
    """Map every raw group identity to one fixed Windows-safe filename."""
    digest = hashlib.sha256(canonical_json(group_key).encode("utf-8")).hexdigest()
    return f"signature-drift-{digest}.json"


def build_drift_attestations(
    root: Path,
    current_identity: dict,
    *,
    output_dir: Path | None = None,
    model_version: str | None = None,
    probability_signature: str | None = None,
    route: str | None = None,
    route_filter: object = _ROUTE_UNSET,
    expected_record_count: int | None = None,
    require_exactly_one_group: bool = False,
) -> list[dict]:
    """Read registered snapshots and write only caller-selected evidence files."""
    reports = []
    evidence_dir = Path(output_dir) if output_dir is not None else _attestation_dir(root)
    records = load_registered_records(root)
    if model_version is not None:
        records = [record for record in records if _identity(record)[0] == model_version]
    if probability_signature is not None:
        records = [record for record in records
                   if _identity(record)[1] == probability_signature]
    # ``route`` is retained for function-level compatibility.  Strict callers
    # use ``route_filter`` so that an explicit JSON null route is distinguishable
    # from no route filter at all.
    if route_filter is not _ROUTE_UNSET:
        records = [record for record in records if registered_route(record) == route_filter]
    elif route is not None:
        records = [record for record in records if registered_route(record) == route]
    groups = group_records(records)
    if expected_record_count is not None and len(records) != expected_record_count:
        raise ReplaySelectionError(
            f"selected record count {len(records)} != expected {expected_record_count}"
        )
    if require_exactly_one_group and len(groups) != 1:
        raise ReplaySelectionError(f"strict replay requires exactly one group; selected {len(groups)}")
    for key, group_rows in sorted(groups.items()):
        report = evaluate_group(group_rows, current_identity=current_identity)
        report_hash_input = {key: value for key, value in report.items() if key not in {
            "generated_at", "report_sha256", "report_hash_input", "attestation_path",
        }}
        report["report_hash_input"] = report_hash_input
        report["report_sha256"] = hashlib.sha256(
            canonical_json(report_hash_input).encode("utf-8")
        ).hexdigest()
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        path = evidence_dir / _attestation_filename(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        report["attestation_path"] = str(path)
        path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
        reports.append(report)
    return reports


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _contains_protected_output_directory(path: Path) -> bool:
    for part in path.parts:
        tokens = {token for token in re.split(r"[^a-z0-9]+", part.casefold()) if token}
        if tokens & _PROTECTED_OUTPUT_TOKENS:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按注册身份生成只读签名漂移重放证明")
    parser.add_argument("--store", required=True, help="只读正式 backtest 目录")
    parser.add_argument("--output-dir", required=True, help="正式库之外的治理证据目录")
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--probability-signature", required=True)
    route_group = parser.add_mutually_exclusive_group(required=True)
    route_group.add_argument("--route")
    route_group.add_argument("--route-null", action="store_true")
    parser.add_argument("--expected-record-count", required=True, type=int)
    args = parser.parse_args(argv)
    if not is_complete_signature(args.probability_signature):
        raise SystemExit("probability-signature must be a complete 64-hex SHA256")
    if args.expected_record_count < 1:
        raise SystemExit("expected-record-count must be positive")
    store = Path(args.store).resolve()
    output_dir = Path(args.output_dir).resolve()
    if output_dir == store or _is_within(output_dir, store):
        raise SystemExit("output-dir must be outside the read-only store")
    if _contains_protected_output_directory(output_dir):
        raise SystemExit("output-dir must not use a protected governance directory")
    try:
        reports = build_drift_attestations(
            store,
            build_identity(),
            output_dir=output_dir,
            model_version=args.model_version,
            probability_signature=args.probability_signature,
            route_filter=None if args.route_null else args.route,
            expected_record_count=args.expected_record_count,
            require_exactly_one_group=True,
        )
    except ReplaySelectionError as exc:
        print(json.dumps({"status": "REJECTED", "reason": str(exc)},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({
        "store": str(store),
        "output_dir": str(output_dir),
        "report_count": len(reports),
        "reports": [{
            "attestation_path": report["attestation_path"],
            "old_identity": report["old_identity"],
            "route": report["route"],
            "record_count": report["record_count"],
            "status": report["status"],
        } for report in reports],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
