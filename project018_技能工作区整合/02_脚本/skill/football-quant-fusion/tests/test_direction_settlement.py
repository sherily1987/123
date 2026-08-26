from __future__ import annotations

import sys
import json
import subprocess
import importlib
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from direction_settlement import (  # noqa: E402
    settle_direction_policy,
    summarize_direction_policy_metrics,
)
backtest = importlib.import_module("fusion_backtest")
OFFICIAL_90MIN_SOURCE = "中国体彩网移动端官方赛果"


def policy(classification="PRIMARY_WITH_COVER", primary="H", alternative="D"):
    return {
        "status": "AVAILABLE",
        "classification": classification,
        "primary_direction": primary,
        "alternative_direction": alternative,
        "activation_timestamp": "2026-08-26T03:16:27+00:00",
        "prediction_as_of": "2026-09-01T10:00:00+00:00",
    }


def official(direction):
    scores = {"H": (2, 0), "D": (1, 1), "A": (0, 2)}
    home, away = scores[direction]
    return {
        "status": "finished",
        "settlement_scope": "90min",
        "score_90": {"home": home, "away": away},
        "source": {"name": OFFICIAL_90MIN_SOURCE},
    }


def settle(value, result=None, registration_status="REGISTERED", **kwargs):
    if result is None:
        result = official("D")
    return settle_direction_policy(
        value,
        result,
        registration_status=registration_status,
        kickoff=kwargs.get("kickoff", "2026-09-01T12:00:00+00:00"),
    )


def test_cover_hit_does_not_turn_primary_into_hit():
    assert settle(policy(primary="H", alternative="D"), official("D")) == {
        "primary_hit": False,
        "alternative_hit": True,
        "direction_policy_hit": True,
        "official_result": "D",
        "settlement_status": "SETTLED",
    }


def test_missing_historical_policy_is_not_registered_and_never_reinferred():
    assert settle(None, official("H"), registration_status="NOT_REGISTERED") == {
        "primary_hit": None,
        "alternative_hit": None,
        "direction_policy_hit": None,
        "official_result": "H",
        "settlement_status": "NOT_REGISTERED",
    }


def test_unavailable_and_unclear_policies_are_not_scoreable():
    unavailable = settle(
        {"status": "UNAVAILABLE", "classification": "UNAVAILABLE",
         "primary_direction": None, "alternative_direction": None},
        official("H"), registration_status="UNAVAILABLE",
    )
    unclear = settle(policy("UNCLEAR", None, None), official("D"))

    assert unavailable["settlement_status"] == "UNAVAILABLE"
    assert unclear["settlement_status"] == "UNCLEAR"
    assert all(unclear[key] is None for key in (
        "primary_hit", "alternative_hit", "direction_policy_hit"))


def test_only_verified_official_90_minute_results_are_settled():
    invalid_results = [
        "H",
        {"score_90_status": "pending", "score_90": {"home": 1, "away": 0}},
        {"score_90_status": "verified", "score_90": {"home": 1, "away": 0}},
        {"status": "pending", "settlement_scope": "90min",
         "score_90": {"home": 1, "away": 0},
         "source": {"name": OFFICIAL_90MIN_SOURCE}},
        {"status": "finished", "settlement_scope": "full_match",
         "score_90": {"home": 1, "away": 0},
         "source": {"name": OFFICIAL_90MIN_SOURCE}},
        {"status": "finished", "settlement_scope": "90min",
         "score_90": {"home": 1, "away": 0}, "score_et": {"home": 2, "away": 1},
         "source": {"name": OFFICIAL_90MIN_SOURCE}},
        {"status": "finished", "settlement_scope": "90min",
         "score_90": {"home": 1, "away": 1}, "penalty_winner": "home",
         "source": {"name": OFFICIAL_90MIN_SOURCE}},
        {"status": "finished", "settlement_scope": "90min",
         "score_90": {"home": 1, "away": 0}, "source": True},
        {"status": "finished", "settlement_scope": "90min",
         "score_90": {"home": 1, "away": 0},
         "source": {"name": "unknown-provider"}},
        {"status": "finished", "settlement_scope": "90min",
         "score_90": {"home": 1, "away": 0},
         "score_90_status": "pending",
         "source": {"name": OFFICIAL_90MIN_SOURCE}},
    ]

    for result in invalid_results:
        settled = settle(policy("PRIMARY_ONLY", "H", None), result)
        assert settled["settlement_status"] == "UNSETTLED"
        assert settled["official_result"] is None

    assert settle(policy("PRIMARY_ONLY", "H", None), official("H"))["primary_hit"] is True


