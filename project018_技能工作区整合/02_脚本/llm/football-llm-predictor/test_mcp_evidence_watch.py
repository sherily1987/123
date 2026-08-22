import mcp_evidence as mcp


def test_late_refresh_retries_when_no_provider_lineup_is_available():
    """T-75 is only an opening window; a missing XI must not end refreshes."""
    api_sports = {"lineups_status": "UNAVAILABLE"}

    assert mcp.should_retry_late_lineup_refresh(api_sports, None) is True


def test_late_refresh_stops_after_any_valid_provider_lineup():
    api_sports = {"lineups_status": "ok"}

    assert mcp.should_retry_late_lineup_refresh(api_sports, None) is False
    assert mcp.should_retry_late_lineup_refresh(
        {"lineups_status": "UNAVAILABLE"}, {"available": True}
    ) is False


def test_formal_collector_kickoff_is_accepted_for_matching_and_utc_queries():
    raw = {"kickoff": "2026-08-25T00:30:00+08:00"}

    assert mcp.raw_kickoff_bj(raw).isoformat() == "2026-08-25T00:30:00"
    assert mcp.utc_date({"raw": raw}) == "2026-08-24"


def test_formal_collector_schema_matches_provider_candidate_with_shared_aliases():
    raw = {
        "home": "博洛尼亚", "away": "拉齐奥", "competition": "意甲",
        "kickoff": "2026-08-25T00:30:00+08:00",
    }
    candidate = {
        "league": "Serie A", "country": "Italy", "home_team": "Bologna",
        "away_team": "Lazio", "kickoff_utc": "2026-08-24T16:30:00.000Z",
    }

    assert mcp.match_raw_to_candidates([raw], [candidate]) == [(0, candidate)]
