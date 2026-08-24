import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).parents[1] / "scripts" / "league_capability_matrix.py"
    spec = importlib.util.spec_from_file_location("league_capability_matrix", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classify_exposes_xg_coverage_and_production_eligibility():
    module = _module()
    rows = [
        {"league": "L1", "kickoff": "2026-01-01", "xg_status": "EXPLICIT_XG",
         "settlement": {"score_90_status": "verified"}, "evidence_audit": {"evidence_gap": False}},
        {"league": "L1", "kickoff": "2026-01-02", "xg_status": "UNAVAILABLE",
         "settlement": {"score_90_status": "verified"}, "evidence_audit": {"evidence_gap": False}},
    ]
    result = module.classify(rows, min_samples=1, min_recent=1, max_missing_rate=1.0,
                             min_verified_rate=1.0)
    assert result["xg_coverage_rate"] == 0.5
    assert result["production_eligible"] is True
    assert result["research_only"] is False
