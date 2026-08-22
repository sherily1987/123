from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "score_shadow_compare.py"
if str(MODULE.parent) not in sys.path:
    sys.path.insert(0, str(MODULE.parent))
SPEC = importlib.util.spec_from_file_location("score_shadow_compare", MODULE)
shadow = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(shadow)


def test_candidate_score_matrix_is_normalized_and_shadow_only():
    matrix = shadow.bivariate_matrix(1.6, 0.9, lambda3=0.15, temperature=1.1)

    assert round(sum(matrix.values()), 12) == 1.0
    assert matrix["0-0"] > 0

    report = shadow.compare_rows([
        {"league": "西甲", "xg": [1.6, 0.9], "actual_score": "2-0"},
    ])

    assert report["research_only"] is True
    assert report["production_unchanged"] is True
    assert report["big5_candidate"]["n"] == 1
    assert report["big5_candidate"]["score_matrix"]["baseline"]["temperature"] == 1.0
    assert report["big5_candidate"]["score_matrix"]["candidate"]["temperature"] == 1.0
    assert report["big5_candidate"]["top_scores"]["baseline"]["temperature"] == 1.3
    assert report["big5_candidate"]["top_scores"]["candidate"]["temperature"] == 1.1
    assert report["big5_candidate"]["admission"] == "insufficient_n"


def test_score_shadow_selection_uses_prediction_as_of_and_model_version(tmp_path):
    """Score diagnostics must evaluate the later released model, not a delayed old write."""
    store = tmp_path / "backtest"
    predictions = store / "predictions"
    results = store / "results"
    predictions.mkdir(parents=True)
    results.mkdir()
    (results / "m1.json").write_text(
        json.dumps({"status": "finished", "settlement_scope": "90min", "score_90": {"home": 2, "away": 0}}),
        encoding="utf-8")
    registry = []
    for name, model_version, created_at, prediction_as_of in [
        ("m3", "m3", "2026-08-21T16:00:00Z", "2026-08-21T13:00:00Z"),
        ("m4", "m4", "2026-08-21T15:00:00Z", "2026-08-21T14:00:00Z"),
    ]:
        path = predictions / f"{name}.json"
        path.write_text(json.dumps({
            "match_id": "m1", "snapshot_type": "prematch", "created_at": created_at,
            "prediction_as_of": prediction_as_of,
            "model": {"model_version": model_version, "probability_signature": model_version * 32},
            "match": {"competition": "西甲"},
            "output": {"core_output": {"xg": [1.5, 0.8]}},
        }), encoding="utf-8")
        registry.append({"match_id": "m1", "path": str(path)})
    (store / "registry.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in registry), encoding="utf-8")

    selected = shadow.load_registered_rows(str(store), "latest_before_kickoff")

    assert len(selected) == 1
    assert selected[0]["model"]["model_version"] == "m4"
