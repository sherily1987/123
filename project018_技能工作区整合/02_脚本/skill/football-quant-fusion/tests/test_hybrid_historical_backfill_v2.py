import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
backfill = importlib.import_module("hybrid_historical_backfill_v2")
contract = importlib.import_module("hybrid_contract")


LOCK = {"model_version": "m4", "probability_signature": "a" * 64}


def _pair():
    return ({
        "identity": {
            "match_id": "sporttery-1", "kickoff": "2026-08-21T12:00:00+00:00",
            "home": "主队", "away": "客队", "competition": "英超",
        },
        "input": {
            "home": "主队", "away": "客队", "competition": "英超",
            "kickoff": "2026-08-21T12:00:00+00:00",
            "prediction_as_of": "2026-08-21T10:00:00+00:00",
            "odds": [2.0, 3.2, 4.1],
        },
        "research": {"hybrid": {
            "lambda_prior": {"lambda_home": 1.4, "lambda_away": 0.9, "source": "independent"},
            "routing_audit": {
                "route": "understat_xg", "no_future_leakage": True,
                "history_latest": "2026-08-20T00:00:00+00:00",
            },
        }},
    }, {"score_90": {"home": 2, "away": 1}, "status": "finished"})


def _predict(_core, _version, _payload):
    return {
        "fusion_status": "ok", "mode": "hybrid", "research_only": True,
        "build_identity": LOCK,
        "forecast": {
            "final_1x2_pct": [55, 25, 20], "model_1x2_pct": [60, 22, 18],
            "market_prob_pct": [50, 30, 20],
        },
    }


def test_historical_replay_keeps_real_execution_time_separate_from_simulation_as_of():
    job, result = _pair()
    row = backfill.build_replay_row(
        None, {}, job, result, LOCK,
        replay_generated_at=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
        predict_fn=_predict,
    )
    sidecar = row["hybrid"]
    assert sidecar["model_version"] == "m4"
    assert sidecar["probability_signature"] == "a" * 64
    assert sidecar["hybrid_cohort_key"] == "m4::" + "a" * 64
    assert sidecar["simulation_as_of"] == "2026-08-21T10:00:00+00:00"
    assert sidecar["replay_generated_at"] == "2026-08-26T12:00:00+00:00"
    assert contract.validate_historical_replay_sidecar(sidecar, job["input"], LOCK) == []


def test_historical_replay_marks_verified_prematch_pool_snapshot_as_fresh():
    seen = {}

    def capture(_core, _version, payload):
        seen.update(payload)
        return _predict(_core, _version, payload)

    job, result = _pair()
    backfill.build_replay_row(
        None, {}, job, result, LOCK,
        replay_generated_at=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
        predict_fn=capture,
    )
    assert seen["field_meta"]["odds"]["freshness"] == 100
    assert seen["field_meta"]["odds"]["collected_at"] == job["input"]["prediction_as_of"]
    assert seen["field_meta"]["production_router"]["history_latest"] < job["input"]["kickoff"]


def test_historical_replay_contract_rejects_missing_version_identity():
    job, result = _pair()

    def missing_identity(*_args):
        output = _predict(None, None, None)
        output.pop("build_identity")
        return output

    row = backfill.build_replay_row(
        None, {}, job, result, LOCK,
        replay_generated_at=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
        predict_fn=missing_identity,
    )
    assert row["status"] == "error"
    assert "HYBRID_MODEL_VERSION_MISSING" in row["errors"]


def test_backfill_report_uses_separate_denominator_and_current_cohort_only():
    report = backfill.build_report(
        [_pair()], None, {}, LOCK, predict_fn=_predict,
        replay_generated_at=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
    )
    assert report["denominator_id"] == "HISTORICAL_HYBRID_REPLAY_CURRENT"
    assert report["review"]["denominator_id"] == "HISTORICAL_HYBRID_REPLAY_CURRENT"
    assert report["n"] == 1
    assert set(report["cohorts"]) == {"m4::" + "a" * 64}
    assert report["production_change_allowed"] is False


def test_backfill_report_preserves_failed_row_evidence_for_audit():
    def unscorable(_core, _version, _payload):
        output = _predict(None, None, None)
        output["forecast"].pop("market_prob_pct")
        return output

    report = backfill.build_report(
        [_pair()], None, {}, LOCK, predict_fn=unscorable,
        replay_generated_at=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
    )
    assert report["n"] == 0
    assert report["error_rows"][0]["errors"] == ["HYBRID_REPLAY_UNSCORABLE"]
    assert report["error_rows"][0]["hybrid"]["model_version"] == "m4"


def test_reevaluate_existing_report_repairs_nested_denominator_without_predictions():
    report = backfill.build_report(
        [_pair()], None, {}, LOCK, predict_fn=_predict,
        replay_generated_at=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
    )
    report["review"]["denominator_id"] = "LIVE_HYBRID_REVIEW_UNIQUE"
    repaired = backfill.reevaluate_report(report)
    assert repaired["review"]["denominator_id"] == "HISTORICAL_HYBRID_REPLAY_CURRENT"
    assert repaired["rows"] == report["rows"]
