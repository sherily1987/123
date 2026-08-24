import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("evaluate_score_tail_stability.py")
spec = importlib.util.spec_from_file_location("tail_eval", SCRIPT)
tail_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tail_eval)


def test_stable_matrix_has_same_shape_and_unit_mass():
    import numpy as np

    actual = tail_eval.stable_bp_matrices(
        np.array([1.2, 3.0]), np.array([1.0, 2.2]), 0.20, n=11, tail_buffer=8
    )
    assert actual.shape == (2, 11, 11)
    assert np.allclose(actual.sum(axis=(1, 2)), 1.0)

