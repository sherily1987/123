from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

SPEC = importlib.util.spec_from_file_location(
    "tune_nb", Path(__file__).with_name("tune_score_negbin.py"))
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


def test_nb_pmf_sums_to_one():
    p = mod.nb_pmf(np.array([1.2, 0.8]), 8.0)
    assert p.shape == (2, mod.base.N)
    np.testing.assert_allclose(p.sum(axis=1), 1.0, atol=1e-9)


def test_nb_matrices_normalized_and_fatter_tails_than_low_r():
    lh = np.array([1.3])
    la = np.array([1.1])
    tight = mod.nb_matrices(lh, la, 16.0)
    wide = mod.nb_matrices(lh, la, 3.0)
    np.testing.assert_allclose(tight.sum(), 1.0, atol=1e-9)
    # 更小的 r 方差更大，角上 0-0 或高比分质量应不低于更尖的分布
    corner = tight[0, 0, 0] + tight[0, -1, -1]
    corner_w = wide[0, 0, 0] + wide[0, -1, -1]
    assert corner_w >= corner - 1e-9
