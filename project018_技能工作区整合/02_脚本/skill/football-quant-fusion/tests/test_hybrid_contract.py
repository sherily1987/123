import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hybrid_contract as contract


LOCK = {
    "model_version": "m4",
    "probability_signature": "a" * 64,
}


def valid_sidecar():
    return {
        "hybrid_sidecar_schema_version": "hybrid-sidecar-2.0",
        "evaluation_contract_version": "hybrid-review-1.0",
        "research_only": True,
        "status": "ok",
        "mode": "hybrid",
        "market_derived": False,
        "lambda_prior": {"source": "independent"},
        "model_version": "m4",
        "probability_signature": "a" * 64,
        "hybrid_cohort_key": "m4::" + "a" * 64,
        "routing_audit": {
            "route": "understat_xg",
            "no_future_leakage": True,
            "history_latest": "2026-08-20T00:00:00+00:00",
        },
        "market_input_as_of": "2026-08-21T10:00:00+00:00",
        "research_run_at": "2026-08-21T10:01:00+00:00",
    }


INPUT = {
    "prediction_as_of": "2026-08-21T10:00:00+00:00",
    "kickoff": "2026-08-21T12:00:00+00:00",
}


def test_success_sidecar_requires_complete_time_and_version_contract():
    assert contract.validate_success_sidecar(valid_sidecar(), INPUT, LOCK) == []


@pytest.mark.parametrize(
    ("mutate", "error_code"),
    [
        (lambda row: row.pop("routing_audit"), "HYBRID_ROUTING_AUDIT_MISSING"),
        (lambda row: row["routing_audit"].pop("history_latest"), "HYBRID_HISTORY_LATEST_MISSING"),
        (lambda row: row.pop("research_run_at"), "HYBRID_RESEARCH_RUN_AT_MISSING"),
        (lambda row: row.pop("model_version"), "HYBRID_MODEL_VERSION_MISSING"),
        (lambda row: row.pop("probability_signature"), "HYBRID_PROBABILITY_SIGNATURE_MISSING"),
        (lambda row: row["routing_audit"].pop("route"), "HYBRID_ROUTE_MISSING"),
        (lambda row: row["routing_audit"].update(no_future_leakage=False), "HYBRID_NO_FUTURE_LEAKAGE_UNCONFIRMED"),
        (lambda row: row["routing_audit"].update(history_latest="2026-08-20T00:00:00"), "HYBRID_HISTORY_LATEST_TZ_REQUIRED"),
        (lambda row: row["routing_audit"].update(history_latest="2026-08-21T12:00:00+00:00"), "HYBRID_HISTORY_NOT_PREMATCH"),
        (lambda row: row.update(research_run_at="2026-08-21T12:00:00+00:00"), "HYBRID_RESEARCH_RUN_NOT_PREMATCH"),
        (lambda row: row.update(research_run_at="2026-08-21T10:01:00"), "HYBRID_RESEARCH_RUN_AT_TZ_REQUIRED"),
        (lambda row: row.pop("market_input_as_of"), "HYBRID_MARKET_INPUT_AS_OF_MISSING"),
        (lambda row: row.update(market_input_as_of="2026-08-21T10:00:00"), "HYBRID_MARKET_INPUT_AS_OF_TZ_REQUIRED"),
        (lambda row: row.update(market_input_as_of="2026-08-21T12:00:00+00:00"), "HYBRID_MARKET_INPUT_NOT_PREMATCH"),
        (lambda row: row.update(probability_signature="b" * 64), "HYBRID_COHORT_DRIFT"),
    ],
)
def test_success_sidecar_fails_closed_for_each_missing_or_drifting_field(mutate, error_code):
    row = valid_sidecar()
    mutate(row)
    assert error_code in contract.validate_success_sidecar(row, INPUT, LOCK)


def test_denominator_ids_are_unique_and_stable():
    assert contract.REGISTERED_HYBRID_BACKTEST_V1 == "REGISTERED_HYBRID_BACKTEST_V1"
    assert contract.FROZEN_HYBRID_SIDECAR_AUDIT_20260824 == "FROZEN_HYBRID_SIDECAR_AUDIT_20260824"
    assert contract.LIVE_HYBRID_REVIEW_UNIQUE == "LIVE_HYBRID_REVIEW_UNIQUE"
    assert len(contract.DENOMINATOR_IDS) == len(set(contract.DENOMINATOR_IDS)) == 3
