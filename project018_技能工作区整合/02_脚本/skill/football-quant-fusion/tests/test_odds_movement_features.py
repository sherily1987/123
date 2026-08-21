import importlib.util
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("odds_movement_features", SCRIPTS / "odds_movement_features.py")
features = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(features)


def test_feature_uses_only_safe_had_snapshots_and_devigs_direction_shift():
    match = {"match_id": "sporttery-1", "prediction_as_of": "2026-08-21T12:00:00+08:00"}
    rows = [
        {"match_id": 1, "pool": "HAD", "updated_at": "2026-08-21 09:00:00",
         "odds": {"h": "2.0", "d": "3.0", "a": "6.0"}},
        {"match_id": 1, "pool": "HAD", "updated_at": "2026-08-21 11:00:00",
         "odds": {"h": "1.8", "d": "3.2", "a": "7.0"}},
        {"match_id": 1, "pool": "HAD", "updated_at": "2026-08-21 13:00:00",
         "odds": {"h": "1.2", "d": "6.0", "a": "15.0"}},
    ]

    result = features.movement_feature(match, rows)

    assert result["status"] == "VALID"
    assert result["safe_snapshot_count"] == 2
    assert result["excluded_after_prediction"] == 1
    assert result["from_updated_at"] == "2026-08-21 09:00:00"
    assert result["to_updated_at"] == "2026-08-21 11:00:00"
    assert result["prob_shift_pp"][0] > 0


def test_feature_fails_closed_when_no_two_safe_snapshots():
    result = features.movement_feature(
        {"match_id": "sporttery-1", "prediction_as_of": "2026-08-21T12:00:00+08:00"},
        [{"match_id": 1, "pool": "HAD", "updated_at": "2026-08-21 13:00:00",
          "odds": {"h": "2", "d": "3", "a": "6"}}],
    )

    assert result == {
        "research_only": True,
        "status": "UNAVAILABLE",
        "reason": "insufficient_safe_had_snapshots",
        "safe_snapshot_count": 0,
        "excluded_after_prediction": 1,
    }
