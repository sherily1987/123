from types import SimpleNamespace
import json
import sys

import mcp_evidence as me
import predict


def evidence_with_fact(fact_suffix=""):
    timestamp = "2026-08-10T20:00:00+08:00"
    sections = (
        "伤停与阵容", "战意与动机", "近况与状态", "主客旅行天气", "赔率", "身份核验"
    )
    return "\n".join(
        f"## {idx}. {title}\n- 可核验事实{idx} source(https://example.test/{idx}) collected_at({timestamp}){fact_suffix}"
        for idx, title in enumerate(sections, 1)
    )


def evidence_prediction(direction, *, alt=None, gap=False):
    return {
        "decision": "opinion", "direction": direction, "alt_direction": alt, "score_pref": "1-0",
        "reasoning": "【近况:有可核验事实】", "reasoning_ok": True,
        "evidence_gap": gap, "collapse_score": False,
    }


def test_every_evidence_fact_requires_source_and_collected_at():
    text = evidence_with_fact().replace(
        "可核验事实3 source(https://example.test/3) collected_at(2026-08-10T20:00:00+08:00)",
        "无来源的关键伤停事实",
    )
    result = predict.assess_evidence(text, "2026-08-11T01:00:00+08:00")
    assert result == {"ok": False, "reason": "fact_missing_source_or_collected_at"}


def test_evidence_filename_requires_exact_sequence_boundary():
    files = {
        "evidence_0010_wrong.md": "wrong",
        "evidence_001_right.md": "right",
        "evidence_003_target.md": "target",
    }
    assert predict.match_evidence_file(1, files) == "evidence_001_right.md"
    assert predict.match_evidence_file(3, files) == "evidence_003_target.md"


def test_mcp_filename_prefers_identity_matched_refresh_over_stale_duplicate():
    files = {
        "evidence_001_unknown_juventus_mcp.md": (
            "match_identity(sporttery_match_id=;home=弗洛西诺;away=尤文图斯;api_match_id=None)"
        ),
        "evidence_001_frosinone_juventus_mcp.md": (
            "match_identity(sporttery_match_id=2041018;home=弗洛西诺;away=尤文图斯;api_match_id=807857)"
        ),
    }
    match = {"sporttery_meta": {"match_id": 2041018}, "home": "弗洛西诺", "away": "尤文图斯"}
    assert predict.match_mcp_file(1, files, match=match) == "evidence_001_frosinone_juventus_mcp.md"


def test_original_third_match_single_rerun_uses_evidence_003(tmp_path, monkeypatch, capsys):
    raw_path = tmp_path / "raw.json"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    raw_path.write_text(json.dumps({"matches": [
        {"match_id": 1, "match_num": "001", "home": "A", "away": "B", "kickoff_iso": "2099-01-01T12:00:00+08:00"},
        {"match_id": 2, "match_num": "002", "home": "C", "away": "D", "kickoff_iso": "2099-01-01T12:00:00+08:00"},
        {"match_id": 3, "match_num": "003", "home": "E", "away": "F", "kickoff_iso": "2099-01-01T12:00:00+08:00"},
    ]}, ensure_ascii=False), encoding="utf-8")
    (evidence_dir / "evidence_001_wrong.md").write_text(evidence_with_fact(), encoding="utf-8")
    (evidence_dir / "evidence_003_target.md").write_text(evidence_with_fact(), encoding="utf-8")

    monkeypatch.setattr(predict.fp, "get_client", lambda *_: object())
    monkeypatch.setattr(predict, "call_evidence_model", lambda _client, model, *_: (model, evidence_prediction("主胜")))
    monkeypatch.setattr(sys, "argv", ["predict.py", "--input", str(raw_path), "--evidence-dir", str(evidence_dir),
                                       "--match-id", "3", "--models", "a", "b", "c"])
    predict.main()
    output = capsys.readouterr().out
    assert "证据: evidence_003_target.md" in output
    assert "evidence_001_wrong.md (MCP 已拼入)" not in output


def test_manual_item_honors_seq_and_fixture_kickoff():
    args = SimpleNamespace(
        match_id="715575", home="Sirius", away="Brommapojkarna", league="瑞超",
        seq=3, kickoff_iso="2026-08-10T17:00:00Z",
    )
    item = me.build_manual_item(args)
    assert item["ri"] == 2
    assert item["raw"]["kickoff_iso"] == "2026-08-10T17:00:00Z"
    assert item["cand"]["home_team"] == "Sirius"
    assert me.utc_date(item) == "2026-08-10"


