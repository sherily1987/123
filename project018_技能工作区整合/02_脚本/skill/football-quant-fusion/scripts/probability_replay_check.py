#!/usr/bin/env python3
"""Replay registered predictions and compare every formal probability output.

This module only produces per-record evidence. Grouping, proof files, and any
later human approval live in ``signature_drift_governance`` so a replay cannot
silently alter a cohort or alias configuration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fusion_backtest import load_jsonl, resolve_path
from fusion_predict_core import build_identity
from runtime import resolve_python
from runtime_paths import backtest_store

HERE = Path(__file__).resolve().parent
PY = resolve_python()

# This is a governance contract, not a best-effort display list. Missing formal
# output is a difference and must never be silently defaulted.
COMPARE_FIELDS = (
    "final_1x2_pct", "model_1x2_pct", "score_matrix", "top_scores",
    "ou_2_5", "ou_3_5", "btts", "hafu_model", "ttg_score_consistency",
)
FLOAT_TOLERANCE = 1e-10


def canonical_json(value: Any) -> str:
    """Stable JSON used for immutable replay-input hashes."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def registered_route(record: dict[str, Any]) -> str | None:
    """Read route only from the registered snapshot, never a current replay."""
    candidates = []
    for container in (record, record.get("model") or {}, record.get("input") or {}):
        if isinstance(container, dict):
            value = container.get("route") or container.get("mode")
            if value not in (None, ""):
                candidates.append(str(value).strip())
    if not candidates or not candidates[0]:
        return None
    return candidates[0] if all(value == candidates[0] for value in candidates) else None


def _identity_value(container: dict[str, Any], field: str) -> Any:
    match = container.get("match") if isinstance(container.get("match"), dict) else {}
    aliases = {
        "home": ("home", "home_team"),
        "away": ("away", "away_team"),
        "competition": ("competition", "league", "stage"),
    }
    for key in aliases[field]:
        if container.get(key) not in (None, ""):
            return container[key]
        if match.get(key) not in (None, ""):
            return match[key]
    return None


def _record_identity(record: dict[str, Any]) -> dict[str, Any]:
    match = record.get("match") if isinstance(record.get("match"), dict) else {}
    return {
        "match_id": record.get("match_id"),
        "home": _identity_value(record, "home"),
        "away": _identity_value(record, "away"),
        "competition": _identity_value(record, "competition"),
        "kickoff": record.get("kickoff") or match.get("kickoff"),
        "prediction_as_of": record.get("prediction_as_of"),
    }


def _input_identity(payload: dict[str, Any]) -> dict[str, Any]:
    match = payload.get("match") if isinstance(payload.get("match"), dict) else {}
    return {
        "match_id": payload.get("match_id"),
        "home": _identity_value(payload, "home"),
        "away": _identity_value(payload, "away"),
        "competition": _identity_value(payload, "competition"),
        "kickoff": payload.get("kickoff") or payload.get("kickoff_at") or match.get("kickoff"),
        "prediction_as_of": payload.get("prediction_as_of"),
    }


_EVIDENCE_TIME_KEYS = frozenset({
    "as_of", "collected_at", "created_at", "observed_at", "refreshed_at",
    "timestamp", "updated_at",
})


def _late_evidence_time(value: Any, prediction_as_of: datetime | None) -> bool:
    """Detect time-stamped input evidence that was not available at prediction time."""
    if prediction_as_of is None:
        return False
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _EVIDENCE_TIME_KEYS:
                observed = _parse_time(child)
                if observed is not None and observed > prediction_as_of:
                    return True
            if _late_evidence_time(child, prediction_as_of):
                return True
    elif isinstance(value, list):
        return any(_late_evidence_time(item, prediction_as_of) for item in value)
    return False


