# -*- coding: utf-8 -*-
"""Unit tests for prompt anti-collapse and evidence-first gate."""
import hashlib
import json
import sys

import football_predictor as fp
import llm_prompt_rules as lpr
import predict as pr


SIX_SECTIONS = """## 1. 伤停/阵容
- 主力后卫停赛 | source(https://example.test/injuries) | collected_at(2026-08-10T09:00:00+08:00)
## 2. 战意/动机
- 联赛争四 | source(https://example.test/motivation) | collected_at(2026-08-10T09:00:00+08:00)
## 3. 近况/状态
- 近五场三胜 | source(https://example.test/form) | collected_at(2026-08-10T09:00:00+08:00)
## 4. 主客/旅行/天气
- 主场作战 | source(https://example.test/weather) | collected_at(2026-08-10T09:00:00+08:00)
## 5. 赔率异动
- 赔率稳定 | source(https://example.test/odds) | collected_at(2026-08-10T09:00:00+08:00)
## 6. 身份核验
- 名称已核验 | source(https://example.test/identity) | collected_at(2026-08-10T09:00:00+08:00)
"""


def test_reasoning_quality():
    assert lpr.reasoning_quality("主胜赔率低市场看好")["ok"] is False
    assert lpr.reasoning_quality("【近况:连胜】【主客:主场】")["ok"] is True


def test_normalize():
    assert lpr.normalize_ou25("小") == "小2.5"
    assert lpr.normalize_hafu("HH") == "胜胜"
    assert lpr.normalize_score_pref("6-0") == "胜其他"


def test_production_default_models_are_three_domestic_voters_including_kimi():
    """qwen/qwen3.8-max 已于 2026-08-12 移除（DASHSCOPE key 401 失效），正式池 3 模。"""
    assert fp.DEFAULT_MODELS == [
        "zhipu/glm-4-flash",
        "deepseek/deepseek-chat",
        "moonshot/kimi-k2.6",
    ]
    assert "qwen/qwen3.8-max" not in fp.DEFAULT_MODELS
    assert fp.MODEL_TEMPERATURE_OVERRIDES["kimi-k2.6"] == 1.0


def test_parse_four_market_anti_collapse():
    good = fp.parse_prediction(
        '{"home_score":1,"away_score":0,"result":"主胜","total_goals":"1",'
        '"half_result":"平局","ou25":"小","hafu":"平胜","confidence":0.7,'
        '"reasoning":"【近况:主队不败】【主客:主场】"}'
    )
    assert good["ou25"] == "小2.5" and good["reasoning_ok"] is True
    weak = fp.parse_prediction(
        '{"home_score":2,"away_score":1,"result":"主胜","total_goals":"3",'
        '"half_result":"主胜","confidence":0.9,"reasoning":"赔率支持主胜"}'
    )
    assert weak["confidence"] <= 0.45 and weak["reasoning_ok"] is False


def test_aggregate_dual_and_ou():
    preds = {
        "a": fp.parse_prediction(
            '{"home_score":1,"away_score":0,"result":"主胜","total_goals":"1",'
            '"half_result":"平局","ou25":"小","hafu":"平胜","confidence":0.6,'
            '"reasoning":"【近况:稳】【主客:主】"}'
        ),
        "b": fp.parse_prediction(
            '{"home_score":1,"away_score":1,"result":"平局","total_goals":"2",'
            '"half_result":"平局","ou25":"小","hafu":"平平","confidence":0.55,'
            '"reasoning":"【近况:胶着】【战意:互爆】"}'
        ),
        "c": fp.parse_prediction(
            '{"home_score":2,"away_score":1,"result":"主胜","total_goals":"3",'
            '"half_result":"主胜","confidence":0.8,"reasoning":"盘口主热"}'
        ),
    }
    agg = fp.aggregate(preds, list(preds))
    assert agg["top_result"] in ("主胜", "平局")
    assert "top_ou25" in agg


