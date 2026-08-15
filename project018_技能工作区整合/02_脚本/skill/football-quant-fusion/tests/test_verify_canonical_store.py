import hashlib
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_canonical_store.py"
spec = importlib.util.spec_from_file_location("verify_canonical_store", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def _sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _store(root, prediction_id, payload):
    store = root / prediction_id
    pred = store / "predictions" / f"{prediction_id}.json"
    pred.parent.mkdir(parents=True)
    pred.write_text(json.dumps(payload), encoding="utf-8")
    record_hash = _sha(payload)
    row = {"prediction_id": prediction_id, "match_id": prediction_id, "path": str(pred), "record_hash": record_hash, "previous_hash": ""}
    row["entry_hash"] = _sha(row["previous_hash"] + row["record_hash"])
    (store / "registry.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return store


def test_verify_accepts_canonical_superset_and_writes_mapping(tmp_path):
    canonical = _store(tmp_path / "canonical", "p1", {"x": 1})
    legacy = _store(tmp_path / "legacy", "p1", {"x": 1})
    report, mapping = module.verify_canonical_store(canonical, [legacy])
    assert report["ok"] is True
    assert report["canonical_rows"] == 1
    assert report["source_only_prediction_ids"] == []
    assert mapping[0]["migration_status"] == "already_canonical"


def test_verify_blocks_source_only_or_conflicting_records(tmp_path):
    canonical = _store(tmp_path / "canonical", "p1", {"x": 1})
    legacy = _store(tmp_path / "legacy", "p2", {"x": 2})
    report, _ = module.verify_canonical_store(canonical, [legacy])
    assert report["ok"] is False
    assert report["source_only_prediction_ids"] == ["p2"]
