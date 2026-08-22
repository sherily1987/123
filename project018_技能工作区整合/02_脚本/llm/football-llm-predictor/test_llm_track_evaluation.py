import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("llm_track_evaluation.py")
SPEC = importlib.util.spec_from_file_location("llm_track_evaluation", MODULE_PATH)
evaluation = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(evaluation)


def test_settlement_excludes_unverified_scores_and_deduplicates_match_ids():
    records = [
        {"match_id": "sporttery-1", "direction": "平局", "top_scores": ["1-1"]},
        {"match_id": "sporttery-1", "direction": "平局", "top_scores": ["1-1"]},
        {"match_id": "sporttery-2", "direction": "主胜", "top_scores": ["2-0"]},
    ]
    results = {
        "sporttery-1": {"score_90": [1, 1], "score_90_status": "verified"},
        "sporttery-2": {"score_90": [2, 0], "score_90_status": "pending"},
    }

    report = evaluation.settle_llm_records(records, results)

    assert [row["match_id"] for row in report["rows"]] == ["sporttery-1"]
    assert report["audit"]["duplicate_match_id"] == 1
    assert report["audit"]["score_90_not_verified"] == 1


def test_evaluation_reports_1x2_draw_and_score_metrics_separately():
    records = [
        {"match_id": "sporttery-1", "direction": "平局", "top_scores": ["1-1"], "top_ou25": "小", "top_hafu": "平平"},
        {"match_id": "sporttery-2", "direction": "主胜", "top_scores": ["2-0"], "top_ou25": "小", "top_hafu": "胜胜"},
    ]
    results = {
        "sporttery-1": {"score_90": [1, 1], "score_90_status": "verified", "half_score": [0, 0]},
        "sporttery-2": {"score_90": [2, 0], "score_90_status": "verified", "half_score": [1, 0]},
    }

    report = evaluation.evaluate_llm_records(records, results)

    assert report["n"] == 2
    assert report["one_x_two"]["accuracy_pct"] == 100.0
    assert report["draw"]["actual_draws"] == 1
    assert report["draw"]["predicted_draws"] == 1
    assert report["draw"]["hits"] == 1
    assert report["score"]["top1_hits"] == 2
    assert report["ou25"]["n"] == 2
    assert report["hafu"]["n"] == 2