def test_evidence_assessment_requires_all_six_sections_url_timestamp_and_facts():
    valid = pr.assess_evidence(SIX_SECTIONS)
    assert valid["ok"] is True
    assert valid["evidence_gap"] is False

    no_url = pr.assess_evidence(SIX_SECTIONS.replace("https://example.test/", "local/"))
    assert no_url == {"ok": False, "reason": "missing_source_url"}

    wrong_title = pr.assess_evidence(SIX_SECTIONS.replace("## 3. 近况/状态", "## 3. 其他内容"))
    assert wrong_title == {"ok": False, "reason": "missing_required_sections:3"}

    only_gaps = pr.assess_evidence(
        SIX_SECTIONS.replace("主力后卫停赛", "未检索到可靠信息")
        .replace("联赛争四", "证据缺口").replace("近五场三胜", "未拿到数据")
        .replace("主场作战", "未检索到").replace("赔率稳定", "证据缺口")
        .replace("名称已核验", "未检索到")
    )
    assert only_gaps == {"ok": False, "reason": "only_evidence_gaps"}


def test_evidence_assessment_rejects_missing_or_invalid_or_post_kickoff_timestamps():
    missing_on_a_cited_fact = SIX_SECTIONS.replace(" | collected_at(2026-08-10T09:00:00+08:00)", "", 1)
    missing = pr.assess_evidence(missing_on_a_cited_fact, kickoff="2026-08-10T10:00:00+08:00")
    assert missing == {"ok": False, "reason": "fact_missing_source_or_collected_at"}

    invalid = pr.assess_evidence(SIX_SECTIONS.replace("2026-08-10T09:00:00+08:00", "not-a-date", 1), kickoff="2026-08-10T10:00:00+08:00")
    assert invalid["ok"] is False
    assert invalid["reason"].startswith("evidence_after_kickoff:")
    assert "invalid_collected_at" in invalid["reason"]

    post_kickoff = pr.assess_evidence(SIX_SECTIONS, kickoff="2026-08-10T09:00:00+08:00")
    assert post_kickoff == {
        "ok": False,
        "reason": "evidence_after_kickoff:collected_at_at_or_after_kickoff",
    }


def test_evidence_assessment_returns_hash_and_timestamp_range_before_kickoff():
    text = SIX_SECTIONS.replace("2026-08-10T09:00:00+08:00", "2026-08-10T08:00:00+08:00", 1).replace(
        "2026-08-10T09:00:00+08:00", "2026-08-10T09:30:00+08:00", 1
    )
    result = pr.assess_evidence(text, kickoff="2026-08-10T10:00:00+08:00")

    assert result["ok"] is True
    assert result["evidence_file_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result["evidence_collected_at_min"] == "2026-08-10T08:00:00+08:00"
    assert result["evidence_collected_at_max"] == "2026-08-10T09:30:00+08:00"


def test_predict_parse():
    p = pr.parse_evidence_prediction(
        '{"direction":"客胜","alt_direction":"平局","score_pref":"0-1",'
        '"ou25":"小","hafu":"平负","reasoning":"【战意:升班马】"}'
    )
    assert p["direction"] == "客胜" and p["ou25"] == "小2.5" and p["reasoning_ok"]


def test_prompt_uses_evidence_collection_timestamp_not_hardcoded_date():
    prompt = pr.build_evidence_prompt({"home": "A", "away": "B"}, SIX_SECTIONS, 1)
    assert "采集时间 2026-08-10T09:00:00+08:00" in prompt
    assert "采集时间 2026-08-05" not in prompt


def test_cli_missing_evidence_is_json_and_never_initializes_llm(tmp_path, monkeypatch, capsys):
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({"matches": [{"home": "A", "away": "B", "match_num": "001"}]}), encoding="utf-8")
    monkeypatch.setattr(pr.fp, "get_client", lambda *_: (_ for _ in ()).throw(AssertionError("LLM initialized")))
    monkeypatch.setattr(sys, "argv", ["predict.py", "--input", str(raw), "--evidence-dir", str(tmp_path)])
    pr.main()
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result == {"match_index": 1, "status": "evidence_insufficient", "reason": "missing_evidence_file"}


