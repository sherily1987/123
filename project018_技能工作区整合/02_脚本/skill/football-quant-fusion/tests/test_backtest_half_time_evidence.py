from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE = SCRIPTS / "backtest_dual_track.py"
SPEC = importlib.util.spec_from_file_location("backtest_dual_track", MODULE)
backtest = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(backtest)


def test_half_time_requires_verified_external_evidence_not_bare_result_field():
    result = {"score_ht": {"home": 1, "away": 0}, "score_90": {"home": 2, "away": 0}}
    evidence = {
        "status": "verified", "matched_by": "team_time_fulltime",
        "provider": "api-sports.io", "provider_fixture_id": "42",
        "record_kickoff": "2026-08-01T12:00:00+08:00",
        "provider_kickoff": "2026-08-01T12:00:00+08:00",
        "score_ht": {"home": 1, "away": 0},
        "score_90": {"home": 2, "away": 0},
    }

    assert backtest.official_half_time_score(result) is None
    assert backtest.official_half_time_score(result, evidence) == {"home": 1, "away": 0}
