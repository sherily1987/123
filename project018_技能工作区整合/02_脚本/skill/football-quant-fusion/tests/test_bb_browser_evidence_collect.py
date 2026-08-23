import importlib.util
import json
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "bb_browser_evidence_collect.py"
spec = importlib.util.spec_from_file_location("bb_browser_evidence_collect", MODULE)
bec = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(bec)


def _payload():
    return {
        "general": {
            "matchId": "5987811",
            "homeTeam": {"name": "Bodø/Glimt", "id": 8402},
            "awayTeam": {"name": "NEC Nijmegen", "id": 8464},
            "matchTimeUTCDate": "2026-08-25T19:00:00.000Z",
            "started": False,
            "finished": False,
        },
        "header": {"status": {"utcTime": "2026-08-25T19:00:00.000Z", "aggregatedStr": "3 - 1"}},
        "content": {"matchFacts": {
            "teamForm": [
                [{"score": "4 - 0", "resultString": "W"}] * 5,
                [{"score": "1 - 2", "resultString": "L"}] * 5,
            ]
        }, "lineup": {
            "matchId": 5987811,
            "source": "lastStartingLineups",
            "homeTeam": {"formation": "4-3-3", "starters": [{"name": "Home Player"}], "unavailable": [{"name": "Home Injured"}]},
            "awayTeam": {"formation": "3-4-2-1", "starters": [{"name": "Away Player"}], "unavailable": [],
            },
        }},
    }


def test_collect_one_accepts_predicted_xi_as_explicit_nonofficial_evidence(monkeypatch):
    calls = []

    def fake_run(args):
        calls.append(args)
        if args[0] == "open":
            return "tab: trial1\n"
        if args[0] == "eval":
            return json.dumps(_payload(), ensure_ascii=False)
        return "closed\n"

    monkeypatch.setattr(bec, "_run_browser", fake_run)
    row = bec.collect_one(
        {"match_id": "sporttery-1", "home": "Bodø/Glimt", "away": "NEC Nijmegen",
         "kickoff": "2026-08-26T03:00:00+08:00"},
        {"url": "https://www.fotmob.com/matches/bodoglimt-vs-nec-nijmegen/2cov5v", "fotmob_match_id": "5987811"},
        now=bec._parse("2026-08-23T17:45:00+08:00"),
    )
    assert row["status"] == "ok"
    assert row["evidence_audit"]["entries"]["recent_form"]["status"] == "VALID"
    assert row["evidence_audit"]["entries"]["starting_xi"]["status"] == "PREDICTED"
    assert row["evidence_audit"]["entries"]["starting_xi"]["missing_reason"] == "PREDICTED_XI_NOT_CONFIRMED"
    assert "starting_xi" not in row["evidence_audit"]["missing_fields"]
    assert row["evidence_audit"]["entries"]["suspensions"]["status"] == "UNAVAILABLE"
    assert any(args[0] == "eval" for args in calls)
    assert any(args[0] == "close" for args in calls)


def test_collect_one_without_mapping_emits_browser_task():
    row = bec.collect_one(
        {"match_id": "sporttery-2", "home": "A", "away": "B",
         "kickoff": "2026-08-26T03:00:00+08:00"},
        None,
        now=bec._parse("2026-08-23T17:45:00+08:00"),
    )
    assert row["status"] == "pending_browser_task"
    assert row["browser_task"]["reason"] == "FOTMOB_MATCH_URL_REQUIRED"


def test_discover_sources_uses_match_identity_not_fixed_league_url(monkeypatch):
    calls = []

    def fake_run(args):
        calls.append(args)
        if args[0] == "open":
            return "tab: discover1\n"
        if args[0] == "eval":
            return json.dumps([
                "https://www.uefa.com/uefachampionsleague/match/2049221--bodo-glimt-vs-n-e-c/",
                "https://www.fotmob.com/matches/bodoglimt-vs-nec-nijmegen/2cov5v",
            ])
        return "closed\n"

    monkeypatch.setattr(bec, "_run_browser", fake_run)
    row = bec.discover_sources({
        "match_id": "sporttery-1", "competition": "Champions League",
        "home": "Bodø/Glimt", "away": "NEC Nijmegen",
        "kickoff": "2026-08-26T03:00:00+08:00",
    })
    assert row["status"] == "source_candidates_found"
    assert row["official_candidates"][0].startswith("https://www.uefa.com/")
    assert row["third_party_candidates"][0].startswith("https://www.fotmob.com/")
    assert any(args[0] == "close" for args in calls)
