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
                           "competition": "英超", "kickoff": "2026-08-25T20:00:00+08:00"})
    audit = row["evidence_audit"]
    assert audit["entries"]["team_stats"]["status"] == "VALID"
    assert audit["entries"]["recent_form"]["status"] == "VALID"
    assert audit["entries"]["injury"]["status"] == "VALID"
    assert audit["entries"]["starting_xi"]["status"] == "PENDING_REFRESH"
    assert audit["evidence_gap"] is True
    assert len(audit["lineup_refresh_schedule"]) == 6


def test_collect_file_writes_sidecar_without_mutating_input(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    source.write_text('{"matches":[{"match_id":"sporttery-1","home":"A","away":"B","kickoff":"2026-08-25T20:00:00+08:00"}]}', encoding="utf-8")
    monkeypatch.setattr(pec.preview, "collect", lambda mid, terms, hist: {"feature": {}, "strength": None,
        "recent_home": [], "recent_away": [], "injuries": {}, "tables": []})
    out = pec.collect_file(source, tmp_path / "out")
    assert out["count"] == 1
    assert (tmp_path / "out" / "sporttery-1.json").exists()
    assert "evidence_audit" not in source.read_text(encoding="utf-8")
    assert out["source_health"]["api_sports"]["NOT_REQUESTED"] == 1
    assert out["source_health"]["evidence_gap"] == 1


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
                           "competition": "日职", "kickoff": "2026-08-25T20:00:00+08:00"})
    analysis = row["facts"]["feature_analysis"]
    assert analysis["source_field_map"]["h2h_last7"] == "feature.last"
    assert analysis["h2h_last7"]["totalLegCnt"] == 7
    assert analysis["goals_avg"]["homeGoalAvgCnt"] == "1.8"
    assert row["evidence_audit"]["entries"]["team_stats"]["value"]["feature_analysis"] == analysis
    assert row["evidence_audit"]["entries"]["injury"]["status"] == "EMPTY_UNCONFIRMED"
    assert row["evidence_audit"]["entries"]["suspensions"]["status"] == "EMPTY_UNCONFIRMED"


def test_missing_injury_payload_remains_unavailable(monkeypatch):
    monkeypatch.setattr(pec.preview, "collect", lambda mid, terms, hist: {
        "feature": {}, "strength": None, "recent_home": [], "recent_away": [],
        "injuries": {}, "tables": [],
    })
    row = pec.collect_one({"match_id": "sporttery-2", "home": "A", "away": "B",
                           "kickoff": "2026-08-25T20:00:00+08:00"})
    assert row["evidence_audit"]["entries"]["injury"]["status"] == "UNAVAILABLE"
    assert row["evidence_audit"]["entries"]["suspensions"]["status"] == "UNAVAILABLE"
    assert row["evidence_audit"]["api_sports_attempt"]["status"] == "NOT_REQUESTED"


def test_api_sports_enrichment_fills_form_injury_and_confirmed_lineups(monkeypatch):
    monkeypatch.setenv("ENABLE_API_SPORTS_EVIDENCE", "1")
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-key")
    monkeypatch.setattr(pec.preview, "collect", lambda mid, terms, hist: {
        "feature": {}, "strength": None, "recent_home": [], "recent_away": [],
        "injuries": {}, "tables": [],
    })

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def collect_match(self, home, away, kickoff, *, aliases=None):
            return {
                "status": "ok", "fixture_id": 42,
                "team_ids": {"home": 10, "away": 20},
                "recent": {
                    "home": [{"date": "2026-08-20", "league": "英超", "home": "A", "away": "X", "score_90": "1-0", "status": "FT"}] * 5,
                    "away": [{"date": "2026-08-20", "league": "英超", "home": "Y", "away": "B", "score_90": "0-1", "status": "FT"}] * 5,
                },
                "injuries": [{"team": {"id": 10}, "player": {"name": "A1", "reason": "Knee"}}],
                "lineups": [{"team": {"id": 10}, "startXI": [{"player": {"name": "A1"}}]},
                            {"team": {"id": 20}, "startXI": [{"player": {"name": "B1"}}]}],
            }

    monkeypatch.setattr(pec.enrichment, "ApiSportsClient", FakeClient)
    row = pec.collect_one({"match_id": "sporttery-3", "home": "A", "away": "B",
                           "competition": "英超", "kickoff": "2026-08-25T20:00:00+08:00"})
    entries = row["evidence_audit"]["entries"]
    assert entries["recent_form"]["status"] == "VALID"
    assert entries["recent_form"]["source_id"] == "api-sports.io"
    assert entries["injury"]["status"] == "VALID"
    assert entries["starting_xi"]["status"] == "VALID"
    assert row["facts"]["api_sports"]["fixture_id"] == 42
    assert row["evidence_audit"]["api_sports_attempt"]["status"] == "ok"


def test_api_fixture_id_can_be_supplied_inside_evidence_sources(monkeypatch):
    monkeypatch.setenv("ENABLE_API_SPORTS_EVIDENCE", "1")
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-key")
    monkeypatch.setattr(pec.preview, "collect", lambda mid, terms, hist: {
        "feature": {}, "strength": None, "recent_home": [], "recent_away": [],
        "injuries": {}, "tables": [],
    })
    seen = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        def collect_match(self, home, away, kickoff, *, aliases=None, fixture_id=None):
            seen.append(fixture_id)
            return {"status": "UNAVAILABLE", "reason": "fixture_not_ready"}
    monkeypatch.setattr(pec.enrichment, "ApiSportsClient", FakeClient)
    pec.collect_one({"match_id": "sporttery-7", "home": "A", "away": "B",
                     "kickoff": "2026-08-25T20:00:00+08:00",
                     "evidence_sources": {"api_sports_fixture_id": 7788}})
    assert seen == [7788]


