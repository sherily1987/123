import importlib.util
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("hybrid_admission", SCRIPTS / "hybrid_admission.py")
admission = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(admission)


def _evaluation(n=100, brier_delta=-0.01, brier_ci=(-0.02, -0.001),
                logloss_delta=-0.01, logloss_ci=(-0.02, -0.001)):
    return {"n": n, "metrics": {
        "brier": {"delta_hybrid_minus_market": brier_delta, "paired_bootstrap_95_ci": list(brier_ci)},
        "logloss": {"delta_hybrid_minus_market": logloss_delta, "paired_bootstrap_95_ci": list(logloss_ci)},
    }}


def test_admission_blocks_small_sample_or_non_significant_metric():
    small = admission.admission_report(_evaluation(n=38), minimum_n=100)
    crossing = admission.admission_report(_evaluation(brier_ci=(-0.02, 0.001)), minimum_n=100)

    assert small["status"] == "BLOCKED"
    assert "insufficient_sample" in small["reasons"]
    assert crossing["status"] == "BLOCKED"
    assert "brier_ci_not_strictly_below_zero" in crossing["reasons"]
    assert small["production_recommendations_enabled"] is False


def test_admission_only_grants_human_review_not_production_switch():
    report = admission.admission_report(_evaluation(), minimum_n=100)

    assert report["status"] == "ELIGIBLE_FOR_HUMAN_REVIEW"
    assert report["automatic_production_change"] is False
    assert report["production_recommendations_enabled"] is False


def _review_rows(n, brier=-0.02, logloss=-0.02):
    rows = []
    for index in range(n):
        day = 1 + index // 5
        rows.append({
            "match_id": f"sporttery-{index}",
            "kickoff": f"2026-{8 + (day - 1) // 28:02d}-{1 + (day - 1) % 28:02d}T12:00:00+00:00",
            "brier_delta_hybrid_minus_market": brier,
            "logloss_delta_hybrid_minus_market": logloss,
        })
    return rows


def test_review_protocol_blocks_n99_and_requires_both_paired_intervals_below_zero():
    small = admission.review_protocol(_review_rows(99), minimum_n=100, bootstrap_samples=100, bootstrap_seed=7)
    evidence = admission.review_protocol(_review_rows(100), minimum_n=100, bootstrap_samples=100, bootstrap_seed=7)
    crossing_rows = _review_rows(100)
    for index, row in enumerate(crossing_rows[-30:]):
        row["brier_delta_hybrid_minus_market"] = -0.1 if index % 2 else 0.1
    crossing = admission.review_protocol(crossing_rows, minimum_n=100, bootstrap_samples=1000, bootstrap_seed=7)

    assert small["decision"] == "INSUFFICIENT_SAMPLE"
    assert evidence["decision"] == "EVIDENCE_BETTER_THAN_MARKET"
    assert evidence["test"]["brier"]["paired_bootstrap_95_ci"][1] < 0
    assert evidence["test"]["logloss"]["paired_bootstrap_95_ci"][1] < 0
    assert crossing["decision"] == "NO_EVIDENCE"


def test_review_time_split_keeps_same_kickoff_day_together():
    report = admission.review_protocol(_review_rows(100), minimum_n=100, bootstrap_samples=100, bootstrap_seed=7)
    assert report["split"]["method"] == "chronological_70_30_by_kickoff_date_group"
    assert report["split"]["train_through"] < report["split"]["test_from"]
    assert report["automatic_production_change"] is False


def test_review_protocol_treats_zero_as_no_evidence_and_positive_as_harm():
    zero = admission.review_protocol(_review_rows(100, brier=0.0, logloss=-0.02),
                                     bootstrap_samples=100, bootstrap_seed=7)
    harm = admission.review_protocol(_review_rows(100, brier=0.02, logloss=-0.02),
                                     bootstrap_samples=100, bootstrap_seed=7)
    assert zero["decision"] == "NO_EVIDENCE"
    assert zero["test"]["brier"]["paired_bootstrap_95_ci"] == [0.0, 0.0]
    assert harm["decision"] == "EVIDENCE_OF_HARM"
