"""Read-only inventory for football prediction registries."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: object) -> str:
    raw = value if isinstance(value, str) else stable_json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_registry(store: Path) -> tuple[list[dict], list[dict]]:
    rows, errors = [], []
    registry = store / "registry.jsonl"
    if not registry.exists():
        return rows, [{"line": 0, "error": "missing_registry"}]
    for number, line in enumerate(registry.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append({"line": number, "error": str(exc)})
    return rows, errors


def _payload_path(store: Path, row: dict) -> Path:
    path = Path(str(row.get("path", "")))
    if path.exists():
        return path
    if not path.is_absolute():
        return (store / path).resolve()
    candidates = list((store / "predictions").rglob(path.name)) if path.name else []
    return candidates[0] if len(candidates) == 1 else path


def inventory_store(store: Path, label: str | None = None) -> dict:
    store = Path(store).resolve()
    rows, json_errors = load_registry(store)
    missing, content_mismatches, duplicate_ids = [], [], []
    versions: dict[str, int] = defaultdict(int)
    seen: set[str] = set()
    chain_valid = not json_errors
    expected_previous = ""
    records = []
    for row in rows:
        prediction_id = str(row.get("prediction_id", ""))
        if prediction_id in seen:
            duplicate_ids.append(prediction_id)
        seen.add(prediction_id)
        if row.get("previous_hash", "") != expected_previous:
            chain_valid = False
        expected_entry = sha256(str(row.get("previous_hash", "")) + str(row.get("record_hash", "")))
        if row.get("entry_hash") != expected_entry:
            chain_valid = False
        expected_previous = str(row.get("entry_hash", ""))
        payload_path = _payload_path(store, row)
        payload = None
        payload_hash = None
        if not payload_path.exists():
            missing.append(prediction_id)
        else:
            try:
                payload = json.loads(payload_path.read_text(encoding="utf-8-sig"))
                payload_hash = sha256(payload)
                if row.get("record_hash") and row["record_hash"] != payload_hash:
                    content_mismatches.append(prediction_id)
            except (OSError, json.JSONDecodeError):
                content_mismatches.append(prediction_id)
        model = payload.get("model", {}) if isinstance(payload, dict) else {}
        version = model.get("model_version") or (payload or {}).get("model_version") or "unknown_legacy"
        versions[str(version)] += 1
        records.append({"row": row, "path": str(payload_path), "payload_hash": payload_hash, "payload": payload})
    return {
        "label": label or store.name,
        "store": str(store),
        "registry_rows": len(rows),
        "unique_prediction_ids": len(seen),
        "duplicate_ids": sorted(set(duplicate_ids)),
        "json_errors": json_errors,
        "missing_files": sorted(missing),
        "content_hash_mismatches": sorted(content_mismatches),
        "chain_valid": chain_valid,
        "version_distribution": dict(sorted(versions.items())),
        "records": records,
    }


def classify_sources(stores: list[Path]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    inventories = []
    for index, store in enumerate(stores):
        inventory = inventory_store(Path(store), label=f"source_{index + 1}")
        inventories.append(inventory)
        for record in inventory["records"]:
            grouped[str(record["row"].get("prediction_id", ""))].append(record)
    duplicates, conflicts = [], []
    for prediction_id, records in grouped.items():
        if len(records) > 1:
            duplicates.append(prediction_id)
            hashes = {record["payload_hash"] for record in records}
            if len(hashes) > 1:
                conflicts.append(prediction_id)
    return {
        "sources": inventories,
        "duplicate_prediction_ids": sorted(duplicates),
        "conflict_prediction_ids": sorted(conflicts),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = classify_sources(args.store)
    for source in report["sources"]:
        source.pop("records", None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