def test_mcp_generated_facts_have_machine_readable_provenance():
    raw = {"home": "天狼星", "away": "布鲁马波卡纳", "league": "瑞超", "match_id": "x"}
    cand = {"home_team": "Sirius", "away_team": "Brommapojkarna"}
    block = me.build_block(raw, cand, [], None, None, None, "715575")
    fact_lines = [line for line in block.splitlines() if line.startswith("-")]
    assert fact_lines
    assert all("source(https://" in line and "collected_at(" in line for line in fact_lines)


def test_mcp_block_includes_sporttery_markets_and_api_sports_recent_form():
    raw = {"home":"阿森纳","away":"曼城","league":"英社区盾","match_id":2040898,
           "fixed_bonus_url":"https://webapi.sporttery.cn/match/2040898",
           "crs":{"1-0":9.5},"ttg":{"2":3.5},"hafu":{"hh":4.2}}
    api = {"status":"ok","fixture_id":1582365,
           "recent":{"home":[{"date":"2026-08-13","league":"Friendly","home":"Arsenal",
                                 "away":"Como","score_90":"1-1","status":"PEN"}],"away":[]},
           "injuries_status":"UNAVAILABLE","lineups_status":"UNAVAILABLE"}
    block = me.build_block(raw, {"home_team":"Arsenal","away_team":"Manchester City"},
                           [], None, None, None, "715575", api_sports=api)
    assert "CRS 比分赔率" in block and "TTG 总进球赔率" in block and "HAFU 半全场赔率" in block
    assert "主队近况" in block and "Arsenal" in block


def test_one_valid_model_returns_insufficient_model_responses():
    result = predict.aggregate_directions({"a": evidence_prediction("主胜"), "b": {"error": "down"}})
    assert result["error"] == "insufficient_model_responses"
    assert result["valid_model_count"] == 1


def test_explicit_k3_single_model_is_research_only_not_false_consensus():
    result = predict.aggregate_directions(
        {"moonshot/kimi-k3": evidence_prediction("主胜", alt="平局")},
        allow_single_model_research=True,
    )
    assert result["direction"] == "主胜"
    assert result["single_model"] is True
    assert result["research_only"] is True
    assert result["strength"] is None
    assert result["probs_1x2"] is None
    assert result["action"] == "observe"


def test_k3_only_main_skips_ev_and_single_pick(tmp_path, monkeypatch, capsys):
    raw_path = tmp_path / "raw.json"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    raw_path.write_text(json.dumps({"matches": [{
        "match_id": 3, "match_num": "003", "home": "E", "away": "F",
        "kickoff_iso": "2099-01-01T12:00:00+08:00",
    }]}, ensure_ascii=False), encoding="utf-8")
    (evidence_dir / "evidence_001_target.md").write_text(evidence_with_fact(), encoding="utf-8")

    monkeypatch.setattr(predict.fp, "get_client", lambda *_: object())
    monkeypatch.setattr(predict, "call_evidence_auditor", lambda *_: {
        "status": "ok", "usable_evidence_ids": [], "unusable_evidence_ids": [],
        "conflict_evidence_ids": [], "gaps": [], "market_readiness": {}, "summary": "ok",
    })
    monkeypatch.setattr(predict, "call_evidence_model",
                        lambda _client, model, *_: (model, evidence_prediction("主胜", alt="平局")))
    monkeypatch.setattr(sys, "argv", ["predict.py", "--input", str(raw_path),
                                       "--evidence-dir", str(evidence_dir),
                                       "--models", "moonshot/kimi-k3"])
    predict.main()
    output = capsys.readouterr().out
    assert "K3 单模型研究意见" in output
    assert "single_model_no_consensus" in output
    assert "💰 下注推荐" not in output
    assert '"action": "observe"' in output


def test_two_valid_models_forces_cautious_dual_output():
    result = predict.aggregate_directions({
        "a": evidence_prediction("主胜"), "b": evidence_prediction("客胜"),
    })
    assert result["direction"] == "主胜"
    assert result["caution"] is True
    assert result["alt_direction"] == "客胜"
    assert result["valid_model_count"] == 2


def test_evidence_gap_alt_direction_uses_second_highest_vote():
    aggregation = {
        "direction": "主胜", "alt_direction": None,
        "all_votes": {"主胜": 3.0, "客胜": 2.0, "平局": 1.0},
    }
    assert predict.enforce_evidence_gap(aggregation)["alt_direction"] == "客胜"


def test_incomplete_odds_are_explicitly_degraded_not_indexed():
    match = {"home": "A", "away": "B", "model_odds": ["1.8", None], "model_hhad": {"odds": ["1.5"]}}
    prompt = predict.build_evidence_prompt(match, evidence_with_fact(), 1)
    assert "官方胜平负赔率: 数据缺口" in prompt
    assert "官方让球赔率: 数据缺口" in prompt
