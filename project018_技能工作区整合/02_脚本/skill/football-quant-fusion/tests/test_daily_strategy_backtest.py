import importlib.util
import json
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "daily_strategy_backtest.py"
spec = importlib.util.spec_from_file_location("daily_strategy_backtest", MODULE)
dbt = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(dbt)


def _plan():
    return {
        "snapshot_id": "snap-1", "selected_day": "2026-08-23",
        "single_purchase_recommendations": [
            {"match_id": "sporttery-1", "market": "HAD", "selection": "胜", "odds": 2.0, "stake_amount": 10},
            {"match_id": "sporttery-2", "market": "TTG", "selection": "2球", "odds": 3.0, "stake_amount": 10},
            {"match_id": "sporttery-3", "market": "HAFU", "selection": "胜胜", "odds": 4.0, "stake_amount": 10},
            {"match_id": "sporttery-4", "market": "CRS", "selection": "1-0", "odds": 5.0, "stake_amount": 10},
        ],
        "combo_purchase_recommendations": [{
            "combo_id": "c1", "combined_odds": 4.0, "stake_amount": 10,
            "legs": [
                {"match_id": "sporttery-1", "market": "HAD", "selection": "胜", "odds": 2.0},
                {"match_id": "sporttery-4", "market": "CRS", "selection": "1:0", "odds": 5.0},
            ],
        }],
    }


def test_scores_markets_and_excludes_pending_hafu_from_roi(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    payloads = {
        "sporttery-1": {"match_id": "sporttery-1", "score_90": {"home": 2, "away": 0}},
        "sporttery-2": {"match_id": "sporttery-2", "score_90": {"home": 1, "away": 1}},
        "sporttery-3": {"match_id": "sporttery-3", "score_90": {"home": 2, "away": 0}},
        "sporttery-4": {"match_id": "sporttery-4", "score_90": {"home": 1, "away": 0}},
    }
    for match_id, payload in payloads.items():
        (results / f"{match_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    report = dbt.build_report([_plan()], results)
    summary = report["summary"]
    assert summary["recommendation_count"] == 5
    assert summary["won_count"] == 4
    assert summary["pending_count"] == 1
    assert summary["settled_stake"] == 40
    assert summary["profit"] == 100
    assert summary["roi_pct"] == 250.0
    hafu = next(row for row in report["daily"][0]["records"] if row["market"] == "HAFU")
    assert hafu["status"] == "pending"


def test_combo_loses_when_one_leg_loses(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    for match_id, score in (("sporttery-1", (0, 1)), ("sporttery-4", (1, 0))):
        (results / f"{match_id}.json").write_text(json.dumps({"match_id": match_id, "score_90": {"home": score[0], "away": score[1]}}), encoding="utf-8")
    report = dbt.build_report([_plan()], results)
    combo = next(row for row in report["daily"][0]["records"] if row["market"] == "COMBO")
    assert combo["status"] == "lost"
    assert combo["profit"] == -10
