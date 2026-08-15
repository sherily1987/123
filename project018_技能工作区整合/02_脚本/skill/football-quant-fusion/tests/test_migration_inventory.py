import hashlib
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "migration_inventory.py"
spec = importlib.util.spec_from_file_location("migration_inventory", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def _sha(value):
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _store(tmp_path, prediction_id="p1", payload=None):
    store = tmp_path / prediction_id
    pred = store / "predictions" / f"{prediction_id}.json"
    pred.parent.mkdir(parents=True)
    payload = payload or {"prediction_id": prediction_id, "model": {"model_version": "m1", "probability_signature": "sig"}}
    pred.write_text(json.dumps(payload), encoding="utf-8")
    record_hash = _sha(payload)
    entry = {"prediction_id": prediction_id, "match_id": "m1", "path": str(pred), "record_hash": record_hash, "previous_hash": ""}
    entry["entry_hash"] = _sha(entry["previous_hash"] + entry["record_hash"])
    (store / "registry.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return store


def test_inventory_valid_store(tmp_path):
    report = module.inventory_store(_store(tmp_path), label="repo")
    assert report["registry_rows"] == 1
    assert report["unique_prediction_ids"] == 1
    assert report["chain_valid"] is True
    assert report["missing_files"] == []


def test_inventory_detects_missing_file(tmp_path):
    store = _store(tmp_path)
    next((store / "predictions").glob("*.json")).unlink()
    report = module.inventory_store(store)
    assert report["missing_files"] == ["p1"]


def test_classify_sources_detects_duplicate_and_conflict(tmp_path):
    same_a = _store(tmp_path / "same-a", "same", {"x": 1})
    same_b = _store(tmp_path / "same-b", "same", {"x": 1})
    conflict = _store(tmp_path / "conflict", "same", {"x": 2})
    report = module.classify_sources([same_a, same_b, conflict])
    assert report["duplicate_prediction_ids"] == ["same"]
    assert report["conflict_prediction_ids"] == ["same"]