def test_cli_rejects_post_kickoff_evidence_before_initializing_llm(tmp_path, monkeypatch, capsys):
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({"matches": [{
        "home": "A", "away": "B", "match_num": "001", "kickoff_iso": "2026-08-10T09:00:00+08:00"
    }]}), encoding="utf-8")
    (tmp_path / "evidence_001_A_B.md").write_text(SIX_SECTIONS, encoding="utf-8")
    monkeypatch.setattr(pr.fp, "get_client", lambda *_: (_ for _ in ()).throw(AssertionError("LLM initialized")))
    monkeypatch.setattr(sys, "argv", ["predict.py", "--input", str(raw), "--evidence-dir", str(tmp_path)])

    pr.main()

    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result == {
        "match_index": 1,
        "status": "evidence_insufficient",
        "reason": "prediction_at_or_after_kickoff",
    }


def test_evidence_gap_forces_dual_direction_and_caution():
    gated = pr.enforce_evidence_gap({"direction": "主胜", "alt_direction": None, "caution": False})
    assert gated["evidence_gap"] is True
    assert gated["caution"] is True
    assert gated["alt_direction"] in ("平局", "客胜")
    assert gated["alt_direction"] != gated["direction"]


def test_audit_record_keeps_failed_model_without_casting_a_reverse_vote():
    """故意不用 fp.DEFAULT_MODELS：这里测的是聚合/审计机制本身，不是生产模型池组成，
    绑定 DEFAULT_MODELS 的具体内容/长度会在每次调池子时无谓break（见 2026-08-12 踩坑记录）。
    """
    models = ["zhipu/glm-4-flash", "qwen/qwen3.8-max",
              "deepseek/deepseek-chat", "moonshot/kimi-k2.6"]
    successful = pr.parse_evidence_prediction(
        '{"direction":"主胜","score_pref":"1-0","reasoning":"【近况:主队连胜】"}'
    )
    agg = pr.aggregate_directions({models[0]: successful, models[1]: {"error": "timeout"},
                                   models[2]: successful, models[3]: successful})
    evidence_status = pr.assess_evidence(SIX_SECTIONS)
    prompt = "evidence prompt"

    record = pr.build_audit_record(agg, models, prompt, evidence_status)

    assert agg["direction"] == "主胜"
    assert agg["all_votes"] == {"主胜": 3.0}
    assert record["individual"][models[0]]["model_id"] == models[0]
    assert record["individual"][models[0]]["provider"] == "zhipu"
    assert record["individual"][models[0]]["status"] == "success"
    assert record["individual"][models[1]] == {
        "model_id": models[1], "provider": "qwen", "status": "failed", "error": "timeout"
    }
    assert record["llm_model_pool_sha256"] == hashlib.sha256(
        json.dumps(models, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert record["prompt_sha256"] == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert record["evidence_file_sha256"] == evidence_status["evidence_file_sha256"]
    assert record["evidence_collected_at_min"] == "2026-08-10T09:00:00+08:00"
    assert record["evidence_collected_at_max"] == "2026-08-10T09:00:00+08:00"
    assert record["aggregation_rule_version"]
    assert len(record["aggregation_rule_sha256"]) == 64
    json.dumps(record, ensure_ascii=False)


if __name__ == "__main__":
    test_reasoning_quality()
    test_normalize()
    test_parse_four_market_anti_collapse()
    test_aggregate_dual_and_ou()
    test_evidence_assessment_requires_all_six_sections_url_timestamp_and_facts()
    test_predict_parse()
    print("ALL TESTS PASSED")
