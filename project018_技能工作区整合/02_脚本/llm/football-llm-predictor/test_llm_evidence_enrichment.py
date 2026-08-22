from datetime import datetime, timedelta, timezone

import llm_evidence_enrichment as lee


COLLECTED = "2026-08-15T13:22:20+00:00"


def test_render_sporttery_markets_keeps_crs_ttg_and_hafu():
    raw = {
        "fixed_bonus_url": "https://webapi.sporttery.cn/match/2040898",
        "model_odds": [2.37, 3.17, 2.55],
        "crs": {"1-0": 9.5, "1-1": 5.7},
        "ttg": {"2": 3.5, "3": 3.65},
        "hafu": {"hh": 4.2, "dd": 5.35, "aa": 4.4},
    }
    text = lee.render_sporttery_markets(raw, COLLECTED)
    assert "CRS" in text and "1-0=9.5" in text
    assert "TTG" in text and "2=3.5" in text
    assert "HAFU" in text and "hh=4.2" in text
    assert "source(https://webapi.sporttery.cn/match/2040898)" in text
    assert f"collected_at({COLLECTED})" in text


def test_render_recent_form_limits_each_team_to_five():
    row = {"date": "2026-08-10T12:00:00+00:00", "league": "Friendly",
           "home": "Arsenal", "away": "Como", "score_90": "1-1", "status": "FT"}
    text = lee.render_recent_form({"home": [dict(row, date=f"2026-08-{10-i:02d}T12:00:00+00:00") for i in range(6)],
                                   "away": [dict(row, home="Man City", away="Inter") for _ in range(6)]}, COLLECTED)
    assert text.count("- 主队近况:") == 5
    assert text.count("- 客队近况:") == 5


def test_refresh_due_has_closed_t75_open_kickoff_boundary():
    kickoff = datetime(2026, 8, 16, 14, 0, tzinfo=timezone.utc)
    assert lee.refresh_due(kickoff, kickoff - timedelta(minutes=76)) is False
    assert lee.refresh_due(kickoff, kickoff - timedelta(minutes=75)) is True
    assert lee.refresh_due(kickoff, kickoff - timedelta(minutes=1)) is True
    assert lee.refresh_due(kickoff, kickoff) is False
    assert lee.refresh_due(kickoff, kickoff + timedelta(seconds=1)) is False


def test_write_canonical_snapshot_archives_previous_content(tmp_path):
    path = tmp_path / "evidence_001_match_mcp.md"
    lee.write_canonical_snapshot(path, "first", COLLECTED)
    result = lee.write_canonical_snapshot(path, "second", "2026-08-15T14:00:00+00:00")
    assert path.read_text(encoding="utf-8") == "second"
    archived = list((tmp_path / "snapshots").glob("*.md"))
    assert len(archived) == 1 and archived[0].read_text(encoding="utf-8") == "first"
    assert result["archived"] == str(archived[0])


def test_api_sports_client_collects_recent_and_marks_empty_availability():
    calls = []
    def transport(path, params):
        calls.append((path, dict(params)))
        if path == "/fixtures" and "date" in params:
            return {"response": [{"fixture": {"id": 1582365, "date": "2026-08-16T14:00:00+00:00"},
                                   "teams": {"home": {"id": 42, "name": "Arsenal"},
                                             "away": {"id": 50, "name": "Manchester City"}}}]}
        if path == "/fixtures" and "last" in params:
            name = "Arsenal" if params["team"] == 42 else "Manchester City"
            return {"response": [{"fixture": {"date": "2026-08-10T12:00:00+00:00", "status": {"short": "FT"}},
                                   "league": {"name": "Friendly"},
                                   "teams": {"home": {"name": name}, "away": {"name": "Opponent"}},
                                   "score": {"fulltime": {"home": 2, "away": 1}},
                                   "goals": {"home": 2, "away": 1}}]}
        if path in ("/injuries", "/fixtures/lineups"):
            return {"response": []}
        raise AssertionError((path, params))
    client = lee.ApiSportsClient(transport=transport)
    result = client.collect_match("Arsenal", "Manchester City", "2026-08-16T14:00:00+00:00")
    assert result["status"] == "ok" and result["fixture_id"] == 1582365
    assert len(result["recent"]["home"]) == 1 and len(result["recent"]["away"]) == 1
    assert result["injuries_status"] == "UNAVAILABLE"
    assert result["lineups_status"] == "UNAVAILABLE"


def test_api_sports_fixture_query_uses_utc_date_for_offset_kickoff():
    seen = []
    def transport(path, params):
        if path == "/fixtures" and "date" in params:
            seen.append(params["date"])
            return {"response": []}
        raise AssertionError((path, params))
    lee.ApiSportsClient(transport=transport).collect_match(
        "A", "B", "2026-08-16T01:00:00+08:00")
    assert seen == ["2026-08-15"]


def test_api_sports_client_matches_fixture_against_verified_alias_lists():
    def transport(path, params):
        if path == "/fixtures" and "date" in params:
            return {"response": [{
                "fixture": {"id": 1492340, "date": "2026-08-24T23:00:00+00:00"},
                "teams": {"home": {"id": 1, "name": "Botafogo"},
                          "away": {"id": 2, "name": "Atletico Paranaense"}},
            }]}
        if path == "/fixtures" and "last" in params:
            return {"response": []}
        if path in ("/injuries", "/fixtures/lineups"):
            return {"response": []}
        raise AssertionError((path, params))

    result = lee.ApiSportsClient(transport=transport).collect_match(
        ["博塔弗戈", "Botafogo"], ["巴竞技", "Atletico Paranaense"],
        "2026-08-25T07:00:00+08:00",
    )

    assert result["status"] == "ok" and result["fixture_id"] == 1492340
