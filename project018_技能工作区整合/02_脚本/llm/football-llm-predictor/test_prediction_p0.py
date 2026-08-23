import pytest
from types import SimpleNamespace

import football_predictor as fp
import mcp_evidence as me
import predict


def test_deepseek_retries_structured_parse_failure(monkeypatch):
    class Chat:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            content = (
                "not-json"
                if self.calls == 1
                else '{"decision":"opinion","direction":"主胜",'
                     '"probs_1x2":[50,25,25],"top_scores":["1-0","2-0","1-1"],'
                     '"ou25":"小","hafu":"胜胜","evidence_gap":true,'
                     '"evidence_ids":[],"summary":"仅作观察性研究意见。"}'
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                usage=None,
            )

    chat = Chat()
    monkeypatch.setattr(predict.time, "sleep", lambda *_args: None)
    model, result = predict.call_evidence_model(
        SimpleNamespace(chat=SimpleNamespace(completions=chat)),
        "deepseek/deepseek-v4-flash",
        "E1: 已核验事实",
        evidence_catalog=None,
    )
    assert model == "deepseek/deepseek-v4-flash"
    assert chat.calls == 2
    assert result["direction"] == "主胜"


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


def test_success_audit_record_carries_llm_contract_and_evidence_manifest():
    aggregation = {
        "direction": "主胜",
        "single_model": True,
        "research_only": True,
        "action": "observe",
        "reason": "single_model_no_consensus",
        "models_used": ["moonshot/kimi-k3"],
        "individual": {},
    }
    evidence_status = {
        "evidence_file_sha256": "abc",
        "evidence_collected_at_min": "2026-08-10T20:00:00+08:00",
        "evidence_collected_at_max": "2026-08-10T20:00:00+08:00",
        "evidence_source": "web_primary",
    }
    match = {
        "match_id": "2040999",
        "home": "主队",
        "away": "客队",
        "kickoff": "2026-08-10T22:00:00+08:00",
        "crs": [],
        "ttg": [],
        "hafu": [],
    }

    record = predict.build_audit_record(
        aggregation,
        ["moonshot/kimi-k3"],
        "prompt",
        evidence_status,
        match=match,
    )

    assert record["match_id"] == "sporttery-2040999"
    assert record["llm_track_contract"]["valid"] is True
    assert record["evidence_manifest"]["match_id"] == "sporttery-2040999"
    assert record["prediction_as_of"]


def test_manifest_keeps_predicted_xi_distinct_from_official_lineup():
    match = {
        "match_id": "sporttery-2040999",
        "crs": [{"score": "1-0", "odds": 5.0}],
        "ttg": [{"total": "2", "odds": 3.5}],
        "hafu": [{"result": "平胜", "odds": 4.0}],
    }
    status = {
        "evidence_collected_at_max": "2099-08-22T12:00:00+08:00",
        "collection_status": "COMPLETE_PREDICTED",
    }
    text = (
        "- 近期状态 | source(https://example.test/form)\n"
        "- 伤停状态 | AVAILABLE | source(https://example.test/injuries)\n"
        "- 首发状态 | PREDICTED | 预计首发，非官方首发 | source(https://example.test/xi)"
    )

    manifest = predict._build_llm_evidence_manifest(match, status, text)

    assert manifest["sections"]["lineups"]["status"] == "PREDICTED"
    assert manifest["risk_sections"] == ["lineups"]
    assert manifest["gap_sections"] == ["recent_form"]


def test_skip_audit_record_keeps_match_identity():
    record = predict.build_skip_audit_record(
        {},
        ["moonshot/kimi-k3"],
        "prompt",
        {
            "evidence_file_sha256": "abc",
            "evidence_collected_at_min": "2026-08-10T20:00:00+08:00",
            "evidence_collected_at_max": "2026-08-10T20:00:00+08:00",
        },
        {},
        {"reason": "single_model_no_consensus"},
        "failed",
        match={"match_id": "2040999", "home": "主队", "away": "客队"},
    )

    assert record["match_id"] == "sporttery-2040999"
    assert record["action"] == "skip"


def test_deepseek_v4_flash_evidence_auditor_uses_default_temperature_budget():
    requests = []

    class Completions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))

    predict.call_evidence_auditor(client, "证据审计", [])

    assert requests
    assert all(request["temperature"] == 0.0 for request in requests)
    assert all(request["max_tokens"] == 4096 for request in requests)
    assert all(request["extra_body"] == {"thinking": {"type": "disabled"}} for request in requests)


