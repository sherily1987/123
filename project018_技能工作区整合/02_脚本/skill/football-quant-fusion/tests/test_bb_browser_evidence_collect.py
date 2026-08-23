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
    assert row["evidence_audit"]["entries"]["suspensions"]["status"] == "EMPTY_UNCONFIRMED"
    assert any(args[0] == "eval" for args in calls)
    assert any(args[0] == "close" for args in calls)


def test_collect_one_attaches_official_page_probe_without_changing_lineup_status(monkeypatch):
    def fake_run(args):
        if args[0] == "open":
            return "tab: official-probe\n"
        if args[0] == "eval":
            return json.dumps(_payload(), ensure_ascii=False)
        return "closed\n"

    monkeypatch.setattr(bec, "_run_browser", fake_run)
    monkeypatch.setattr(bec, "_probe_official_page", lambda match, url: {
        "status": "ok", "source_url": url, "lineup_status": "LINEUP_PENDING"
    })
    row = bec.collect_one(
        {"match_id": "sporttery-1", "home": "Bodø/Glimt", "away": "NEC Nijmegen",
         "kickoff": "2026-08-26T03:00:00+08:00"},
        {"url": "https://www.fotmob.com/matches/a/x", "fotmob_match_id": "5987811",
         "official_url": "https://www.uefa.com/match/1"},
        now=bec._parse("2026-08-23T17:45:00+00:00"),
    )
    assert row["official_page_probe"]["status"] == "ok"
    assert row["official_page_probe"]["lineup_status"] == "LINEUP_PENDING"
    assert row["evidence_audit"]["entries"]["starting_xi"]["status"] == "PREDICTED"


def test_collect_one_uses_scrapling_when_fotmob_api_is_unavailable(monkeypatch):
    monkeypatch.setattr(bec, "_run_browser", lambda args: (_ for _ in ()).throw(RuntimeError("api blocked")))
    monkeypatch.setattr(bec, "_scrapling_fotmob_snapshot", lambda match, mapping, collected_at: {
        "schema_version": "scrapling-fotmob-evidence-1.0",
        "provider": "fotmob_via_scrapling_dynamic", "research_only": True,
        "match_id": match["match_id"], "evidence_audit": {
            "entries": {"starting_xi": {"status": "PREDICTED"}},
            "missing_fields": ["team_stats"], "evidence_gap": True,
        },
    })

    row = bec.collect_one(
        {"match_id": "sporttery-1", "home": "Bodø/Glimt", "away": "NEC Nijmegen",
         "kickoff": "2026-08-26T03:00:00+00:00"},
        {"url": "https://www.fotmob.com/matches/a/x", "fotmob_match_id": "5987811",
         "scrapling_fallback": True},
        now=bec._parse("2026-08-23T17:45:00+00:00"),
    )
    assert row["status"] == "ok"
    assert row["provider"] == "fotmob_via_scrapling_dynamic"
    assert row["research_only"] is True


def test_collect_one_uses_scrapling_for_missing_api_fields_and_merges_valid_entries(monkeypatch):
    def fake_run(args):
        if args[0] == "open":
            return "tab: partial-api\n"
        if args[0] == "eval":
            return json.dumps(_payload(), ensure_ascii=False)
        return "closed\n"

    monkeypatch.setattr(bec, "_run_browser", fake_run)
    monkeypatch.setattr(bec, "_scrapling_fotmob_snapshot", lambda match, mapping, collected_at: {
        "provider": "fotmob_via_scrapling_dynamic", "research_only": True,
        "evidence_audit": {"entries": {
            "team_stats": {"status": "EXPLICIT_XG", "value": {"xg": {"home": 1.1, "away": 0.8}},
                            "source_id": "fotmob.scrapling.dynamic"},
        }}
    })
    row = bec.collect_one(
        {"match_id": "sporttery-1", "home": "Bodø/Glimt", "away": "NEC Nijmegen",
         "kickoff": "2026-08-26T03:00:00+00:00"},
        {"url": "https://www.fotmob.com/matches/a/x", "fotmob_match_id": "5987811",
         "scrapling_fallback": True},
        now=bec._parse("2026-08-23T17:45:00+00:00"),
    )
    assert row["evidence_audit"]["entries"]["team_stats"]["status"] == "EXPLICIT_XG"
    assert row["scrapling_fallback_used"] is True


def test_collect_one_supports_generic_scrapling_source_without_fotmob_id(monkeypatch):
    called = []

    def fake_generic(match, mapping, collected_at):
        called.append(mapping["scrapling_url"])
        return {"provider": "league_preview", "research_only": True,
                "evidence_audit": {"missing_fields": ["team_stats"], "evidence_gap": True}}

    monkeypatch.setattr(bec, "_scrapling_generic_snapshot", fake_generic)
    row = bec.collect_one(
        {"match_id": "sporttery-generic", "home": "A", "away": "B",
         "kickoff": "2026-08-26T03:00:00+00:00"},
        {"scrapling_url": "https://league.example/match/1", "source_id": "league.example.preview",
         "provider": "league_preview", "scrapling_fallback": True},
        now=bec._parse("2026-08-23T17:45:00+00:00"),
    )
    assert row["status"] == "ok"
    assert row["provider"] == "league_preview"
    assert called == ["https://league.example/match/1"]


