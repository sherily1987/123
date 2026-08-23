import importlib
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
mpc = importlib.import_module("market_pool_calibration_backtest")


def test_fit_class_bias_uses_only_given_rows_and_shrinks_ratios():
    rows = [
        {"direct": [0.6, 0.4], "actual": 0},
        {"direct": [0.6, 0.4], "actual": 0},
        {"direct": [0.6, 0.4], "actual": 1},
    ]

    factors = mpc.fit_class_bias(rows, prior_matches=10)

    assert len(factors) == 2
    assert factors[0] > factors[1]
    assert factors[0] < (2 / 1.8)
    assert factors[1] > (1 / 1.2)


def test_three_way_backtest_keeps_final_period_out_of_fit_and_policy_selection():
    rows = []
    for day in range(1, 11):
        rows.append({
            "day": f"2026-08-{day:02d}",
            "labels": ["A", "B"],
            "direct": [0.6, 0.4],
            "actual": 0 if day <= 8 else 1,
            "odds": [2.0, 3.0],
            "match_id": f"m{day}",
        })

    report = mpc.three_way_market_backtest(
        rows,
        fit_fraction=0.6,
        validation_fraction=0.2,
        prior_matches=10,
        minimum_validation_bets=1,
        minimum_test_bets=1,
    )

    assert report["fit_n"] == 6
    assert report["validation_n"] == 2
    assert report["test_n"] == 2
    assert report["selected_on"] == "validation_only"
    assert report["fit_class_counts"] == [6, 0]
    assert report["test_class_counts"] == [0, 2]
    assert report["probability_input"] == "same_market_odds_power_devig_plus_historical_class_bias"
    assert report["class_bias_fit_used_final_period"] is False