def test_registered_policy_must_still_have_a_valid_prematch_time_contract():
    late = policy("PRIMARY_ONLY", "H", None)
    late["prediction_as_of"] = "2026-09-01T12:00:00+00:00"
    naive = policy("PRIMARY_ONLY", "H", None)
    naive["prediction_as_of"] = "2026-09-01T10:00:00"

    assert settle(late, official("H"))["settlement_status"] == "UNAVAILABLE"
    assert settle(naive, official("H"))["settlement_status"] == "UNAVAILABLE"
    for kickoff in (None, "", "not-a-time", "2026-09-01T12:00:00"):
        assert settle(policy("PRIMARY_ONLY", "H", None), official("H"),
                      kickoff=kickoff)["settlement_status"] == "UNAVAILABLE"


def test_registered_policy_before_activation_cannot_be_settled():
    historical = policy("PRIMARY_ONLY", "H", None)
    historical["prediction_as_of"] = "2026-08-26T03:16:26+00:00"

    settled = settle(
        historical,
        official("H"),
        kickoff="2026-08-27T12:00:00+00:00",
    )

    assert settled["settlement_status"] == "UNAVAILABLE"
    assert settled["primary_hit"] is None
    assert settled["direction_policy_hit"] is None


def test_three_hit_metrics_keep_independent_denominators():
    rows = [
        {"direction_policy_status": "REGISTERED",
         "direction_policy": policy("PRIMARY_ONLY", "H", None),
         "direction_settlement": settle(policy("PRIMARY_ONLY", "H", None), official("H"))},
        {"direction_policy_status": "REGISTERED",
         "direction_policy": policy("PRIMARY_WITH_COVER", "H", "D"),
         "direction_settlement": settle(policy("PRIMARY_WITH_COVER", "H", "D"), official("D"))},
        {"direction_policy_status": "REGISTERED",
         "direction_policy": policy("PRIMARY_WITH_COVER", "A", "D"),
         "direction_settlement": settle(policy("PRIMARY_WITH_COVER", "A", "D"), official("H"))},
        {"direction_policy_status": "REGISTERED",
         "direction_policy": policy("UNCLEAR", None, None),
         "direction_settlement": settle(policy("UNCLEAR", None, None), official("D"))},
        {"direction_policy_status": "UNAVAILABLE",
         "direction_policy": {"status": "UNAVAILABLE", "classification": "UNAVAILABLE"},
         "direction_settlement": settle(
             {"status": "UNAVAILABLE", "classification": "UNAVAILABLE"},
             official("H"), registration_status="UNAVAILABLE")},
        {"direction_policy_status": "NOT_REGISTERED", "direction_policy": None,
         "direction_settlement": settle(None, official("A"), registration_status="NOT_REGISTERED")},
        {"direction_policy_status": "REGISTERED",
         "direction_policy": policy("PRIMARY_WITH_COVER", "H", "D"),
         "direction_settlement": settle_direction_policy(
             policy("PRIMARY_WITH_COVER", "H", "D"), None,
             registration_status="REGISTERED",
             kickoff="2026-09-01T12:00:00+00:00")},
    ]

    metrics = summarize_direction_policy_metrics(rows)

    assert metrics["registration_status_counts"] == {
        "NOT_REGISTERED": 1, "REGISTERED": 5, "UNAVAILABLE": 1,
    }
    assert metrics["classification_counts"] == {
        "NOT_REGISTERED": 1,
        "PRIMARY_ONLY": 1,
        "PRIMARY_WITH_COVER": 3,
        "UNCLEAR": 1,
        "UNAVAILABLE": 1,
    }
    assert metrics["primary_hit"] == {"hits": 1, "n": 3, "rate": 1 / 3}
    assert metrics["alternative_hit"] == {"hits": 1, "n": 2, "rate": 0.5}
    assert metrics["direction_policy_hit"] == {"hits": 2, "n": 3, "rate": 2 / 3}
    assert metrics["denominator_isolation"] == {
        "top1_1x2_unchanged": True,
        "brier_ece_unchanged": True,
        "ev_kelly_unchanged": True,
        "coverage_is_not_primary_correctness": True,
    }


