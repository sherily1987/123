"""Verify that the canonical registry is a lossless superset of legacy stores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migration_inventory import inventory_store


def _by_id(inventory: dict) -> dict[str, dict]:
    return {str(item["row"].get("prediction_id", "")): item for item in inventory["records"]}


def verify_canonical_store(canonical: Path, sources: list[Path]) -> tuple[dict, list[dict]]:
    canonical_inventory = inventory_store(canonical, label="canonical")
    canonical_by_id = _by_id(canonical_inventory)
    source_only, conflicts, mapping = set(), set(), []
    source_reports = []
    for source in sources:
        inventory = inventory_store(source)
        source_reports.append({key: value for key, value in inventory.items() if key != "records"})
        for prediction_id, record in _by_id(inventory).items():
            target = canonical_by_id.get(prediction_id)
            if target is None:
                source_only.add(prediction_id)
                status = "source_only"
            elif target["payload_hash"] != record["payload_hash"]:
                conflicts.add(prediction_id)
                status = "content_conflict"
            else:
                status = "already_canonical"
            mapping.append({
                "prediction_id": prediction_id,
                "source_store": inventory["store"],
                "source_path": record["path"],
                "source_sha256": record["payload_hash"],
                "source_entry_hash": record["row"].get("entry_hash"),
                "canonical_path": target["path"] if target else None,
                "canonical_sha256": target["payload_hash"] if target else None,
                "canonical_entry_hash": target["row"].get("entry_hash") if target else None,
                "migration_status": status,
            })
    canonical_ok = (
        canonical_inventory["chain_valid"]
        and not canonical_inventory["missing_files"]
        and not canonical_inventory["content_hash_mismatches"]
        and not canonical_inventory["duplicate_ids"]
    )
    report = {
        "ok": bool(canonical_ok and not source_only and not conflicts),
        "canonical_store": canonical_inventory["store"],
        "canonical_rows": canonical_inventory["registry_rows"],
        "canonical_chain_valid": canonical_inventory["chain_valid"],
        "canonical_version_distribution": canonical_inventory["version_distribution"],
        "source_only_prediction_ids": sorted(source_only),
        "conflict_prediction_ids": sorted(conflicts),
        "source_reports": source_reports,
        "mapping_rows": len(mapping),
    }
    return report, sorted(mapping, key=lambda item: (item["prediction_id"], item["source_store"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical", required=True, type=Path)
    parser.add_argument("--source", action="append", default=[], type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    args = parser.parse_args()
    report, mapping = verify_canonical_store(args.canonical, args.source)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.mapping.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in mapping), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
