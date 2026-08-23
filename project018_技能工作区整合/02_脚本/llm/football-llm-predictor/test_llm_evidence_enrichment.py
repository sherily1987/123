from datetime import datetime, timezone

import llm_evidence_enrichment as lee


COLLECTED = "2026-08-15T13:22:20+00:00"


def test_api_sports_injury_dedup_uses_team_player_and_reason_key():
    row = {"team": {"id": 1}, "player": {"id": 7, "type": "Missing Fixture", "reason": "Knee"}}
    got = lee.ApiSportsClient._dedupe_injuries([row, dict(row),
        {"team": {"id": 1}, "player": {"id": 7, "type": "Questionable", "reason": "Knee"}}])
    assert len(got) == 2


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
                                   "league": {"name": "Premier League"},
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


def test_api_sports_client_marks_one_sided_lineup_as_partial():
    def transport(path, params):
        if path == "/fixtures" and "date" in params:
            return {"response": [{
                "fixture": {"id": 9, "date": "2026-08-16T14:00:00+00:00"},
                "teams": {"home": {"id": 1, "name": "Home"},
                          "away": {"id": 2, "name": "Away"}},
            }]}
        if path == "/fixtures" and "last" in params:
            return {"response": []}
        if path == "/injuries":
            return {"response": []}
        if path == "/fixtures/lineups":
            return {"response": [{"team": {"id": 1}, "startXI": [{"player": {"name": "A"}}]}]}
        raise AssertionError((path, params))

    result = lee.ApiSportsClient(transport=transport).collect_match(
        "Home", "Away", "2026-08-16T14:00:00+00:00")
    assert result["lineups_status"] == "PARTIAL"


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


def test_api_sports_recent_form_excludes_friendlies_and_keeps_official_matches():
    def fixture(league, date):
        return {
            "fixture": {"date": date, "status": {"short": "FT"}},
            "league": {"name": league, "type": "League"},
            "teams": {"home": {"name": "Home"}, "away": {"name": "Away"}},
            "score": {"fulltime": {"home": 1, "away": 0}},
        }

    def transport(path, params):
        if path == "/fixtures" and "date" in params:
            return {"response": [{
                "fixture": {"id": 7, "date": "2026-08-24T16:30:00+00:00"},
                "teams": {"home": {"id": 1, "name": "Home"}, "away": {"id": 2, "name": "Away"}},
            }]}
        if path == "/fixtures" and "last" in params:
            rows = [fixture("Friendlies Clubs", f"2026-08-{20-i:02d}T12:00:00+00:00") for i in range(5)]
            rows.append(fixture("Serie A", "2026-05-20T12:00:00+00:00"))
            return {"response": rows}
        if path in ("/injuries", "/fixtures/lineups"):
            return {"response": []}
        raise AssertionError((path, params))

    result = lee.ApiSportsClient(transport=transport).collect_match(
        "Home", "Away", "2026-08-25T00:30:00+08:00")

    assert [row["league"] for row in result["recent"]["home"]] == ["Serie A"]
    assert result["recent_meta"]["home"]["friendly_excluded"] == 5
    assert "排除友谊赛5场" in lee.render_recent_form(
        result["recent"], COLLECTED, result["recent_meta"]
    )


def test_api_sports_recent_form_excludes_future_and_unplayed_rows():
    def fixture(when, status, score=(1, 0)):
        return {
            "fixture": {"date": when, "status": {"short": status}},
            "league": {"name": "Serie A", "type": "League"},
            "teams": {"home": {"name": "Home"}, "away": {"name": "Away"}},
            "score": {"fulltime": {"home": score[0], "away": score[1]}},
        }

    def transport(path, params):
        if path == "/fixtures" and "date" in params:
            return {"response": [{
                "fixture": {"id": 8, "date": "2026-08-24T16:30:00+00:00"},
                "teams": {"home": {"id": 1, "name": "Home"},
                          "away": {"id": 2, "name": "Away"}},
            }]}
        if path == "/fixtures" and "last" in params:
            return {"response": [
                fixture("2026-08-23T12:00:00+00:00", "FT"),
                fixture("2026-08-25T12:00:00+00:00", "NS"),
                fixture("2026-08-22T12:00:00+00:00", "PST"),
                fixture("2026-08-21T12:00:00+00:00", "FT", (None, None)),
            ]}
        if path in ("/injuries", "/fixtures/lineups"):
            return {"response": []}
        raise AssertionError((path, params))

    result = lee.ApiSportsClient(transport=transport).collect_match(
        "Home", "Away", "2026-08-24T16:30:00+00:00")
    assert all(len(result["recent"][side]) == 1 for side in ("home", "away"))
    assert result["recent"]["home"][0]["date"].startswith("2026-08-23")