def test_collect_one_tries_ordered_scrapling_sources_and_records_failure(monkeypatch):
    called = []

    def fake_generic(match, mapping, collected_at):
        url = mapping["scrapling_url"]
        called.append(url)
        if url.endswith("blocked"):
            raise RuntimeError("turnstile")
        return {"provider": mapping["provider"], "research_only": True,
                "evidence_audit": {"missing_fields": ["team_stats"], "evidence_gap": True}}

    monkeypatch.setattr(bec, "_scrapling_generic_snapshot", fake_generic)
    row = bec.collect_one(
        {"match_id": "sporttery-chain", "home": "A", "away": "B",
         "kickoff": "2026-08-26T03:00:00+00:00"},
        {"scrapling_sources": [
            {"scrapling_url": "https://league.example/blocked", "provider": "blocked"},
            {"scrapling_url": "https://league.example/preview", "provider": "preview"},
        ]},
        now=bec._parse("2026-08-23T17:45:00+00:00"),
    )
    assert row["status"] == "ok"
    assert row["provider"] == "preview"
    assert called == ["https://league.example/blocked", "https://league.example/preview"]
    assert row["scrapling_attempts"][0]["status"] == "error"
    assert row["scrapling_attempts"][1]["status"] == "ok"


def test_mapping_predicted_xi_overlay_keeps_media_provenance(monkeypatch):
    def fake_run(args):
        if args[0] == "open":
            return "tab: trial2\n"
        if args[0] == "eval":
            return json.dumps(_payload(), ensure_ascii=False)
        return "closed\n"

    monkeypatch.setattr(bec, "_run_browser", fake_run)
    row = bec.collect_one(
        {"match_id": "sporttery-3", "home": "Bodø/Glimt", "away": "NEC Nijmegen",
         "kickoff": "2026-08-26T03:00:00+08:00"},
        {"url": "https://www.fotmob.com/matches/x/abc", "fotmob_match_id": "5987811",
         "predicted_xi": {"source": "sportsmole.predicted", "home": [{"name": "H"}],
                          "away": [{"name": "A"}], "home_formation": "4-3-3"},
         "predicted_xi_source_url": "https://example.test/preview"},
        now=bec._parse("2026-08-23T17:45:00+08:00"),
    )
    xi = row["evidence_audit"]["entries"]["starting_xi"]
    assert xi["status"] == "PREDICTED"
    assert xi["source_id"] == "fotmob.bb_browser"
    assert xi["source_url"] == "https://example.test/preview"
    assert xi["value"]["home"] == [{"name": "H"}]


def test_collect_file_normalizes_nested_sporttery_identity_for_pending_tasks(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"matches": [{
        "home": "A", "away": "B", "competition": "测试联赛",
        "kickoff": "2026-08-26T03:00:00+08:00",
        "sporttery_meta": {"match_id": 2040999},
    }]}), encoding="utf-8")
    output = tmp_path / "out"
    report = bec.collect_file(source, output, None, discover=False)
    assert report["rows"][0]["match_id"] == "sporttery-2040999"
    assert report["rows"][0]["status"] == "pending_browser_task"
    task = json.loads((output / "browser_tasks.json").read_text(encoding="utf-8"))[0]
    assert task["match_id"] == "sporttery-2040999"


def test_collect_file_discovery_keeps_nested_identity(monkeypatch, tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"matches": [{
        "home": "A", "away": "B", "competition": "测试联赛",
        "kickoff": "2026-08-26T03:00:00+08:00",
        "sporttery_meta": {"match_id": 2050001},
    }]}), encoding="utf-8")
    monkeypatch.setattr(bec, "discover_sources", lambda match: {"status": "source_candidates_found"})
    report = bec.collect_file(source, tmp_path / "out", None, discover=True)
    assert report["rows"][0]["match_id"] == "sporttery-2050001"
    assert report["rows"][0]["browser_task"]["match"]["match_id"] == "sporttery-2050001"


def test_collect_one_without_mapping_emits_browser_task():
    row = bec.collect_one(
        {"match_id": "sporttery-2", "home": "A", "away": "B",
         "kickoff": "2026-08-26T03:00:00+08:00"},
        None,
        now=bec._parse("2026-08-23T17:45:00+08:00"),
    )
    assert row["status"] == "pending_browser_task"
    assert row["browser_task"]["reason"] == "FOTMOB_MATCH_URL_REQUIRED"


