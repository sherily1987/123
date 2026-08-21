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


def test_prompt_assigns_evidence_ids_without_claiming_cross_verification():
    text = """## 1. 伤停/阵容
- 接口返回0条，不能解读为无伤停 | source(https://example.test/injuries) | collected_at(2026-08-15T10:00:00+08:00)
> 证据缺口
"""
    catalog = predict.build_evidence_catalog(text)
    assert catalog == [{
        "id": "E1",
        "status": "UNAVAILABLE",
        "fact": "接口返回0条，不能解读为无伤停",
        "source": "https://example.test/injuries",
    }]
    prompt = predict.build_evidence_prompt({"home": "A", "away": "B"}, text, 1)
    assert "E1" in prompt
    assert "UNAVAILABLE" in prompt
    assert "来源已交叉验证" not in prompt


def test_catalog_marks_vote_slot_placeholders_unavailable():
    text = """## 1. 伤停/阵容
- 源17 besoccer.com：封锁源占槽、不采正文 | source(https://www.besoccer.com/x) | collected_at(t)
- 源9 livescore.com：无本场逐人预测十一人 | source(https://www.livescore.com/) | collected_at(t)
- 二十源整合预测首发（4-4-2，拉科）：Román | source(https://www.fotmob.com/x) | collected_at(t)
"""
    catalog = predict.build_evidence_catalog(text)
    by_id = {item["id"]: item for item in catalog}
    assert by_id["E1"]["status"] == "UNAVAILABLE"
    assert by_id["E2"]["status"] == "UNAVAILABLE"
    assert by_id["E3"]["status"] == "SINGLE_SOURCE"


def test_parser_keeps_opinion_when_lineup_gap_is_only_reason_code():
    payload = {
        "decision": "opinion", "direction": "主胜", "alt_direction": "平局",
        "probs_1x2": [48.0, 28.0, 24.0], "top_scores": ["1-0", "2-0", "1-1"],
        "ou25": "小", "hafu": "平胜",
        "evidence_gap": True, "evidence_ids": ["E2"],
        "unsupported_assumptions": [], "reason_codes": ["LINEUP_UNAVAILABLE"],
        "summary": "E2近况支持主胜；两源首发可用。",
    }
    out = predict.parse_evidence_prediction(
        __import__("json").dumps(payload, ensure_ascii=False),
        [{"id": "E2", "status": "VERIFIED_MULTI_SOURCE"}],
    )
    assert out["decision"] == "opinion"
    assert out["direction"] == "主胜"
    assert out["probs_1x2"] == [48.0, 28.0, 24.0]
    assert "LINEUP_UNAVAILABLE" in out["reason_codes"]


def test_parser_accepts_abstain_and_nullable_markets():
    payload = {
        "decision": "abstain", "direction": None, "alt_direction": None,
        "score_pref": None, "ou25": None, "hafu": None,
        "evidence_gap": True, "evidence_ids": ["E1"],
        "unsupported_assumptions": [], "reason_codes": ["LINEUP_UNAVAILABLE"],
        "summary": "证据不足",
    }
    out = predict.parse_evidence_prediction(
        __import__("json").dumps(payload, ensure_ascii=False),
        [{"id": "E1", "status": "UNAVAILABLE"}],
    )
    assert out["decision"] == "abstain"
    assert out["direction"] is None
    assert out["score_pref"] is None


@pytest.mark.parametrize("evidence_ids", [["E404"], ["E1"]])
def test_parser_downgrades_opinion_with_unknown_or_unusable_evidence_ids(evidence_ids):
    payload = {
        "decision": "opinion", "direction": "主胜", "alt_direction": None,
        "score_pref": None, "ou25": None, "hafu": None,
        "evidence_gap": False, "evidence_ids": evidence_ids,
        "unsupported_assumptions": [], "reason_codes": [], "summary": "主队方向",
    }
    out = predict.parse_evidence_prediction(
        __import__("json").dumps(payload, ensure_ascii=False),
        [{"id": "E1", "status": "UNAVAILABLE"}],
    )
    assert out["decision"] == "abstain"
    assert out["direction"] is None
    assert out["evidence_gap"] is True


