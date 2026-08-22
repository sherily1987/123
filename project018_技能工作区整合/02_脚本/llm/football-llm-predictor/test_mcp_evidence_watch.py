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
