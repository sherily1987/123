import importlib.util
from pathlib import Path


SCRIPT = Path(r"F:\HM足球比赛预测\project017_football-quant-fusion技能导出\01_技能本体\football-quant-fusion/scripts/production_route_evaluation.py")
spec = importlib.util.spec_from_file_location("production_route_evaluation", SCRIPT)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def _row(track, match_id, cohort_key, score, probs):
    return {
        "track": track,
        "match_id": match_id,
        "cohort_key": cohort_key,
        "official_90min_score": score,
        "prediction_as_of": "2026-01-01T09:00:00Z",
        "kickoff": "2026-01-01T10:00:00Z",
        "probs": probs,
        "top_scores": ["1-0", "0-0", "2-0"],
    }


def test_strict_pairs_require_same_match_official_result_and_cohort():
    quant = [_row("quant", "m1", "current-v1", [1, 0], [0.6, 0.2, 0.2]),
             _row("quant", "m2", "current-v1", [0, 1], [0.2, 0.6, 0.2])]
    llm = [_row("llm", "m1", "current-v1", [1, 0], [0.5, 0.3, 0.2]),
           _row("llm", "m2", "legacy-v0", [0, 1], [0.2, 0.5, 0.3])]

    pairs, excluded = evaluation.build_strict_pairs(quant, llm, current_cohort_key="current-v1")

    assert [pair["match_id"] for pair in pairs] == ["m1"]
    assert pairs[0]["cohort"] == "current"
    assert any(row["match_id"] == "m2" and row["reason"] == "cohort_key_mismatch" for row in excluded)


def test_insufficient_strict_pairs_reports_complete_metrics_without_superiority_claim():
    row = {
        "match_id": "m1", "cohort_key": "current-v1", "official_90min_score": [1, 0],
        "experiment_probs": [0.6, 0.2, 0.2], "market_probs": [0.5, 0.3, 0.2],
        "experiment_top_scores": ["1-0", "0-0", "2-0"],
        "market_top_scores": ["0-0", "1-0", "0-1"],
    }
    report = evaluation.evaluate_paired([row], min_matches=100, current_cohort_key="current-v1")

    assert report["status"] == "insufficient_paired_samples"
    assert report["superiority_conclusion"] is None
    assert report["metrics"]["experiment"]["1x2"] is not None
    assert report["metrics"]["experiment"]["score_top1"] is not None
    assert report["metrics"]["experiment"]["score_top3"] is not None
    assert report["metrics"]["experiment"]["brier"] is not None
    assert report["metrics"]["experiment"]["log_loss"] is not None
    assert report["metrics"]["experiment"]["calibration"] is None
    assert report["market_paired_deltas"]["brier_experiment_minus_market"] is None
    assert report["cohort_counts"] == {"current": 1, "legacy": 0, "unknown": 0}
