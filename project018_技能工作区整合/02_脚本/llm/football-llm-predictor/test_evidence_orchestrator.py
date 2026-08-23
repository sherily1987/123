import json

import evidence_orchestrator as eo
import predict


RAW = {
    "match_id": 2040999,
    "home": "主队",
    "away": "客队",
    "kickoff_iso": "2099-08-22T20:00:00+08:00",
    "crs": [{"score": "1-0", "odds": 5.0}],
    "ttg": [{"total": "2", "odds": 3.5}],
    "hafu": [{"result": "平胜", "odds": 4.0}],
}


def test_collection_is_single_pass_and_never_emits_t75_fields():
    manifest = eo.collection_manifest(
        RAW,
        {"recent_form": {"home": [], "away": []}, "injuries_status": "UNAVAILABLE",
         "lineups_status": "UNAVAILABLE"},
        collected_at="2099-08-22T12:00:00+08:00",
    )

    assert manifest["collection_mode"] == "single_pass"
    assert manifest["collection_status"] == "ONLY_ODDS"
    assert manifest["gap_sections"]
    assert "t75_refresh" not in manifest
    assert "refresh_before_minutes" not in manifest


def test_predicted_lineup_is_complete_with_explicit_risk_status():
    manifest = eo.collection_manifest(
        RAW,
        {
            "recent_form": {"home": [{"result": "W"}] * 5,
                            "away": [{"result": "L"}] * 5},
            "injuries_status": "AVAILABLE",
            "lineups_status": "PREDICTED",
        },
        collected_at="2099-08-22T12:00:00+08:00",
    )

    assert manifest["collection_status"] == "COMPLETE_PREDICTED"
    assert manifest["gap_sections"] == []
    assert manifest["risk_sections"] == ["lineups"]


def test_browser_tasks_are_explicit_and_match_bound(tmp_path):
    sources = [{
        "sporttery_match_id": 2040999,
        "url": "https://example.test/match",
        "source_level": "media",
        "canonical_home": "Home FC",
        "canonical_away": "Away FC",
        "facts": [{"section": 3, "text": "近况事实", "required_terms": ["Home FC"]}],
    }]
    tasks = eo.build_browser_tasks(
        [RAW],
        {"sporttery-2040999": {"gap_sections": ["recent_form", "lineups"]}},
        sources,
        generated_at="2099-08-22T12:01:00+08:00",
    )

    assert tasks["schema_version"] == 1
    assert tasks["collection_mode"] == "single_pass"
    assert tasks["tasks"][0]["match_id"] == "sporttery-2040999"
    assert tasks["tasks"][0]["sections"] == ["recent_form", "lineups"]
    assert tasks["tasks"][0]["urls"] == ["https://example.test/match"]
    (tmp_path / "browser_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")


def test_browser_snapshot_merge_rejects_post_kickoff_and_keeps_verified_facts(tmp_path):
    source = {
        "sporttery_match_id": 2040999,
        "url": "https://example.test/match",
        "source_level": "media",
        "canonical_home": "Home FC",
        "canonical_away": "Away FC",
        "facts": [{"section": 3, "text": "近况事实", "required_terms": ["recent form"]}],
    }
    valid = {
        "sporttery_match_id": 2040999,
        "canonical_home": "Home FC",
        "canonical_away": "Away FC",
        "final_url": "https://example.test/match",
        "title": "Home FC vs Away FC",
        "markdown": "recent form",
        "crawled_at": "2099-08-22T12:00:00+08:00",
    }
    late = {**valid, "crawled_at": "2099-08-22T21:00:00+08:00"}
    (tmp_path / "valid.json").write_text(json.dumps(valid), encoding="utf-8")
    (tmp_path / "late.json").write_text(json.dumps(late), encoding="utf-8")

    merged = eo.merge_browser_snapshots([RAW], [source], tmp_path)

    assert merged["sporttery-2040999"]["verified_facts"] == [{
        "section": 3,
        "text": "近况事实",
        "source": "https://example.test/match",
        "collected_at": "2099-08-22T12:00:00+08:00",
        "source_level": "media",
    }]
    assert merged["sporttery-2040999"]["rejected_snapshots"] == 1


def test_browser_snapshot_writer_uses_auditable_common_schema(tmp_path):
    source = {
        "sporttery_match_id": 2040999,
        "url": "https://example.test/match",
        "source_level": "media",
        "canonical_home": "Home FC",
        "canonical_away": "Away FC",
    }
    path = eo.write_browser_snapshot(
        RAW, source, tmp_path,
        title="Home FC vs Away FC", markdown="captured page",
        final_url=source["url"], crawled_at="2099-08-22T12:00:00+08:00",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["sporttery_match_id"] == 2040999
    assert payload["url"] == source["url"]
    assert payload["content_sha256"]


def test_odds_only_degradation_forces_observe_without_confidence_or_recommendation():
    aggregation = {"direction": "主胜", "confidence": 0.7, "action": "bet", "probs_1x2": [60, 20, 20]}

    degraded = eo.apply_collection_degradation(aggregation, "ONLY_ODDS")

    assert degraded["direction"] == "主胜"
    assert degraded["evidence_gap"] is True
    assert degraded["confidence"] is None
    assert degraded["action"] == "observe"
    assert degraded["recommendation"] is None
    assert degraded["reason"] == "odds_only_evidence"


def test_predict_boundary_allows_only_odds_gap_when_explicitly_enabled():
    evidence = "\n".join([
        "## 1. 伤停/阵容", "- UNAVAILABLE | source(https://sporttery.cn) | collected_at(2099-08-22T12:00:00+08:00)",
        "## 2. 战意/动机", "- UNAVAILABLE | source(https://sporttery.cn) | collected_at(2099-08-22T12:00:00+08:00)",
        "## 3. 近况/状态", "- UNAVAILABLE | source(https://sporttery.cn) | collected_at(2099-08-22T12:00:00+08:00)",
        "## 4. 主客/旅行/天气", "- UNAVAILABLE | source(https://sporttery.cn) | collected_at(2099-08-22T12:00:00+08:00)",
        "## 5. 赔率", "- 体彩 CRS/TTG/HAFU 已采集 | source(https://sporttery.cn) | collected_at(2099-08-22T12:00:00+08:00)",
        "## 6. 身份核验", "- UNAVAILABLE | source(https://sporttery.cn) | collected_at(2099-08-22T12:00:00+08:00)",
    ])
    status = predict.assess_evidence(
        evidence,
        kickoff="2099-08-22T20:00:00+08:00",
        now="2099-08-22T12:30:00+08:00",
        allow_odds_only=True,
    )

    assert status["ok"] is True
    assert status["collection_status"] == "ONLY_ODDS"
    manifest = predict._build_llm_evidence_manifest(RAW, status, evidence)
    assert manifest["collection_status"] == "ONLY_ODDS"
