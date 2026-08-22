import mcp_evidence as mcp
import predict


def test_mcp_collector_is_single_pass_without_refresh_helpers():
    """Lineup gaps are recorded for browser回补; the MCP collector never watches."""
    assert not hasattr(mcp, "should_retry_late_lineup_refresh")
    assert "watch-refresh" not in mcp.main.__code__.co_consts


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


def test_api_sports_fallback_item_preserves_aliases_and_marks_evidence_gap():
    raw = {
        "home": "博塔弗戈", "away": "巴竞技", "competition": "巴甲",
        "kickoff": "2026-08-25T07:00:00+08:00",
        "sporttery_meta": {"match_id": 2041038},
    }

    item = mcp.api_sports_fallback_item(raw, 8)
    block = mcp.build_block(raw, item["cand"], [], None, None, None, None,
                            api_sports={"status": "ok", "recent": {}})

    assert item["mid"] is None
    assert "Atletico Paranaense" in item["api_sports_away_names"]
    assert "API-Sports 降级证据" in block


def test_mcp_block_uses_sporttery_meta_identity_when_flat_id_is_absent():
    raw = {
        "home": "弗洛西诺", "away": "尤文图斯", "competition": "意甲",
        "sporttery_meta": {"match_id": 2041018, "match_num": "周日018"},
    }
    block = mcp.build_block(raw, {"home_team": "Frosinone", "away_team": "Juventus"},
                            [], None, None, None, "807857")

    assert "sporttery_match_id=2041018" in block
    assert "体彩matchId 2041018" in block
    assert "数据缺口" in block


def test_mcp_block_meets_primary_evidence_contract_without_fabricating_gaps():
    raw = {
        "home": "天狼星", "away": "布鲁马波卡纳", "competition": "瑞超",
        "sporttery_meta": {"match_id": 100},
    }
    api = {
        "status": "ok", "fixture_id": 715575,
        "recent": {"home": [{"date": "2026-08-10", "league": "瑞超", "home": "Sirius",
                               "away": "AIK", "score_90": "1-0", "status": "FT"}], "away": []},
        "injuries_status": "UNAVAILABLE", "lineups_status": "UNAVAILABLE",
    }
    block = mcp.build_block(
        raw, {"home_team": "Sirius", "away_team": "Brommapojkarna"},
        [], None, None, None, "715575", api_sports=api,
    )

    status = predict.assess_evidence(
        block, kickoff="2099-01-01T12:00:00+08:00", now="2026-08-22T12:00:00+08:00"
    )

    assert status["ok"] is True
    assert status["evidence_gap"] is True
