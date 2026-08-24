import importlib.util
import math
from pathlib import Path


SCRIPT = Path(__file__).with_name("predict.py")
spec = importlib.util.spec_from_file_location("predict_under_test", SCRIPT)
predict = importlib.util.module_from_spec(spec)
spec.loader.exec_module(predict)


def _fold_reference(lh, la, lam3, size=11, reference_size=24):
    """High-resolution reference, folding every score >= size into size-1."""
    raw = predict.bp_matrix(lh, la, lam3, n=reference_size)
    folded = {}
    for (home, away), value in raw.items():
        key = (min(home, size - 1), min(away, size - 1))
        folded[key] = folded.get(key, 0.0) + value
    total = sum(folded.values())
    return {key: value / total for key, value in folded.items()}


def test_stable_bp_matrix_preserves_high_goal_tail_mass():
    expected = _fold_reference(5.0, 5.0, 0.20)
    actual = predict.bp_matrix_stable(5.0, 5.0, 0.20, n=11, tail_buffer=13)
    assert math.isclose(sum(actual.values()), 1.0, abs_tol=1e-12)
    assert math.isclose(actual[(10, 10)], expected[(10, 10)], rel_tol=1e-6)
    assert math.isclose(actual[(5, 5)], expected[(5, 5)], rel_tol=1e-6)


def test_stable_bp_matrix_keeps_low_goal_probabilities_nonnegative():
    actual = predict.bp_matrix_stable(0.05, 0.08, 0.20, n=11, tail_buffer=13)
    assert all(value >= 0.0 for value in actual.values())
    assert math.isclose(sum(actual.values()), 1.0, abs_tol=1e-12)
