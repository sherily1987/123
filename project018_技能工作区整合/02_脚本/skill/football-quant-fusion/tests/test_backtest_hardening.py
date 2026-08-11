import importlib.util
from pathlib import Path


SCRIPT = Path(r"C:/Users/Administrator/.codex/skills/football-quant-fusion/scripts/auto_backtest.py")
spec = importlib.util.spec_from_file_location("auto_backtest", SCRIPT)
auto_backtest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto_backtest)


def test_primary_selection_keeps_latest_prekickoff_per_match_and_labels_every_exclusion():
    rows = [
        {"match_id": "m1", "prediction_as_of": "2026-01-01T08:00:00Z", "kickoff": "2026-01-01T10:00:00Z"},
        {"match_id": "m1", "prediction_as_of": "2026-01-01T09:00:00Z", "kickoff": "2026-01-01T10:00:00Z"},
        {"match_id": "m2", "prediction_as_of": "2026-01-01T10:00:00Z", "kickoff": "2026-01-01T10:00:00Z"},
        {"match_id": "m3", "prediction_as_of": None, "kickoff": "2026-01-01T10:00:00Z"},
        {"match_id": "m4", "prediction_as_of": "2026-01-01T09:00:00Z", "kickoff": None},
    ]

    selected, dropped = auto_backtest.select_primary_records(rows)

    assert [r["match_id"] for r in selected] == ["m1"]
    assert selected[0]["prediction_as_of"] == "2026-01-01T09:00:00Z"
    assert {(r["match_id"], r["reason"]) for r in dropped} == {
        ("m1", "superseded_by_newer_prediction"),
        ("m2", "post_kickoff_prediction"),
        ("m3", "missing_prediction_as_of"),
        ("m4", "missing_kickoff"),
    }
