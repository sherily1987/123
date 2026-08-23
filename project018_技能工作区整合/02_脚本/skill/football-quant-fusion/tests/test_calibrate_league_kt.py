import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "calibrate_league_kt.py"
spec = importlib.util.spec_from_file_location("calibrate_league_kt", MODULE)
cal = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(cal)


def test_run_league_emits_held_out_candidate_review():
    rows = []
    outcomes = [(2, 0), (1, 1), (0, 1), (1, 0), (2, 2)]
    for index in range(30):
        ft = outcomes[index % len(outcomes)]
        rows.append({
            "league": "TST",
            "day": index + 1,
            "ft": list(ft),
            "pinnacle_close": [2.1, 3.4, 3.8],
        })
    result = cal.run_league(rows)
    review = result["candidate_review"]
    assert review["decision"] in {"candidate", "hold", "no_op"}
    assert set(review["delta_fitted_minus_raw"]) == {"brier_mean", "log_loss", "ece"}
    assert review["production_authorized"] is False
    assert review["regression_tolerance"] == 0.0005