def test_empty_unavailable_fields_are_not_confirmed_clear():
    payload = _payload()
    payload["content"]["lineup"]["homeTeam"]["unavailable"] = []
    payload["content"]["lineup"]["awayTeam"]["unavailable"] = []
    row = bec._snapshot(
        {"match_id": "sporttery-3", "home": "A", "away": "B"},
        payload,
        "https://www.fotmob.com/matches/a-vs-b/x",
        "2026-08-23T17:45:00+08:00",
    )
    injury = row["evidence_audit"]["entries"]["injury"]
    assert injury["status"] == "EMPTY_UNCONFIRMED"
    assert "injury" in row["evidence_audit"]["missing_fields"]


def test_discover_sources_uses_match_identity_not_fixed_league_url(monkeypatch):
    calls = []

    def fake_run(args):
        calls.append(args)
        if args[0] == "open":
            return "tab: discover1\n"
        if args[0] == "eval":
            return json.dumps([
                "https://www.google.com.hk/search?q=should-be-ignored",
                "https://www.google.com/search?q=should-be-ignored-too",
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
    assert all("google" not in url for url in row["unclassified_candidates"])
    assert any(args[0] == "close" for args in calls)


def test_discover_sources_classifies_serie_a_official_domain(monkeypatch):
    def fake_run(args):
        if args[0] == "open":
            return "tab: seriea\n"
        if args[0] == "eval":
            return json.dumps(["https://www.legaseriea.it/en/match/serie-a/test"])
        return "closed\n"

    monkeypatch.setattr(bec, "_run_browser", fake_run)
    row = bec.discover_sources({
        "match_id": "sporttery-4", "competition": "意甲", "home": "A", "away": "B",
        "kickoff": "2026-08-26T03:00:00+00:00",
    })
    assert row["official_candidates"] == ["https://www.legaseriea.it/en/match/serie-a/test"]


def test_snapshot_extracts_team_stats_and_suspensions_without_inventing_clear_status():
    payload = _payload()
    payload["content"]["stats"] = {
        "periods": [{"period": "ALL", "stats": [
            {"title": "Expected goals (xG)", "stats": [
                {"key": "home", "value": "1.42"},
                {"key": "away", "value": "0.87"},
            ]}
        ]}]
    }
    payload["content"]["lineup"]["homeTeam"]["unavailable"] = [
        {"name": "Home Suspended", "unavailability": {"type": "suspension"}}
    ]
    row = bec._snapshot(
        {"match_id": "sporttery-4", "home": "A", "away": "B"},
        payload,
        "https://www.fotmob.com/matches/a-vs-b/x",
        "2026-08-23T17:45:00+00:00",
    )
    stats = row["evidence_audit"]["entries"]["team_stats"]
    suspensions = row["evidence_audit"]["entries"]["suspensions"]
    assert stats["status"] == "VALID"
    assert stats["value"]["xg"]["home"] == "1.42"
    assert suspensions["status"] == "VALID"
    assert suspensions["value"]["home"][0]["player"] == "Home Suspended"


def test_snapshot_keeps_missing_stats_and_suspensions_as_gaps():
    row = bec._snapshot(
        {"match_id": "sporttery-5", "home": "A", "away": "B"},
        _payload(),
        "https://www.fotmob.com/matches/a-vs-b/x",
        "2026-08-23T17:45:00+00:00",
    )
    assert row["evidence_audit"]["entries"]["team_stats"]["status"] == "UNAVAILABLE"
    assert row["evidence_audit"]["entries"]["suspensions"]["status"] == "EMPTY_UNCONFIRMED"


def test_discover_sources_accepts_match_specific_official_domains(monkeypatch):
    def fake_run(args):
        if args[0] == "open":
            return "tab: discover2\n"
        if args[0] == "eval":
            return json.dumps(["https://www.example-league.org/matches/a-vs-b",
                               "https://www.fotmob.com/matches/a-vs-b/x"])
        return "closed\n"

    monkeypatch.setattr(bec, "_run_browser", fake_run)
    row = bec.discover_sources({
        "competition": "Example League", "home": "A", "away": "B",
        "kickoff": "2026-08-26T03:00:00+08:00",
        "official_domains": ["example-league.org"],
    })
    assert row["official_candidates"] == ["https://www.example-league.org/matches/a-vs-b"]


def test_snapshot_preserves_explicit_source_identity_for_other_leagues():
    row = bec._snapshot(
        {"match_id": "sporttery-6", "home": "A", "away": "B"},
        _payload(),
        "https://www.example-league.org/matches/a-vs-b",
        "2026-08-23T17:45:00+00:00",
        source_id="example_league.official_browser",
        provider="example_league_via_bb_browser",
    )
    assert row["provider"] == "example_league_via_bb_browser"
    assert row["evidence_audit"]["entries"]["recent_form"]["source_id"] == "example_league.official_browser"
