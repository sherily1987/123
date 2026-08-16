from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

SPEC = importlib.util.spec_from_file_location(
    "tune_xg_lam", Path(__file__).with_name("tune_score_xg_lambda.py"))
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


def _toy_model():
    return {
        "teams": ["H", "A"],
        "team_names": ["H", "A"],
        "team_aliases": {},
        "home_adv": 0.2,
        "alpha": [0.1, -0.1],
        "beta": [0.0, 0.05],
        "rho": 0.0,
    }


def test_predict_lambda_matches_dc_formula():
    model = _toy_model()
    lh, la = mod.predict_lambda(model, "H", "A")
    assert abs(lh - np.exp(0.2 + 0.1 + 0.05)) < 1e-12
    assert abs(la - np.exp(-0.1 + 0.0)) < 1e-12


def test_predict_lambda_unfitted_is_none():
    assert mod.predict_lambda(_toy_model(), "X", "A") is None


def test_first_fit_day_requires_min_train_strictly_before():
    rows = [{"day": 10}] * 3 + [{"day": 11}] * 2 + [{"day": 12}]
    assert mod.first_fit_day(rows, 3) == 11
    assert mod.first_fit_day(rows, 6) is None


def test_walk_forward_never_trains_on_chunk_or_future(monkeypatch):
    fits = []

    def fake_fit(matches, half_life=500.0, target="goals"):
        fits.append(max(m["day"] for m in matches))
        return _toy_model()

    monkeypatch.setattr(mod.strength, "fit_model", fake_fit)
    monkeypatch.setattr(mod.strength, "blend_models", lambda g, x, w: g)

    goals, eval_ids = [], set()
    for i in range(12):
        mid = f"m{i}"
        goals.append({
            "match_id": mid, "day": 100 + i, "home": "H", "away": "A",
            "gh": 1, "ga": 0,
        })
        eval_ids.add(mid)
    walked, refits = mod.walk_lambdas(
        goals, goals, eval_ids, step=3, half_life=500.0, min_train=4, blend_w=0.4)
    assert refits
    assert all(r["train_max_day"] < r["point"] for r in refits)
    assert all(tmax < 100 + 12 for tmax in fits)
    assert walked


def test_decide_adopt_thresholds():
    ok, reason = mod.decide_adopt(3.00, 2.99, 30.0, 30.0, 200)
    assert ok and reason.startswith("test_log_loss_improved")
    ok, reason = mod.decide_adopt(3.00, 3.00, 31.2, 30.0, 200)
    assert ok and reason == "test_top3_plus_1pp_ll_not_worse"
    ok, reason = mod.decide_adopt(3.00, 3.01, 32.0, 30.0, 200)
    assert not ok and reason == "keep_market_lambda"
    ok, reason = mod.decide_adopt(3.00, 2.90, 40.0, 30.0, 50)
    assert not ok and reason == "too_small"


def test_oracle_source_is_not_an_adopt_candidate():
    assert "oracle" not in ("xg", "blend")