def test_evidence_auditor_retries_once_after_unknown_evidence_id():
    responses = [
        '{"usable_evidence_ids":["E999"],"unusable_evidence_ids":[],"conflict_evidence_ids":[],"gaps":[],"market_readiness":{"one_x_two":true,"score":true,"ou25":true,"hafu":true},"summary":"first"}',
        '{"gaps":[],"market_readiness":{"one_x_two":true,"score":true,"ou25":true,"hafu":true},"summary":"second"}',
    ]
    requests = []

    class Completions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=responses.pop(0))
            )])

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    catalog = [{"id": "E1", "status": "SINGLE_SOURCE"}]

    result = predict.call_evidence_auditor(client, "证据审计", catalog)

    assert result["status"] == "ok"
    assert result["usable_evidence_ids"] == ["E1"]
    assert len(requests) == 2
    assert "audit_unknown_evidence_id" in requests[1]["messages"][-1]["content"]
    assert "不得输出 usable_evidence_ids" in requests[1]["messages"][-1]["content"]


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


def test_mcp_sidecar_identity_accepts_sporttery_meta_match_id():
    mcp = """# MCP 数据证据块
> source(https://apifootball.com/) collected_at(2026-08-10T20:00:00+08:00)
> match_identity(sporttery_match_id=2041018;home=弗洛西诺;away=尤文图斯;api_match_id=807857)
- 结构化事实 source(https://apifootball.com/) collected_at(2026-08-10T20:00:00+08:00)
"""
    match = {"sporttery_meta": {"match_id": 2041018}, "home": "弗洛西诺", "away": "尤文图斯"}
    assert predict.assess_mcp_evidence(mcp, "2026-08-11T01:00:00+08:00", match=match) == {"ok": True}


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


def test_catalog_accepts_structured_snapshot_blockquotes_and_honors_status():
    text = """> - recent_form: status=PARTIAL；source=sporttery.preview；facts_available=true | source(https://m.sporttery.cn/zqlszl/bssj/?mid=1) | collected_at(2026-08-23T12:00:00+08:00)
> - starting_xi: status=PREDICTED；source=api-sports.io | source(https://v3.football.api-sports.io/fixtures/lineups?fixture=1) | collected_at(2026-08-23T12:00:00+08:00)
>   facts={"home":["A"]}
> - suspensions: status=EMPTY_UNCONFIRMED；source=sporttery.late_info | source(https://m.sporttery.cn/zqlszl/bssj/?mid=1) | collected_at(2026-08-23T12:00:00+08:00)
"""
    catalog = predict.build_evidence_catalog(text)
    assert [item["status"] for item in catalog] == ["SINGLE_SOURCE", "SINGLE_SOURCE", "UNAVAILABLE"]
    assert catalog[1]["source"].endswith("fixture=1")


def test_prompt_explicitly_downweights_predicted_xi():
    text = (
        "> - starting_xi: status=PREDICTED；source=fotmob.bb_browser；"
        "source(https://example.test/match) | collected_at(2026-08-23T12:00:00+08:00)\n"
        ">   facts={\"home\":[\"A\"],\"away\":[\"B\"]}\n"
    )
    prompt = predict.build_evidence_prompt({"home": "A", "away": "B"}, text, 1)
    assert "预计首发/PREDICTED" in prompt
    assert "权重低于官方已确认首发" in prompt
    assert "不得写成‘官方首发’" in prompt


def test_empty_unconfirmed_status_is_a_gap_not_a_clear_injury_claim():
    text = """## 1. 伤停/阵容
- 伤停状态 | EMPTY_UNCONFIRMED | source(https://example.test/injuries) | collected_at(2026-08-15T10:00:00+08:00)
"""
    status = predict._build_llm_evidence_manifest(
        {"match_id": "sporttery-1", "crs": [], "ttg": [], "hafu": []},
        {"evidence_collected_at_max": "2026-08-15T10:00:00+08:00"},
        text,
    )
    assert status["sections"]["injuries"]["status"] == "UNAVAILABLE"
    assert "injuries" in status["gap_sections"]


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


