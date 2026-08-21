from datetime import datetime, timezone

import fotmob_league as fm


SAMPLE_LEAGUE = {
    "details": {"id": 223, "name": "J. League"},
    "table": [{"data": {"table": {"xg": [{
        "name": "Sanfrecce Hiroshima", "id": 6224, "played": 2,
        "xg": 5.9, "xgConceded": 0.6, "xPoints": 5.7, "xgDiff": 1.0, "position": 1,
    }]}}}],
    "fixtures": {"allMatches": [{
        "id": "5803519",
        "home": {"name": "Yokohama F.Marinos"},
        "away": {"name": "Kashima Antlers"},
        "status": {"utcTime": "2026-08-07T10:25:00Z", "finished": True, "scoreStr": "3 - 4"},
    }]},
}


def test_resolve_and_parse_utc():
    assert fm.resolve_league("日职") == 223
    assert fm.resolve_league("韩职") == 9080
    assert fm.resolve_league("芬超") == 51
    assert fm.resolve_league("沙职") == 536
    assert fm.resolve_league("日乙") == 8974
    assert fm.parse_utc("2026-08-07T10:25:00Z").tzinfo is not None


def test_unknown_league_is_rejected_rather_than_guessed():
    try:
        fm.resolve_league("中超")
    except ValueError as exc:
        assert "未知联赛" in str(exc)
    else:
        raise AssertionError("unknown league must fail")


def test_table_xg_coverage_is_explicit():
    assert 223 in fm.TABLE_XG_IDS
    assert 536 in fm.TABLE_XG_IDS
    assert 9080 in fm.NO_TABLE_XG_IDS
    assert 51 in fm.NO_TABLE_XG_IDS
    assert fm.TABLE_XG_IDS.isdisjoint(fm.NO_TABLE_XG_IDS)


def test_cutoff_rejects_naive():
    try:
        fm.require_cutoff("2026-08-16 12:00:00")
    except ValueError as exc:
        assert "offset" in str(exc) or "时区" in str(exc)
    else:
        raise AssertionError("naive cutoff must fail")


def test_table_and_fixtures():
    xg = fm.table_xg(SAMPLE_LEAGUE)
    assert xg[0]["team"] == "Sanfrecce Hiroshima"
    assert xg[0]["xg"] == 5.9
    fx = fm.fixtures(SAMPLE_LEAGUE)
    assert fx[0]["match_id"] == "5803519"
    assert fx[0]["kickoff_utc"].startswith("2026-08-07T10:25:00")


def test_snapshot_status_uses_utc_offset():
    kick = "2026-08-16T17:00:00+00:00"
    assert fm.snapshot_status(collected_at="2026-08-16T16:00:00+00:00", kickoff_utc=kick) == "VALID"
    assert fm.snapshot_status(collected_at="2026-08-16T18:00:00+00:00", kickoff_utc=kick) == "POST_MATCH_NOT_USABLE"


def test_extract_match_xg_and_post_match_flag():
    details = {
        "general": {
            "matchId": 5803519,
            "finished": True,
            "homeTeam": {"name": "A"},
            "awayTeam": {"name": "B"},
            "matchTimeUTCDate": "2026-08-07T10:25:00.000Z",
        },
        "content": {"stats": {"Periods": {"All": {"stats": [
            {"stats": [{"title": "Expected goals (xG)", "stats": ["1.46", "3.44"]}]},
        ]}}}},
    }
    got = fm.extract_match_xg(details)
    assert got["xg_home"] == 1.46
    assert got["xg_away"] == 3.44
    assert got["looks_post_match"] is True


def test_missing_match_xg_is_empty_not_invented():
    got = fm.extract_match_xg({"general": {"matchId": 1, "finished": False}, "content": {}})
    assert got["xg_home"] is None and got["xg_away"] is None
    assert got["looks_post_match"] is False


def test_naive_utc_time_is_rejected():
    assert fm.parse_utc("2026-08-07T10:25:00") is None
