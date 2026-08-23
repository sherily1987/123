from __future__ import annotations

import json
from pathlib import Path

from scripts.build_k3_calibration_sample import build_sample


def _job(match_id: int, *, as_of: str = "2026-08-20T10:00:00+00:00") -> dict:
    return {
        "identity": {
            "match_id": f"sporttery-{match_id}",
            "home": "主队",
            "away": "客队",
            "competition": "测试联赛",
            "kickoff": "2026-08-20T12:00:00+00:00",
        },
        "input": {"prediction_as_of": as_of},
        "outputs": [{
            "track": "llm",
            "direction": "H",
            "strength": {"type": "vote_share", "value": 0.8},
            "score": "2-0",
            "ou25": "小2.5",
            "hafu": "胜胜",
            "action": "skip",
            "evidence_gap": True,
        }],
    }


def test_build_sample_requires_pre_kickoff_and_official_result(tmp_path: Path):
    jobs = tmp_path / "jobs" / "2026-08-20"
    results = tmp_path / "results"
    jobs.mkdir(parents=True)
    results.mkdir()
    (jobs / "sporttery-1.json").write_text(json.dumps(_job(1)), encoding="utf-8")
    (jobs / "sporttery-2.json").write_text(json.dumps(_job(2)), encoding="utf-8")
    (results / "1.json").write_text(json.dumps({
        "match_id": "1",
        "status": "finished",
        "score_90": {"home": 2, "away": 1},
        "source": {"name": "中国体彩网移动端官方赛果"},
    }), encoding="utf-8")

    report = build_sample(jobs, results)

    assert report["model"] == "moonshot/kimi-k3"
    assert report["eligible_settled_rows"] == 1
    assert report["rows"][0]["direction_correct"] is True
    assert report["rows"][0]["score_exact"] is False
    assert report["excluded_by_reason"] == {"pending_or_missing_official_result": 1}
    assert report["metrics"]["direction_accuracy_pct"] == 100.0
    assert report["metrics"]["probability_n"] == 0
    assert report["metrics"]["probability_source_counts"] == {
        "production_llm_probs": 0,
        "research_raw_llm_probs": 0,
    }


def test_build_sample_rejects_post_kickoff_prediction(tmp_path: Path):
    jobs = tmp_path / "jobs"
    results = tmp_path / "results"
    jobs.mkdir()
    results.mkdir()
    (jobs / "sporttery-3.json").write_text(json.dumps(_job(3, as_of="2026-08-20T13:00:00+00:00")), encoding="utf-8")

    report = build_sample(jobs, results)

    assert report["eligible_settled_rows"] == 0
    assert report["excluded_by_reason"] == {"post_kickoff_prediction": 1}


def test_build_sample_scores_self_reported_probability_separately(tmp_path: Path):
    jobs = tmp_path / "jobs"
    results = tmp_path / "results"
    jobs.mkdir()
    results.mkdir()
    job = _job(4)
    job["outputs"][0]["llm_probs_1x2"] = [60, 25, 15]
    (jobs / "sporttery-4.json").write_text(json.dumps(job), encoding="utf-8")
    (results / "4.json").write_text(json.dumps({
        "match_id": "4", "status": "finished", "score_90": {"home": 1, "away": 0}
    }), encoding="utf-8")

    report = build_sample(jobs, results)

    assert report["metrics"]["probability_n"] == 1
    assert report["metrics"]["brier"] == 0.245
    assert report["metrics"]["probability_source_counts"]["production_llm_probs"] == 1


def test_build_sample_scores_raw_markets_without_promoting_them(tmp_path: Path):
    jobs = tmp_path / "jobs"
    results = tmp_path / "results"
    jobs.mkdir()
    results.mkdir()
    job = _job(5)
    job["outputs"][0].update({
        "llm_decision": "abstain",
        "llm_raw_probs_1x2": [60, 25, 15],
        "llm_probs_1x2": None,
    })
    (jobs / "sporttery-5.json").write_text(json.dumps(job), encoding="utf-8")
    (results / "5.json").write_text(json.dumps({
        "match_id": "5", "status": "finished", "score_90": {"home": 1, "away": 0}
    }), encoding="utf-8")

    report = build_sample(jobs, results)

    assert report["metrics"]["probability_n"] == 1
    assert report["rows"][0]["llm_probs_1x2"] is None
    assert report["rows"][0]["llm_raw_probs_1x2"] == [60, 25, 15]
    assert report["metrics"]["probability_source_counts"]["research_raw_llm_probs"] == 1


def test_build_sample_can_target_deepseek_v4_flash_without_changing_default_k3(tmp_path: Path):
    jobs = tmp_path / "jobs"
    results = tmp_path / "results"
    jobs.mkdir()
    results.mkdir()
    job = _job(6)
    job["outputs"][0]["model_id"] = "deepseek/deepseek-v4-flash"
    (jobs / "sporttery-6.json").write_text(json.dumps(job), encoding="utf-8")
    (results / "6.json").write_text(json.dumps({
        "match_id": "6", "status": "finished", "score_90": {"home": 2, "away": 0}
    }), encoding="utf-8")

    report = build_sample(jobs, results, "deepseek/deepseek-v4-flash")

    assert report["model"] == "deepseek/deepseek-v4-flash"
    assert report["eligible_settled_rows"] == 1