def _time_audit(record: dict[str, Any], payload: dict[str, Any], route: str | None) -> dict:
    if not route:
        return {"usable": False, "reason": "registered_route_missing_or_inconsistent"}
    registered, stored = _record_identity(record), _input_identity(payload)
    for field in ("match_id", "home", "away", "competition"):
        if registered[field] in (None, "") or stored[field] in (None, ""):
            return {"usable": False, "reason": f"{field}_missing"}
        if str(registered[field]) != str(stored[field]):
            reason = {"home": "home_team_mismatch", "away": "away_team_mismatch"}.get(
                field, f"{field}_mismatch")
            return {"usable": False, "reason": reason}
    registered_kickoff, stored_kickoff = (_parse_time(registered["kickoff"]),
                                          _parse_time(stored["kickoff"]))
    if registered_kickoff is None or stored_kickoff is None:
        return {"usable": False, "reason": "kickoff_missing_or_not_timezone_aware"}
    if registered_kickoff != stored_kickoff:
        return {"usable": False, "reason": "kickoff_mismatch"}
    registered_as_of, stored_as_of = (_parse_time(registered["prediction_as_of"]),
                                      _parse_time(stored["prediction_as_of"]))
    if registered_as_of is None or stored_as_of is None:
        return {"usable": False, "reason": "prediction_as_of_missing_or_not_timezone_aware"}
    if registered_as_of != stored_as_of:
        return {"usable": False, "reason": "prediction_as_of_mismatch"}
    if registered_as_of >= registered_kickoff:
        return {"usable": False, "reason": "prediction_as_of_not_before_kickoff"}
    if _late_evidence_time(payload, registered_as_of):
        return {"usable": False, "reason": "evidence_after_prediction_as_of"}
    return {"usable": True, "reason": None}


def _formal_output(value: dict[str, Any]) -> dict[str, Any]:
    nested = value.get("core_output") if isinstance(value, dict) else None
    return nested if isinstance(nested, dict) else value


def _normalised_difference(before: Any, after: Any, path: str = "$") -> list[dict]:
    """Compare recursively; tolerance never erases type or array-shape drift."""
    if type(before) is not type(after):
        return [{"path": path, "reason": "type", "recorded": before, "replayed": after}]
    if isinstance(before, float):
        if abs(before - after) <= FLOAT_TOLERANCE:
            return []
        return [{"path": path, "reason": "numeric", "recorded": before, "replayed": after}]
    if isinstance(before, dict):
        differences = []
        before_keys, after_keys = set(before), set(after)
        for key in sorted(before_keys - after_keys):
            differences.append({"path": f"{path}.{key}", "reason": "missing_replayed",
                                "recorded": before[key], "replayed": None})
        for key in sorted(after_keys - before_keys):
            differences.append({"path": f"{path}.{key}", "reason": "missing_recorded",
                                "recorded": None, "replayed": after[key]})
        for key in sorted(before_keys & after_keys):
            differences.extend(_normalised_difference(before[key], after[key], f"{path}.{key}"))
        return differences
    if isinstance(before, list):
        if len(before) != len(after):
            return [{"path": path, "reason": "array_length", "recorded": before, "replayed": after}]
        return [diff for index, (left, right) in enumerate(zip(before, after))
                for diff in _normalised_difference(left, right, f"{path}[{index}]")]
    if before != after:
        return [{"path": path, "reason": "value", "recorded": before, "replayed": after}]
    return []


def _run_replay(payload: dict[str, Any]) -> dict[str, Any]:
    """Run current prediction code against the registered input."""
    with tempfile.TemporaryDirectory() as tmp:
        in_path, out_path = Path(tmp) / "input.json", Path(tmp) / "output.json"
        in_path.write_text(canonical_json(payload), encoding="utf-8")
        proc = subprocess.run([PY, str(HERE / "fusion_predict.py"), str(in_path),
                               "--output", str(out_path)], text=True, capture_output=True)
        if proc.returncode != 0 or not out_path.exists():
            detail = (proc.stderr or proc.stdout or "").strip()[:300]
            raise RuntimeError(detail or "prediction replay did not produce output")
        return json.loads(out_path.read_text(encoding="utf-8"))


