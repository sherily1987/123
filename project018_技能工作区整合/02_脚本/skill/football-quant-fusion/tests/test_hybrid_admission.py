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