def test_audit_does_not_upgrade_one_sided_api_lineup_to_valid(monkeypatch):
    monkeypatch.setenv("ENABLE_API_SPORTS_EVIDENCE", "1")
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-key")
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def collect_match(self, *args, **kwargs):
            return {
                "status": "ok", "fixture_id": 43,
                "recent": {"home": [{"league": "英超"}] * 5,
                            "away": [{"league": "英超"}] * 5},
                "injuries": [],
                "lineups": [{"team": {"id": 10}, "startXI": [{"player": {"name": "A1"}}]}],
                "lineups_status": "PARTIAL",
            }

    monkeypatch.setattr(pec.enrichment, "ApiSportsClient", FakeClient)
    row = pec.collect_one({"match_id": "sporttery-4", "home": "A", "away": "B",
                           "competition": "英超", "kickoff": "2026-08-25T20:00:00+08:00"})
    entry = row["evidence_audit"]["entries"]["starting_xi"]
    assert entry["status"] == "PARTIAL"
    assert "starting_xi" in row["evidence_audit"]["missing_fields"]


def test_api_gap_routes_to_scrapling_and_projects_only_missing_fields(monkeypatch):
    monkeypatch.setattr(pec.preview, "collect", lambda mid, terms, hist: {
        "feature": {}, "strength": None, "recent_home": [], "recent_away": [],
        "injuries": {}, "tables": [],
    })
    calls = []
    def fake_scrapling(match, audit):
        calls.append((match["match_id"], tuple(audit["missing_fields"])))
        return {
            "status": "ok", "provider": "scrapling_generic", "research_only": True,
            "evidence_audit": {"entries": {
                "recent_form": {"status": "VALID", "value": {"home": [1] * 5, "away": [2] * 5},
                                 "source_id": "sportsmole.preview", "source_url": "https://example.test"},
                "starting_xi": {"status": "PREDICTED", "value": {"home": ["A"], "away": ["B"]},
                                "source_id": "sportsmole.preview", "source_url": "https://example.test"},
            }}
        }
    monkeypatch.setattr(pec, "_scrapling_fallback", fake_scrapling)
    row = pec.collect_one({"match_id": "sporttery-5", "home": "A", "away": "B",
                           "kickoff": "2026-08-25T20:00:00+08:00",
                           "evidence_sources": {"scrapling_url": "https://example.test"}})
    assert calls and calls[0][0] == "sporttery-5"
    assert row["facts"]["scrapling"]["research_only"] is True
    # PREDICTED is intentionally not promoted to VALID; API/official evidence
    # remains authoritative for production gating.
    assert row["evidence_audit"]["entries"]["recent_form"]["status"] == "VALID"
    assert row["evidence_audit"]["entries"]["starting_xi"]["status"] == "PREDICTED"


def test_scrapling_is_attempted_before_api_and_api_only_fills_gaps(monkeypatch):
    monkeypatch.setenv("ENABLE_API_SPORTS_EVIDENCE", "1")
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-key")
    monkeypatch.setattr(pec.preview, "collect", lambda mid, terms, hist: {
        "feature": {}, "strength": None, "recent_home": [], "recent_away": [],
        "injuries": {}, "tables": [],
    })
    calls = []

    def fake_scrapling(match, audit):
        calls.append("scrapling")
        return {"status": "ok", "research_only": True, "evidence_audit": {"entries": {
            "recent_form": {"status": "VALID", "value": {"home": ["S"] * 5, "away": ["S"] * 5},
                             "source_id": "dynamic.source", "source_url": "https://example.test"},
            "starting_xi": {"status": "PREDICTED", "value": {"home": ["S"], "away": ["S"]},
                             "source_id": "dynamic.source", "source_url": "https://example.test"},
        }}}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def collect_match(self, *args, **kwargs):
            calls.append("api")
            return {"status": "ok", "fixture_id": 99,
                    "recent": {"home": [{"league": "英超"}] * 5,
                                "away": [{"league": "英超"}] * 5},
                    "injuries": [], "lineups": []}

    monkeypatch.setattr(pec, "_scrapling_fallback", fake_scrapling)
    monkeypatch.setattr(pec.enrichment, "ApiSportsClient", FakeClient)
    row = pec.collect_one({"match_id": "sporttery-8", "home": "A", "away": "B",
                           "competition": "英超", "kickoff": "2026-08-25T20:00:00+08:00"})
    assert calls == ["scrapling", "api"]
    entries = row["evidence_audit"]["entries"]
    assert entries["recent_form"]["source_id"] == "dynamic.source"
    assert entries["starting_xi"]["source_id"] == "dynamic.source"
    assert row["facts"]["api_sports"]["fixture_id"] == 99


def test_collect_file_injects_match_scoped_scrapling_url_map(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    source.write_text('{"matches":[{"match_id":"sporttery-6","home":"A","away":"B","kickoff":"2026-08-25T20:00:00+08:00"}]}', encoding="utf-8")
    mapping = tmp_path / "sources.json"
    mapping.write_text('{"sporttery-6":{"scrapling_url":"https://league.test/match/6","source_id":"league.preview"}}', encoding="utf-8")
    seen = []
    monkeypatch.setattr(pec, "collect_one", lambda match, **kwargs: (
        seen.append(match) or {"evidence_audit": {"evidence_gap": True}}
    ))
    pec.collect_file(source, tmp_path / "out", scrapling_url_map=mapping)
    assert seen[0]["evidence_sources"]["scrapling_url"] == "https://league.test/match/6"
