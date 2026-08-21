import importlib.util
import json
import math
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("hybrid_evaluation", SCRIPTS / "hybrid_evaluation.py")
evaluation = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(evaluation)


def _job(match_id, hybrid, *, prediction_as_of="2026-08-21T10:00:00+00:00",
         kickoff="2026-08-21T12:00:00+00:00", score="2-1"):
    return {
        "identity": {"match_id": match_id, "home": "Home", "away": "Away"},
        "input": {"prediction_as_of": prediction_as_of, "kickoff": kickoff},
        "research": {"hybrid": hybrid},
        "settlement": {"score_90": score},
    }


def _write_job(root, name, job):
    folder = root / "2026-08-21"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"sporttery-{name}.json").write_text(json.dumps(job), encoding="utf-8")


def test_evaluation_only_counts_independent_prematch_hybrid_pairs(tmp_path):
    eligible = {
        "research_only": True,
        "status": "ok",
        "mode": "hybrid",
        "final_1x2_pct": [60, 25, 15],
        "market_1x2_pct": [50, 30, 20],
        "lambda_prior": {"source": "independent_strength"},
    }
    _write_job(tmp_path, "eligible", _job("sporttery-eligible", eligible))
    _write_job(tmp_path, "market-derived", _job("sporttery-market-derived", {
        **eligible, "market_derived": True,
    }))
    _write_job(tmp_path, "no-prior", _job("sporttery-no-prior", {
        key: value for key, value in eligible.items() if key != "lambda_prior"
    }))
    _write_job(tmp_path, "post-kickoff", _job(
        "sporttery-post-kickoff", eligible,
        prediction_as_of="2026-08-21T12:01:00+00:00",
    ))

    report = evaluation.evaluate_jobs(tmp_path)

    assert report["n"] == 1
    assert report["excluded"] == {
        "market_derived": 1,
        "missing_independent_prior": 1,
        "not_prematch": 1,
    }
    assert report["metrics"]["brier"]["hybrid"] == 0.245
    assert report["metrics"]["brier"]["market"] == 0.38
    assert report["metrics"]["brier"]["delta_hybrid_minus_market"] == -0.135
    assert report["metrics"]["logloss"]["hybrid"] == round(-math.log(0.6), 6)
    assert report["metrics"]["logloss"]["market"] == round(-math.log(0.5), 6)


def test_paired_bootstrap_interval_is_reproducible(tmp_path):
    good = {
        "research_only": True, "status": "ok", "mode": "hybrid",
        "final_1x2_pct": [60, 25, 15], "market_1x2_pct": [50, 30, 20],
        "lambda_prior": {"source": "independent_strength"},
    }
    bad = {
        "research_only": True, "status": "ok", "mode": "hybrid",
        "final_1x2_pct": [40, 35, 25], "market_1x2_pct": [50, 30, 20],
        "lambda_prior": {"source": "independent_strength"},
    }
    _write_job(tmp_path, "good", _job("sporttery-good", good))
    _write_job(tmp_path, "bad", _job("sporttery-bad", bad))

    first = evaluation.evaluate_jobs(tmp_path, bootstrap_samples=100, bootstrap_seed=7)
    second = evaluation.evaluate_jobs(tmp_path, bootstrap_samples=100, bootstrap_seed=7)

    assert first["metrics"] == second["metrics"]
    ci = first["metrics"]["brier"]["paired_bootstrap_95_ci"]
    assert len(ci) == 2
    assert ci[0] <= first["metrics"]["brier"]["delta_hybrid_minus_market"] <= ci[1]


def test_cli_creates_parent_directory_for_report(tmp_path):
    output = tmp_path / "nested" / "report.json"

    assert evaluation.main(["--jobs-root", str(tmp_path), "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["n"] == 0


def test_weight_sweep_is_scored_as_separate_research_candidates(tmp_path):
    hybrid = {
        "research_only": True, "status": "ok", "mode": "hybrid",
        "final_1x2_pct": [60, 25, 15], "market_1x2_pct": [50, 30, 20],
        "lambda_prior": {"source": "independent_strength"},
        "weight_sweep": [
            {"research_only": True, "status": "ok", "market_weight": 0.4,
             "final_1x2_pct": [65, 20, 15], "market_1x2_pct": [50, 30, 20]},
            {"research_only": True, "status": "ok", "market_weight": 0.8,
             "final_1x2_pct": [55, 30, 15], "market_1x2_pct": [50, 30, 20]},
        ],
    }
    _write_job(tmp_path, "sweep", _job("sporttery-sweep", hybrid))

    report = evaluation.evaluate_jobs(tmp_path)

    sweep = report["weight_sweep"]["by_market_weight"]
    assert sweep["0.4"]["n"] == 1
    assert sweep["0.8"]["n"] == 1
    assert sweep["0.4"]["metrics"]["brier"]["candidate"] < sweep["0.8"]["metrics"]["brier"]["candidate"]