def test_abstentions_do_not_vote_but_remain_auditable():
    abstain = {
        "decision": "abstain", "direction": None, "alt_direction": None,
        "score_pref": None, "ou25": None, "hafu": None,
        "evidence_gap": True, "evidence_ids": ["E1"], "reasoning": "证据不足",
        "reasoning_ok": True, "collapse_score": False,
    }
    opinion = {
        "decision": "opinion", "direction": "主胜", "alt_direction": None,
        "score_pref": None, "ou25": None, "hafu": None,
        "evidence_gap": False, "evidence_ids": ["E2"], "reasoning": "证据支持",
        "reasoning_ok": True, "collapse_score": False,
    }
    result = predict.aggregate_directions({
        "zhipu/glm-4-flash": abstain,
        "deepseek/deepseek-chat": opinion,
        "moonshot/kimi-k3": opinion,
    })
    assert result["valid_model_count"] == 2
    assert result["direction"] == "主胜"
    assert result["individual"]["zhipu/glm-4-flash"]["decision"] == "abstain"


def test_evidence_audit_validates_ids_and_unavailable_status():
    catalog = [
        {"id":"E1","status":"UNAVAILABLE"},
        {"id":"E2","status":"SINGLE_SOURCE"},
    ]
    payload = {"usable_evidence_ids":["E2"],"unusable_evidence_ids":["E1"],
               "conflict_evidence_ids":[],"gaps":["LINEUP_UNAVAILABLE"],
               "market_readiness":{"one_x_two":True,"score":False,"ou25":False,"hafu":False},
               "summary":"E2可用，E1不可用。"}
    audit = predict.parse_evidence_audit(__import__("json").dumps(payload, ensure_ascii=False), catalog)
    assert audit["status"] == "ok"
    assert audit["usable_evidence_ids"] == ["E2"]
    payload["usable_evidence_ids"] = ["E1"]
    assert "error" in predict.parse_evidence_audit(__import__("json").dumps(payload, ensure_ascii=False), catalog)


def test_voter_prompt_contains_neutral_audit_not_direction():
    audit = {"status":"ok","usable_evidence_ids":["E2"],"unusable_evidence_ids":["E1"],
             "conflict_evidence_ids":[],"gaps":["LINEUP_UNAVAILABLE"],
             "market_readiness":{"one_x_two":True,"score":False,"ou25":False,"hafu":False},
             "summary":"E2可用。"}
    prompt = predict.build_voter_prompt("BASE", audit)
    assert "BASE" in prompt and "E2" in prompt
    assert '"direction"' not in prompt


def test_glm_audits_and_deepseek_votes():
    assert predict.EVIDENCE_AUDITOR_MODEL == "zhipu/glm-4-flash"
    voters = [model for model in fp.DEFAULT_MODELS if model != predict.EVIDENCE_AUDITOR_MODEL]
    assert voters == ["deepseek/deepseek-chat", "moonshot/kimi-k3"]


def test_two_voter_consensus_requires_two_matching_opinions():
    glm = {"decision":"opinion","direction":"主胜"}
    kimi = {"decision":"opinion","direction":"主胜"}
    voters = ["zhipu/glm-4-flash", "moonshot/kimi-k3"]
    agreed = predict.two_voter_consensus({voters[0]:glm, voters[1]:kimi}, voters)
    assert agreed == {"status":"consensus","action":"research_opinion","direction":"主胜",
                      "voter_models":voters}
    disagreed = predict.two_voter_consensus(
        {voters[0]:glm, voters[1]:{"decision":"opinion","direction":"客胜"}}, voters)
    assert disagreed["status"] == "skip" and disagreed["reason"] == "voter_disagreement"
    abstained = predict.two_voter_consensus(
        {voters[0]:glm, voters[1]:{"decision":"abstain","direction":None}}, voters)
    assert abstained["status"] == "skip" and abstained["reason"] == "voter_abstained_or_failed"


def test_kimi_reasoning_model_gets_larger_output_budget():
    assert predict.output_token_budget("moonshot/kimi-k3") == 4096
    assert predict.output_token_budget("zhipu/glm-4-flash") == 1024


def test_skip_audit_record_preserves_gate_and_evidence_audit():
    record = predict.build_skip_audit_record(
        {"moonshot/kimi-k3": {"decision": "abstain", "direction": None}},
        ["moonshot/kimi-k3"], "PROMPT",
        {"evidence_file_sha256": "abc", "evidence_collected_at_min": "t1",
         "evidence_collected_at_max": "t2"},
        {"status": "ok", "summary": "audit"},
        {"status": "skip", "action": "skip", "reason": "voter_abstained_or_failed"},
        "insufficient_model_responses",
    )
    assert record["status"] == "skip"
    assert record["reason"] == "voter_abstained_or_failed"
    assert record["evidence_audit"]["summary"] == "audit"