def test_backtest_reports_coverage_without_changing_top1_denominator(tmp_path):
    store = tmp_path / "backtest"
    predictions = store / "predictions"
    results = store / "results"
    predictions.mkdir(parents=True)
    results.mkdir()
    release = json.loads((SCRIPTS.parent / "config" / "release_lock.json").read_text(
        encoding="utf-8-sig"))
    registered_policy = policy("PRIMARY_WITH_COVER", "H", "D")
    record = {
        "prediction_id": "m-1__2026-09-01T10:00:00Z__prematch",
        "match_id": "m-1",
        "snapshot_type": "prematch",
        "created_at": "2026-09-01T10:00:00+00:00",
        "prediction_as_of": "2026-09-01T10:00:00+00:00",
        "kickoff": "2026-09-01T12:00:00+00:00",
        "match": {"competition": "Test League", "kickoff": "2026-09-01T12:00:00+00:00"},
        "model": {
            "model_version": release["model_version"],
            "probability_signature": release["probability_signature"],
        },
        "input": {"mode": "market_only", "odds": [2.0, 3.2, 4.0]},
        "output": {"final_1x2_pct": [50.0, 30.0, 20.0]},
        "direction_policy_status": "REGISTERED",
        "direction_policy": registered_policy,
    }
    prediction_path = predictions / "m-1.json"
    prediction_path.write_text(json.dumps(record), encoding="utf-8")
    (store / "registry.jsonl").write_text(json.dumps({
        "prediction_id": record["prediction_id"], "match_id": "m-1",
        "created_at": record["created_at"], "path": str(prediction_path),
    }) + "\n", encoding="utf-8")
    (results / "m-1.json").write_text(json.dumps(official("D")), encoding="utf-8")
    (store / "results_registry.jsonl").write_text(
        json.dumps({"match_id": "m-1"}) + "\n", encoding="utf-8")
    output = tmp_path / "report.json"

    completed = subprocess.run([
        sys.executable, str(SCRIPTS / "fusion_backtest.py"),
        "--store", str(store), "--output", str(output),
        "--bootstrap-iterations", "1", "--walk-forward-folds", "1",
    ], text=True, capture_output=True, check=False)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["overall"]["n"] == 1
    assert report["overall"]["accuracy_pct"] == 0.0
    assert report["direction_policy_metrics"]["primary_hit"] == {
        "hits": 0, "n": 1, "rate": 0.0,
    }
    assert report["direction_policy_metrics"]["alternative_hit"] == {
        "hits": 1, "n": 1, "rate": 1.0,
    }
    assert report["direction_policy_metrics"]["direction_policy_hit"] == {
        "hits": 1, "n": 1, "rate": 1.0,
    }


def test_backtest_alias_never_fills_an_inconsistent_registered_route(monkeypatch):
    alias = {
        "status": "EQUIVALENT_ALIAS", "model_version": "m3",
        "probability_signature": "b" * 64, "route": "market_only",
        "alias_to_model_version": "m4", "alias_to_probability_signature": "a" * 64,
    }
    monkeypatch.setattr(backtest, "load_version_aliases", lambda _version: [alias])
    scored_projection_with_conflict = {
        "model": {"model_version": "m3", "probability_signature": "b" * 64},
        "version": "fusion-1.5.0",
        "mode": "market_only",
        "route_identity_valid": False,
    }

    assert backtest.version_cohort(scored_projection_with_conflict, {
        "model_version": "m4", "probability_signature": "a" * 64,
    }) == "legacy"


def test_offline_actual_remains_top1_scoreable_but_not_formally_direction_settled(tmp_path):
    source = tmp_path / "offline.json"
    source.write_text(json.dumps({"matches": [{
        "match_id": "offline-1",
        "output": {"final_1x2_pct": [60.0, 25.0, 15.0]},
        "actual": [2, 0],
        "kickoff": "2026-09-01T12:00:00+00:00",
        "direction_policy_status": "REGISTERED",
        "direction_policy": policy("PRIMARY_ONLY", "H", None),
    }]}), encoding="utf-8")
    output = tmp_path / "report.json"

    completed = subprocess.run([
        sys.executable, str(SCRIPTS / "fusion_backtest.py"), str(source),
        "--store", str(tmp_path / "store"), "--output", str(output),
        "--bootstrap-iterations", "1", "--walk-forward-folds", "1",
    ], text=True, capture_output=True, check=False)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["overall"]["n"] == 1
    assert report["overall"]["accuracy_pct"] == 100.0
    assert report["direction_policy_metrics"]["primary_hit"]["n"] == 0
    assert report["direction_policy_metrics"]["direction_policy_hit"]["n"] == 0


def test_score_record_preserves_original_mode_projection_separate_from_route_identity(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "mode-1.json").write_text(json.dumps({
        "score_90": {"home": 1, "away": 0},
    }), encoding="utf-8")
    record = {
        "prediction_id": "mode-1__2026-09-01T10:00:00Z__prematch",
        "match_id": "mode-1",
        "model": {"version": "fusion-test"},
        "output": {"mode": "hybrid", "final_1x2_pct": [60.0, 25.0, 15.0]},
    }

    row, error = backtest.score_record(record, tmp_path)

    assert error is None
    assert row["mode"] == "hybrid"
    assert row["route"] is None
    assert row["route_identity_valid"] is False
    assert "hybrid" in backtest.route_stratification([row])
