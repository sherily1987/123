from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path


MODULE = Path(__file__).with_name("train_five_leagues.py")
SPEC = importlib.util.spec_from_file_location("five_training", MODULE)
training = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(training)


def test_time_cutoffs_keep_same_kickoff_day_together():
    rows = []
    for day, count in (("2021-08-01", 4), ("2021-08-02", 3), ("2021-08-03", 3), ("2021-08-04", 3)):
        rows.extend({"kickoff": f"{day}T20:00:00"} for _ in range(count))

    first, second = training.time_cutoffs(rows)

    assert first == datetime.fromisoformat("2021-08-03").date().toordinal()
    assert second == datetime.fromisoformat("2021-08-04").date().toordinal()


def test_training_loads_core_prediction_helpers():
    assert training.strength.dc_matrix is not None
    assert training.strength.dc_one is not None


def test_training_quality_rejects_an_unconverged_fit():
    quality = training.training_quality.assess({
        "converged": False,
        "teams": ["home", "away"],
        "alpha": [0.1, -0.1],
        "beta": [0.0, 0.0],
        "weighted_n": [10.0, 10.0],
        "home_adv": 0.2,
        "rho": -0.08,
        "fun": 12.0,
    })

    assert quality["status"] == "REJECTED"
    assert "optimizer_not_converged" in quality["reasons"]


def test_training_does_not_write_candidate_when_final_fit_fails_quality(monkeypatch, tmp_path):
    source = tmp_path / "events.jsonl"
    rows = [
        {"kickoff": f"2024-01-{day:02d}T20:00:00"}
        for day in range(1, 11)
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    league = {"id": 1, "slug": "test", "name": "Test"}
    monkeypatch.setattr(training.audit, "validate_prematch_record", lambda row: None)
    monkeypatch.setattr(training.audit, "classify", lambda rows, kind: {"tier": "independent"})
    matches = [
        {"day": datetime.fromisoformat(row["kickoff"]).date().toordinal()}
        for row in rows
    ]
    monkeypatch.setattr(training.strength, "load_matches", lambda *args, **kwargs: matches)
    monkeypatch.setattr(training.strength, "fit_model", lambda *args, **kwargs: {
        "converged": False, "teams": ["a", "b"], "alpha": [0.0, 0.0],
        "beta": [0.0, 0.0], "weighted_n": [10.0, 10.0], "home_adv": 0.2,
        "rho": -0.08, "fun": 1.0,
    })

    result = training.train_one_league(source, league, tmp_path / "models")

    assert result["status"] == "training_rejected"
    assert result["lifecycle"] == "candidate"
    assert not (tmp_path / "models" / "test_candidate.json").exists()


def test_half_life_override_requires_explicit_held_out_evidence():
    policy = training.training_policy
    rejected = policy.resolve_half_life("test", {
        "test": {"half_life": 120.0, "oos": {"n": 500, "brier_delta": -0.01}}
    })
    accepted = policy.resolve_half_life("test", {
        "test": {
            "half_life": 120.0,
            "oos": {"n": 500, "brier_delta": -0.01, "split": "held_out"},
            "approved_by": "human_review",
        }
    })

    assert rejected["half_life"] == policy.DEFAULT_HALF_LIFE
    assert rejected["status"] == "DEFAULT_LOCKED"
    assert accepted == {"half_life": 120.0, "status": "OOS_APPROVED"}
