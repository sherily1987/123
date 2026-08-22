from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from fusion_predict_core import build_identity


def test_sample_audit_counts_later_m4_prediction_as_current_despite_delayed_m3_write(tmp_path):
    """Sample audit must use the prediction's original time, not registry persistence order."""
    store = tmp_path / "backtest"
    predictions = store / "predictions"
    predictions.mkdir(parents=True)
    m4_identity = build_identity()
    records = []
    for name, model, created_at, prediction_as_of in [
        ("m3", {"model_version": "m3", "probability_signature": "a" * 64},
         "2026-08-21T16:00:00Z", "2026-08-21T13:00:00Z"),
        ("m4", {"model_version": m4_identity["model_version"],
                 "probability_signature": m4_identity["probability_signature"]},
         "2026-08-21T15:00:00Z", "2026-08-21T14:00:00Z"),
    ]:
        path = predictions / f"{name}.json"
        path.write_text(json.dumps({
            "match_id": "m1", "prediction_id": f"m1-{name}", "snapshot_type": "prematch",
            "created_at": created_at, "prediction_as_of": prediction_as_of, "model": model,
        }), encoding="utf-8")
        records.append({"match_id": "m1", "path": str(path)})
    (store / "registry.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    output = tmp_path / "audit.json"

    proc = subprocess.run([
        sys.executable, str(SCRIPTS / "sample_audit.py"),
        "--store", str(store), "--output", str(output),
    ], text=True, capture_output=True)

    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["by_version_cohort"]["current"] == 1
