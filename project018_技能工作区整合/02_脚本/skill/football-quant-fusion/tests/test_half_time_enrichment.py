from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "half_time_enrichment.py"
SPEC = importlib.util.spec_from_file_location("half_time_enrichment", MODULE)
enrichment = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(enrichment)


def record():
    return {"match_id": "sporttery-1", "match": {
        "home": "Start", "away": "Viking", "kickoff": "2026-08-02T00:00:00+08:00",
    }}


def result(home=0, away=3):
    return {"status": "finished", "settlement_scope": "90min",
            "score_90": {"home": home, "away": away}}


def api_sports_fixture(home=0, away=3, ht_home=0, ht_away=3):
    return {"fixture": {"id": 1494722, "date": "2026-08-02T00:00:00+08:00"},
            "teams": {"home": {"name": "Start"}, "away": {"name": "Viking"}},
            "goals": {"home": home, "away": away},
            "score": {"halftime": {"home": ht_home, "away": ht_away},
                      "fulltime": {"home": home, "away": away}}}


def test_match_accepts_only_identity_and_fulltime_consistent_half_time_fixture():
    fixture = enrichment.normalize_fixture(api_sports_fixture())

    evidence = enrichment.match_finished_fixture(record(), result(), fixture, aliases={})

    assert evidence == {
        "match_id": "sporttery-1", "status": "verified", "matched_by": "team_time_fulltime",
        "provider": "api-sports.io", "provider_fixture_id": "1494722",
        "record_kickoff": "2026-08-02T00:00:00+08:00", "provider_kickoff": "2026-08-02T00:00:00+08:00",
        "score_ht": {"home": 0, "away": 3}, "score_90": {"home": 0, "away": 3},
    }


def test_match_rejects_fixture_when_its_fulltime_score_disagrees():
    fixture = enrichment.normalize_fixture(api_sports_fixture(home=1, away=3))

    evidence = enrichment.match_finished_fixture(record(), result(), fixture, aliases={})

    assert evidence == {"match_id": "sporttery-1", "status": "fulltime_conflict"}


def test_match_accepts_one_of_explicitly_verified_aliases_only():
    chinese_record = record()
    chinese_record["match"]["home"] = "斯达"
    evidence = enrichment.match_finished_fixture(
        chinese_record, result(), enrichment.normalize_fixture(api_sports_fixture()),
        aliases={"斯达": ["Start", "IK Start"]})

    assert evidence["status"] == "verified"


def test_build_marks_multiple_valid_fixtures_ambiguous_and_missing_half_time_unavailable():
    ambiguous = enrichment.build_half_time_evidence(
        [(record(), result())], [enrichment.normalize_fixture(api_sports_fixture()),
                                 enrichment.normalize_fixture(api_sports_fixture())], aliases={})
    unavailable = enrichment.build_half_time_evidence(
        [(record(), result())], [enrichment.normalize_fixture(api_sports_fixture(ht_home=None, ht_away=None))], aliases={})

    assert ambiguous["rows"] == [{"match_id": "sporttery-1", "status": "ambiguous_match", "candidates": 2}]
    assert unavailable["rows"] == [{"match_id": "sporttery-1", "status": "missing_half_time_score"}]


def test_load_fixture_payload_accepts_api_sports_response_envelope():
    fixtures = enrichment.load_fixture_payload({"response": [api_sports_fixture()]})

    assert fixtures == [enrichment.normalize_fixture(api_sports_fixture())]
