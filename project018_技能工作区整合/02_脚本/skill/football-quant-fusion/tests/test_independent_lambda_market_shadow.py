from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_independent_lambda_shadow_module_is_available():
    """Catches removal of the independent four-market research entrypoint."""
    try:
        module = importlib.import_module("independent_lambda_market_shadow")
    except ModuleNotFoundError:
        module = None

    assert module is not None


import independent_lambda_market_shadow as ims


def _crs_labels():
    exact = [
        f"{home}-{away}"
        for home in range(6)
        for away in range(6)
        if not (home == 5 and away in (3, 4, 5))
        and not (away == 5 and home in (3, 4))
    ]
    return exact + ["胜其他", "平其他", "负其他"]


def test_four_market_probabilities_are_normalized_without_odds_input():
    """Catches probability loss in Poisson tails or half/full convolution."""
    result = ims.four_market_probabilities(1.5, 1.0, crs_labels=_crs_labels())

    assert sum(result["HAD"].values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(result["TTG"].values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(result["HAFU"].values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(result["CRS"].values()) == pytest.approx(1.0, abs=1e-9)
    assert max(result["TTG"], key=result["TTG"].get) == "2球"


def test_ttg_candidate_ev_uses_ttg_odds_and_independent_lambda_probability():
    """Catches TTG EV accidentally using HAD prices or a market-implied probability."""
    job = {
        "identity": {"match_id": "sporttery-1", "home": "主队", "away": "客队", "kickoff": "2026-08-23T18:00:00+08:00"},
        "input": {
            "prediction_as_of": "2026-08-23T08:00:00+08:00",
            "odds": [2.0, 2.0, 2.0],
            "ttg": {"odds": [2.0, 2.0, 10.0, 2.0, 2.0, 2.0, 2.0, 2.0]},
            "hafu": {"odds": [2.0] * 9},
            "crs": {label: 2.0 for label in _crs_labels()},
        },
        "research": {
            "hybrid": {
                "research_only": True,
                "lambda_prior": {
                    "lambda_home": 1.2,
                    "lambda_away": 0.8,
                    "source": "understat_rolling_xg",
                },
                "routing_audit": {"no_future_leakage": True, "history_latest": "2026-08-20T18:00:00+08:00"},
                "research_run_at": "2026-08-23T08:05:00+08:00",
            }
        },
    }

    candidates = ims.build_paper_candidates(job)
    ttg = next(row for row in candidates if row["market"] == "TTG")

    assert ttg["selection"] == "2球"
    assert ttg["odds"] == 10.0
    assert ttg["model_probability"] == pytest.approx(0.2706705665, abs=1e-9)
    assert ttg["decimal_ev"] == pytest.approx(1.706705665, abs=1e-9)
    assert ttg["probability_source"] == "independent_prematch_lambda"
    assert ttg["research_only"] is True

    assert ims.build_paper_candidates(
        job, as_of=datetime.fromisoformat("2026-08-23T18:00:01+08:00")
    ) == []


def test_actual_labels_require_verified_half_time_for_hafu():
    """Catches half/full-time truth being fabricated from the full-time score."""
    labels = ims.actual_market_labels(
        {"score_90": {"home": 2, "away": 1}, "score_ht": None},
        crs_labels=["2-1", "胜其他", "平其他", "负其他"],
    )

    assert labels == {"HAD": "胜", "TTG": "3球", "CRS": "2-1", "HAFU": None}


def test_actual_crs_uses_other_bucket_when_exact_score_is_not_offered():
    """Catches unlisted correct scores being dropped instead of settled as other."""
    labels = ims.actual_market_labels(
        {"score_90": {"home": 6, "away": 1}, "score_ht": {"home": 2, "away": 0}},
        crs_labels=["2-1", "胜其他", "平其他", "负其他"],
    )

    assert labels["CRS"] == "胜其他"
    assert labels["HAFU"] == "胜胜"


def test_power_devig_returns_a_normalized_market_baseline():
    """Catches raw overround probabilities leaking into market comparisons."""
    probabilities = ims.power_devig({"胜": 2.0, "平": 2.0, "负": 2.0})

    assert sum(probabilities.values()) == pytest.approx(1.0, abs=1e-12)
    assert probabilities == pytest.approx({"胜": 1 / 3, "平": 1 / 3, "负": 1 / 3})


def test_settled_evaluation_keeps_separate_denominators_and_holds_small_samples():
    """Catches HAFU borrowing full-time denominators or small samples being admitted."""
    job = {
        "identity": {"match_id": "sporttery-2", "home": "主队", "away": "客队", "kickoff": "2026-08-23T18:00:00+08:00"},
        "input": {
            "prediction_as_of": "2026-08-23T08:00:00+08:00",
            "odds": [2.0, 3.0, 4.0],
            "ttg": {"odds": [8.0, 5.0, 4.0, 4.0, 6.0, 10.0, 20.0, 30.0]},
            "hafu": {"odds": [4.0, 10.0, 20.0, 8.0, 5.0, 7.0, 20.0, 12.0, 6.0]},
            "crs": {"2-1": 8.0, "胜其他": 20.0, "平其他": 20.0, "负其他": 20.0},
        },
        "research": {
            "hybrid": {
                "lambda_prior": {
                    "lambda_home": 1.2,
                    "lambda_away": 0.8,
                    "source": "understat_rolling_xg",
                },
                "routing_audit": {"no_future_leakage": True, "history_latest": "2026-08-20T18:00:00+08:00"},
                "research_run_at": "2026-08-23T08:05:00+08:00",
            }
        },
    }
    result = {"status": "finished", "score_90": {"home": 2, "away": 1}, "score_ht": None}

    report = ims.evaluate_settled_pairs([(job, result)])

    assert report["markets"]["HAD"]["n"] == 1
    assert report["markets"]["TTG"]["n"] == 1
    assert report["markets"]["CRS"]["n"] == 1
    assert report["markets"]["HAFU"]["n"] == 0
    assert report["markets"]["HAD"]["admission"] == "hold"
    assert report["markets"]["HAD"]["minimum_n"] == 100
    assert report["markets"]["HAFU"]["minimum_n"] == 200
    bets = ims.settled_paper_bets([(job, result)], market="TTG")
    assert bets[0]["match_id"] == "sporttery-2"
    assert bets[0]["actual"] == "3球"
    assert bets[0]["profit_units"] in {-1.0, bets[0]["odds"] - 1.0}


def test_bet_policy_scan_selects_on_train_and_reports_test_risk():
    bets = [
        {
            "match_id": f"m{i}",
            "kickoff": f"2026-08-{i + 1:02d}T18:00:00+08:00",
            "odds": odds,
            "raw_ev": ev,
            "won": won,
            "profit_units": odds - 1.0 if won else -1.0,
        }
        for i, (odds, ev, won) in enumerate([
            (2.0, 0.05, True),
            (2.0, 0.06, True),
            (9.0, 0.30, False),
            (2.0, 0.07, True),
            (2.0, 0.08, False),
            (9.0, 0.35, False),
            (2.0, 0.09, True),
            (9.0, 0.40, False),
            (9.0, 0.45, False),
            (9.0, 0.50, False),
        ])
    ]

    report = ims.walk_forward_bet_policy_scan(
        bets,
        train_ratio=0.7,
        ev_thresholds=(0.0, 0.1),
        odds_caps=(3.0, 10.0),
        minimum_train_bets=2,
        minimum_test_bets=2,
    )

    assert report["train_n"] == 7
    assert report["test_n"] == 3
    assert report["selected_policy"] == {"minimum_raw_ev": 0.0, "maximum_odds": 3.0}
    assert report["selected_on"] == "train_only"
    assert report["test"]["n"] == 0
    assert report["decision"] == "hold"
    assert report["reason"] == "insufficient_test_bets"


def test_bet_metrics_exposes_longshot_profit_concentration_and_drawdown():
    rows = [
        {"profit_units": -1.0, "won": False, "odds": 12.0},
        {"profit_units": -1.0, "won": False, "odds": 12.0},
        {"profit_units": 11.0, "won": True, "odds": 12.0},
        {"profit_units": -1.0, "won": False, "odds": 12.0},
    ]

    metrics = ims.bet_policy_metrics(rows)

    assert metrics["roi"] == 2.0
    assert metrics["max_drawdown_units"] == 2.0
    assert metrics["largest_winner_profit_share"] == 1.0


def test_build_report_joins_jobs_to_results_by_stable_match_id(tmp_path):
    """Catches evaluation depending on array order or a prefixed/unprefixed ID mismatch."""
    jobs_root = tmp_path / "jobs" / "2026-08-16"
    results_root = tmp_path / "results"
    jobs_root.mkdir(parents=True)
    results_root.mkdir()
    job = {
        "identity": {"match_id": "sporttery-2040001", "home": "主队", "away": "客队", "kickoff": "2026-08-23T18:00:00+08:00"},
        "input": {
            "prediction_as_of": "2026-08-23T08:00:00+08:00",
            "odds": [2.0, 3.0, 4.0],
            "ttg": {"odds": [8.0, 5.0, 4.0, 4.0, 6.0, 10.0, 20.0, 30.0]},
            "hafu": {"odds": [4.0, 10.0, 20.0, 8.0, 5.0, 7.0, 20.0, 12.0, 6.0]},
            "crs": {"2-1": 8.0, "胜其他": 20.0, "平其他": 20.0, "负其他": 20.0},
        },
        "research": {
            "hybrid": {
                "lambda_prior": {"lambda_home": 1.2, "lambda_away": 0.8},
                "routing_audit": {"no_future_leakage": True, "history_latest": "2026-08-20T18:00:00+08:00"},
                "research_run_at": "2026-08-23T08:05:00+08:00",
            }
        },
    }
    (jobs_root / "sporttery-2040001.json").write_text(json.dumps(job), encoding="utf-8")
    result = {"status": "finished", "score_90": {"home": 2, "away": 1}, "score_ht": None}
    (results_root / "2040001.json").write_text(json.dumps(result), encoding="utf-8")
    half_time_evidence = tmp_path / "half_time.json"
    half_time_evidence.write_text(
        json.dumps({
            "rows": [{
                "match_id": "sporttery-2040001",
                "status": "verified",
                "score_ht": {"home": 1, "away": 0},
                "score_90": {"home": 2, "away": 1},
            }]
        }),
        encoding="utf-8",
    )

    report = ims.build_report(tmp_path / "jobs", results_root, half_time_evidence=half_time_evidence)

    assert report["coverage"]["unique_jobs_with_safe_lambda"] == 1
    source_report = report["deterministic_replay_by_source"]["unknown"]
    assert set(source_report["bet_policy_scans"]) == {"HAD", "TTG", "HAFU", "CRS"}
    assert source_report["bet_policy_scans"]["TTG"]["selected_on"] == "train_only"
    assert report["coverage"]["settled_pairs"] == 1
    assert report["evaluation"]["markets"]["HAD"]["n"] == 1
    assert report["evaluation"]["markets"]["HAFU"]["n"] == 1
    assert report["coverage"]["verified_half_time_joined"] == 1
    assert report["market_weight_walk_forward"]["markets"]["HAD"]["decision"] == "hold"


def test_legacy_lambda_claim_is_separated_from_strict_routing_audit():
    """Catches an old 'pre-match' note being promoted to strict no-leakage evidence."""
    job = {
        "identity": {"kickoff": "2026-08-16T20:00:00+08:00"},
        "input": {"prediction_as_of": "2026-08-15T10:00:00+00:00"},
        "research": {
            "hybrid": {
                "lambda_prior": {
                    "lambda_home": 1.2,
                    "lambda_away": 0.8,
                    "source": "apifootball_events_goals_only",
                    "note": "开球前APIfootball Finished历史进球生成λ候选",
                },
                "routing_audit": None,
            }
        },
    }

    assert ims.lambda_evidence_class(job) == "legacy_prematch_claim_only"
    job["input"]["prediction_as_of"] = "2026-08-17T10:00:00+00:00"
    assert ims.lambda_evidence_class(job) == "invalid"


def test_strict_lambda_requires_history_and_research_run_timestamps():
    """Catches no_future_leakage=True being trusted without persisted time evidence."""
    job = {
        "identity": {"kickoff": "2026-08-23T18:00:00+08:00"},
        "input": {"prediction_as_of": "2026-08-23T08:00:00+08:00"},
        "research": {
            "hybrid": {
                "lambda_prior": {"lambda_home": 1.2, "lambda_away": 0.8},
                "routing_audit": {"no_future_leakage": True},
                "research_run_at": "2026-08-23T08:05:00+08:00",
            }
        },
    }

    assert ims.lambda_evidence_class(job) == "invalid"

    job["research"]["hybrid"]["replay_verification"] = {
        "equivalent": True,
        "routing_audit": {
            "no_future_leakage": True,
            "history_latest": "2026-08-20T18:00:00+08:00",
        },
    }
    assert ims.lambda_evidence_class(job) == "deterministic_replay_verified"


def test_walk_forward_weight_scan_selects_independent_signal_when_it_wins_oos():
    """Catches market-weight selection being scored on the same rows used for fitting."""
    pairs = []
    for day in range(1, 7):
        job = {
            "identity": {
                "match_id": f"sporttery-{day}",
                "kickoff": f"2026-08-{day:02d}T18:00:00+08:00",
            },
            "input": {
                "prediction_as_of": f"2026-08-{day:02d}T08:00:00+08:00",
                "odds": [3.0, 3.0, 3.0],
                "ttg": {"odds": [8.0, 5.0, 4.0, 4.0, 6.0, 10.0, 20.0, 30.0]},
                "hafu": {"odds": [4.0, 10.0, 20.0, 8.0, 5.0, 7.0, 20.0, 12.0, 6.0]},
                "crs": {"2-0": 8.0, "胜其他": 20.0, "平其他": 20.0, "负其他": 20.0},
            },
            "research": {
                "hybrid": {
                    "lambda_prior": {"lambda_home": 3.0, "lambda_away": 0.2, "source": "synthetic_xg"},
                    "routing_audit": {"no_future_leakage": True, "history_latest": "2026-07-31T18:00:00+08:00"},
                    "research_run_at": f"2026-08-{day:02d}T08:05:00+08:00",
                }
            },
        }
        pairs.append((job, {"status": "finished", "score_90": {"home": 2, "away": 0}}))

    scan = ims.walk_forward_market_weight_scan(pairs, weights=[0.0, 1.0])

    assert scan["markets"]["HAD"]["train_n"] == 4
    assert scan["markets"]["HAD"]["test_n"] == 2
    assert scan["markets"]["HAD"]["selected_market_weight"] == 0.0
    assert scan["markets"]["HAD"]["test_brier_delta_vs_market"] < 0

    segmented = ims.evaluate_by_lambda_source(pairs)
    assert segmented["synthetic_xg"]["evaluation"]["markets"]["HAD"]["n"] == 6
    had = segmented["synthetic_xg"]["evaluation"]["markets"]["HAD"]
    assert had["brier_delta_ci95"][1] < 0
    assert had["logloss_delta_ci95"][1] < 0
    assert had["paired_ci_both_below_zero"] is True


def test_replay_report_is_attached_only_when_saved_prior_matches():
    """Catches a replay audit from another probability payload being joined by ID alone."""
    job = {
        "identity": {"match_id": "sporttery-1", "kickoff": "2026-08-23T18:00:00+08:00"},
        "input": {"prediction_as_of": "2026-08-23T08:00:00+08:00"},
        "research": {"hybrid": {"lambda_prior": {"lambda_home": 1.2, "lambda_away": 0.8}}},
    }
    replay_rows = {
        "sporttery-1": {
            "status": "equivalent",
            "equivalent": True,
            "saved_prior": {"lambda_home": 1.2, "lambda_away": 0.8},
            "routing_audit": {
                "no_future_leakage": True,
                "history_latest": "2026-08-20T18:00:00+08:00",
            },
        }
    }

    attached = ims.attach_replay_verification(job, replay_rows)
    assert ims.lambda_evidence_class(attached) == "deterministic_replay_verified"

    replay_rows["sporttery-1"]["saved_prior"]["lambda_home"] = 9.9
    rejected = ims.attach_replay_verification(job, replay_rows)
    assert ims.lambda_evidence_class(rejected) == "invalid"