def test_parser_preserves_raw_markets_when_evidence_forces_abstain():
    payload = {
        "decision": "opinion", "direction": "主胜", "alt_direction": "平局",
        "probs_1x2": [55, 25, 20], "top_scores": ["1-0", "2-0", "1-1"],
        "ou25": "小", "hafu": "胜胜", "evidence_gap": False,
        "evidence_ids": ["E404"], "unsupported_assumptions": [],
        "reason_codes": [], "summary": "模型给出研究判断",
    }
    out = predict.parse_evidence_prediction(
        __import__("json").dumps(payload, ensure_ascii=False),
        [{"id": "E1", "status": "UNAVAILABLE"}],
    )
    assert out["decision"] == "abstain"
    assert out["direction"] is None
    assert out["probs_1x2"] is None
    assert out["raw_llm_probs_1x2"] == [55, 25, 20]
    assert out["raw_llm_top_scores"] == ["1-0", "2-0", "1-1"]
    assert out["raw_llm_ou25"] == "小2.5"
    assert out["raw_llm_hafu"] == "胜胜"


def test_parser_rejects_direction_probability_conflict_but_keeps_raw_probability():
    payload = {
        "decision": "opinion", "direction": "主胜", "alt_direction": None,
        "probs_1x2": [20, 25, 55], "top_scores": ["1-0", "1-1", "0-1"],
        "ou25": "小", "hafu": "胜胜", "evidence_gap": False,
        "evidence_ids": ["E1"], "unsupported_assumptions": [],
        "reason_codes": [], "summary": "方向与概率矛盾",
    }
    out = predict.parse_evidence_prediction(
        __import__("json").dumps(payload, ensure_ascii=False),
        [{"id": "E1", "status": "SINGLE_SOURCE"}],
    )
    assert out["decision"] == "abstain"
    assert out["direction"] is None
    assert "PROBABILITY_DIRECTION_CONFLICT" in out["reason_codes"]
    assert out["raw_llm_probs_1x2"] == [20, 25, 55]


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


def test_evidence_audit_derives_status_lists_when_k3_omits_them():
    catalog = [
        {"id": "E1", "status": "SINGLE_SOURCE"},
        {"id": "E2", "status": "UNAVAILABLE"},
        {"id": "E3", "status": "SOURCE_CONFLICT"},
        {"id": "E4", "status": "VERIFIED_MULTI_SOURCE"},
    ]
    payload = {
        "gaps": ["LINEUP_UNAVAILABLE"],
        "market_readiness": {"one_x_two": True, "score": False, "ou25": False, "hafu": False},
        "summary": "仅输出缺口与市场就绪状态。",
    }

    audit = predict.parse_evidence_audit(__import__("json").dumps(payload, ensure_ascii=False), catalog)

    assert audit["status"] == "ok"
    assert audit["usable_evidence_ids"] == ["E1", "E4"]
    assert audit["unusable_evidence_ids"] == ["E2"]
    assert audit["conflict_evidence_ids"] == ["E3"]


def test_voter_prompt_contains_neutral_audit_not_direction():
    audit = {"status":"ok","usable_evidence_ids":["E2"],"unusable_evidence_ids":["E1"],
             "conflict_evidence_ids":[],"gaps":["LINEUP_UNAVAILABLE"],
             "market_readiness":{"one_x_two":True,"score":False,"ou25":False,"hafu":False},
             "summary":"E2可用。"}
    prompt = predict.build_voter_prompt("BASE", audit)
    assert "BASE" in prompt and "E2" in prompt
    assert '"direction"' not in prompt


def test_deepseek_v4_flash_is_the_only_default_auditor_and_voter():
    assert predict.EVIDENCE_AUDITOR_MODEL == "deepseek/deepseek-v4-flash"
    assert fp.DEFAULT_MODELS == ["deepseek/deepseek-v4-flash"]


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


def test_single_k3_is_research_observation_not_consensus():
    voter = "moonshot/kimi-k3"
    observed = predict.two_voter_consensus(
        {voter: {"decision": "opinion", "direction": "主胜"}}, [voter]
    )
    assert observed == {
        "status": "single_model_research", "action": "observe",
        "reason": "single_model_no_consensus", "direction": "主胜",
        "voter_models": [voter],
    }


def test_kimi_reasoning_model_gets_larger_output_budget():
    assert predict.output_token_budget("moonshot/kimi-k3") == 4096
    assert predict.output_token_budget("zhipu/glm-4-flash") == 1024


def test_skip_audit_record_preserves_gate_and_evidence_audit():
    record = predict.build_skip_audit_record(
        {"moonshot/kimi-k3": {"decision": "abstain", "direction": None,
                               "raw_llm_probs_1x2": [20, 25, 55]}},
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
    assert record["individual"]["moonshot/kimi-k3"]["raw_llm_probs_1x2"] == [20, 25, 55]