def replay_one(record: dict[str, Any]) -> dict:
    """Replay one immutable record without inferring its route from fresh output."""
    match_id = record.get("match_id")
    payload = record.get("input")
    route = registered_route(record)
    prediction_as_of = record.get("prediction_as_of")
    if not isinstance(payload, dict):
        return {"match_id": match_id, "status": "UNREPLAYABLE", "route": route,
                "prediction_as_of": prediction_as_of, "input_sha256": None, "diffs": {},
                "time_audit": {"usable": False, "reason": "registered_input_missing"}}
    input_sha256 = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    time_audit = _time_audit(record, payload, route)
    if not time_audit["usable"]:
        return {"match_id": match_id, "status": "UNREPLAYABLE", "route": route,
                "prediction_as_of": prediction_as_of, "input_sha256": input_sha256, "diffs": {},
                "time_audit": time_audit}
    try:
        fresh = _formal_output(_run_replay(payload))
    except Exception as exc:
        return {"match_id": match_id, "status": "UNREPLAYABLE", "route": route,
                "prediction_as_of": prediction_as_of, "input_sha256": input_sha256, "diffs": {},
                "time_audit": {"usable": False, "reason": f"replay_failed:{exc}"}}
    recorded = _formal_output(record.get("output") or {})
    diffs = {}
    for field in COMPARE_FIELDS:
        if field not in recorded or field not in fresh:
            diffs[field] = {"recorded": recorded.get(field), "replayed": fresh.get(field),
                            "reason": "required_field_missing"}
            continue
        differences = _normalised_difference(recorded[field], fresh[field], f"$.{field}")
        if differences:
            diffs[field] = {"recorded": recorded[field], "replayed": fresh[field],
                            "differences": differences}
    return {"match_id": match_id, "status": "differs" if diffs else "identical",
            "route": route, "prediction_as_of": prediction_as_of,
            "input_sha256": input_sha256, "diffs": diffs, "time_audit": time_audit}


def build_report(root: Path, model_version: str, limit: int = 0) -> dict:
    """Legacy per-version evidence report; it cannot approve aliases or write state."""
    records = []
    for entry in load_jsonl(root / "registry.jsonl"):
        path = resolve_path(entry.get("path", ""), root)
        if not path.exists():
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str((rec.get("model") or {}).get("model_version") or "") == model_version:
            records.append(rec)
    results = [replay_one(rec) for rec in (records[:limit] if limit else records)]
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    current_identity = build_identity()
    replayed_signatures = sorted({str((record.get("model") or {}).get("probability_signature") or "")
                                  for record in records
                                  if (record.get("model") or {}).get("probability_signature")})
    replayed_modes = sorted({str(item.get("route")) for item in results if item.get("route")})
    verdict = ("equivalent" if results and all(item.get("status") == "identical" for item in results)
               else "changed" if any(item.get("status") == "differs" for item in results)
               else "inconclusive")
    return {"schema_version": "fusion-probability-replay-2.0",
            "replayed_model_version": model_version,
            "current_identity": {key: str(current_identity.get(key) or "")
                                 for key in ("model_version", "probability_signature")},
            "compare_fields": list(COMPARE_FIELDS), "float_tolerance": FLOAT_TOLERANCE,
            "replayed_probability_signatures": replayed_signatures,
            "replayed_modes": replayed_modes, "verdict": verdict,
            "replayed_n": len(results), "counts": counts, "results": results,
            "note": "Evidence only; this script never creates or loads aliases."}


def main() -> int:
    ap = argparse.ArgumentParser(description="重放已登记预测；不修改版本或别名")
    ap.add_argument("--store", default=str(backtest_store()))
    ap.add_argument("--model-version", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--output")
    args = ap.parse_args()
    report = build_report(Path(args.store), args.model_version, args.limit)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
