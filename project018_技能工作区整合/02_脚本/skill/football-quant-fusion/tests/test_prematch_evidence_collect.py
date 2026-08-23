import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "prematch_evidence_collect.py"
spec = importlib.util.spec_from_file_location("prematch_evidence_collect", MODULE)
pec = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(pec)


def test_audit_has_recent_form_injuries_and_dynamic_lineup_schedule(monkeypatch):
    monkeypatch.setattr(pec.preview, "collect", lambda mid, terms, hist: {
        "feature": {"goalAvg": {"totalLegCnt": 10}},
        "strength": {"lambda_home": 1.4, "lambda_away": 1.1, "sample_legs": 10},
        "recent_home": [{"score": "1-0", "league_id": 39}] * 5,
        "recent_away": [{"score": "0-1", "league_id": 39}] * 5,
        "injuries": {"home": {"count": 1}, "away": {"count": 0}},
        "tables": [],
    })
    row = pec.collect_one({"match_id": "sporttery-1", "home": "A", "away": "B",
                           "competition": "英超", "kickoff": "2026-08-23T20:00:00+08:00"})
    audit = row["evidence_audit"]
    assert audit["entries"]["team_stats"]["status"] == "VALID"
    assert audit["entries"]["recent_form"]["status"] == "VALID"
    assert audit["entries"]["injury"]["status"] == "VALID"
    assert audit["entries"]["starting_xi"]["status"] == "PENDING_REFRESH"
    assert audit["evidence_gap"] is True
    assert len(audit["lineup_refresh_schedule"]) == 6


def test_collect_file_writes_sidecar_without_mutating_input(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    source.write_text('{"matches":[{"match_id":"sporttery-1","home":"A","away":"B","kickoff":"2026-08-23T20:00:00+08:00"}]}', encoding="utf-8")
    monkeypatch.setattr(pec.preview, "collect", lambda mid, terms, hist: {"feature": {}, "strength": None,
        "recent_home": [], "recent_away": [], "injuries": {}, "tables": []})
    out = pec.collect_file(source, tmp_path / "out")
    assert out["count"] == 1
    assert (tmp_path / "out" / "sporttery-1.json").exists()
    assert "evidence_audit" not in source.read_text(encoding="utf-8")


def test_audit_exposes_mobile_feature_analysis_without_guessing_labels(monkeypatch):
    monkeypatch.setattr(pec.preview, "collect", lambda mid, terms, hist: {
        "feature": {
            "goalAvg": {"homeGoalAvgCnt": "1.8", "awayGoalAvgCnt": "1.4", "totalLegCnt": 10},
            "lossGoalAvg": {"homeLossGoalAvgCnt": "0.5", "awayLossGoalAvgCnt": "1.5", "totalLegCnt": 10},
            "last": {"homeWinGoalMatchCnt": 3, "homeDrawMatchCnt": 2, "homeLossGoalMatchCnt": 2, "totalLegCnt": 7},
            "eachHomeAway": {"totalLegCnt": 10},
            "sameHomeAway": {"totalLegCnt": 4},
            "eachSameHomeAway": {"totalLegCnt": 10},
        },
        "strength": {"lambda_home": 1.4, "lambda_away": 1.1, "sample_legs": 10},
        "recent_home": [{"score": "1-0", "league_id": 39}] * 10,
        "recent_away": [{"score": "0-1", "league_id": 39}] * 10,
        "injuries": {"home": {}, "away": {}}, "tables": [],
    })
    row = pec.collect_one({"match_id": "sporttery-1", "home": "A", "away": "B",
                           "competition": "日职", "kickoff": "2026-08-23T20:00:00+08:00"})
    analysis = row["facts"]["feature_analysis"]
    assert analysis["source_field_map"]["h2h_last7"] == "feature.last"
    assert analysis["h2h_last7"]["totalLegCnt"] == 7
    assert analysis["goals_avg"]["homeGoalAvgCnt"] == "1.8"
    assert row["evidence_audit"]["entries"]["team_stats"]["value"]["feature_analysis"] == analysis
