import pytest

import football_predictor as fp
import mcp_evidence as me
import predict


def primary_evidence(collected_at="2026-08-10T20:00:00+08:00"):
    rows = []
    for number, title in (
        (1, "伤停/阵容"), (2, "战意/动机"), (3, "近况/状态"),
        (4, "主客/旅行/天气"), (5, "赔率"), (6, "身份核验"),
    ):
        rows.extend((
            f"## {number}. {title}",
            f"- 已核验事实{number} | source(https://example.test/{number}) | collected_at({collected_at})",
        ))
    return "\n".join(rows)


def test_report_accepts_serialized_score_keys():
    predictions = {
        "zhipu/glm-4-flash": {
            "home_score": 1, "away_score": 0, "result": "主胜", "total_goals": "1",
            "half_result": "主胜", "ou25": "小2.5", "hafu": "胜胜",
            "confidence": 0.6, "reasoning": "【近况:主队状态更好】", "reasoning_ok": True,
        },
        "qwen/qwen3.8-max": {
            "home_score": 1, "away_score": 0, "result": "主胜", "total_goals": "1",
            "half_result": "主胜", "ou25": "小2.5", "hafu": "胜胜",
            "confidence": 0.6, "reasoning": "【近况:主队状态更好】", "reasoning_ok": True,
        },
        "deepseek/deepseek-chat": {
            "home_score": 0, "away_score": 0, "result": "平局", "total_goals": "0",
            "half_result": "平局", "ou25": "小2.5", "hafu": "平平",
            "confidence": 0.5, "reasoning": "【近况:双方状态接近】", "reasoning_ok": True,
        },
    }
    fp.print_report("A", "B", fp.aggregate(predictions, list(predictions)))


def test_evidence_rejects_runtime_at_or_after_kickoff():
    result = predict.assess_evidence(
        primary_evidence(),
        kickoff="2026-08-11T01:00:00+08:00",
        now="2026-08-11T01:00:00+08:00",
    )
    assert result == {"ok": False, "reason": "prediction_at_or_after_kickoff"}


def test_mcp_requires_machine_readable_pre_kickoff_collection_time():
    mcp = """# MCP 数据证据块
> source(https://mcp.apifootball.com/match/1)
> 数据源: apifootball | 采集: 2026-08-11 02:00
- 首发名单
"""
    result = predict.assess_mcp_evidence(mcp, "2026-08-11T01:00:00+08:00")
    assert result == {"ok": False, "reason": "missing_mcp_collected_at"}


def test_mcp_sidecar_identity_must_match_selected_raw_match():
    mcp = """# MCP 数据证据块
> source(https://apifootball.com/) collected_at(2026-08-10T20:00:00+08:00)
> match_identity(sporttery_match_id=100;home=错误主队;away=错误客队;api_match_id=999)
- 结构化事实 source(https://apifootball.com/) collected_at(2026-08-10T20:00:00+08:00)
"""
    match = {"match_id": 100, "home": "正确主队", "away": "正确客队"}
    result = predict.assess_mcp_evidence(mcp, "2026-08-11T01:00:00+08:00", match=match)
    assert result == {"ok": False, "reason": "mcp_match_identity_mismatch"}


def test_automatic_match_rejects_same_league_time_with_different_teams():
    raw = [{
        "league": "瑞超", "kickoff_local": "2026-08-11 01:00",
        "team_ids": {"home_full": "天狼星", "away_full": "布鲁马波卡纳"},
    }]
    candidate = {
        "match_id": "wrong", "league": "Allsvenskan", "country": "Sweden",
        "kickoff_utc": "2026-08-10T17:00:00Z",
        "home_team": "Vasteras SK", "away_team": "Djurgarden",
    }
    assert me.match_raw_to_candidates(raw, [candidate]) == [(0, None)]


def test_automatic_match_rejects_timezone_less_external_kickoff():
    assert me.to_bj("2026-08-10T17:00:00") is None
    raw = [{
        "league": "瑞超", "kickoff_iso": "2026-08-11T01:00:00+08:00",
        "team_ids": {"home_full": "天狼星", "away_full": "布鲁马波卡纳"},
    }]
    candidate = {
        "match_id": "unsafe", "league": "Allsvenskan", "country": "Sweden",
        "kickoff_utc": "2026-08-10T17:00:00",
        "home_team": "Sirius", "away_team": "Brommapojkarna",
    }
    assert me.match_raw_to_candidates(raw, [candidate]) == [(0, None)]


def test_selected_match_keeps_original_evidence_index():
    matches = [{"match_id": 1}, {"match_id": 2}, {"match_id": 3}]
    assert predict.select_matches(matches, match_id=3) == [(3, {"match_id": 3})]
