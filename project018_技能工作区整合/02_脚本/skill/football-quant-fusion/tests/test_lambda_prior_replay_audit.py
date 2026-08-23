from __future__ import annotations

import importlib
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_lambda_prior_replay_audit_module_is_available():
    """Catches removal of the deterministic legacy-prior replay entrypoint."""
    try:
        module = importlib.import_module("lambda_prior_replay_audit")
    except ModuleNotFoundError:
        module = None

    assert module is not None


import lambda_prior_replay_audit as lra


def test_compare_prior_requires_probability_and_sample_identity():
    """Catches matching lambdas being accepted when their historical sample differs."""
    saved = {
        "lambda_home": 1.2,
        "lambda_away": 0.8,
        "source": "understat_rolling_xg",
        "sample_legs": 20,
        "team_sample_sizes": {"home": 10, "away": 11},
    }
    replayed = dict(saved)

    assert lra.compare_prior(saved, replayed)["equivalent"] is True
    replayed["sample_legs"] = 21
    mismatch = lra.compare_prior(saved, replayed)
    assert mismatch["equivalent"] is False
    assert "sample_legs" in mismatch["mismatches"]


def test_replay_job_preserves_router_time_evidence_on_exact_match():
    """Catches exact replay losing the history_latest evidence needed for admission."""
    saved = {
        "lambda_home": 1.2,
        "lambda_away": 0.8,
        "source": "understat_rolling_xg",
        "sample_legs": 20,
        "team_sample_sizes": {"home": 10, "away": 11},
    }
    job = {
        "identity": {"match_id": "sporttery-1", "kickoff": "2026-08-23T18:00:00+08:00"},
        "input": {"home": "主队", "away": "客队", "competition": "英超", "kickoff": "2026-08-23T18:00:00+08:00"},
        "research": {"hybrid": {"lambda_prior": saved}},
    }

    def fake_route(match, understat, events, min_history, enable_experimental):
        return {
            "lambda_prior": dict(saved),
            "field_meta": {"production_router": {
                "no_future_leakage": True,
                "history_latest": "2026-08-20T18:00:00+08:00",
            }},
        }

    result = lra.replay_job(job, [], [], route_fn=fake_route)

    assert result["status"] == "equivalent"
    assert result["match_id"] == "sporttery-1"
    assert result["routing_audit"]["history_latest"] == "2026-08-20T18:00:00+08:00"
