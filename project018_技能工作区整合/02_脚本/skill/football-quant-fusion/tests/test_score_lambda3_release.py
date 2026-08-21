from __future__ import annotations

import importlib.util
from pathlib import Path


CORE = (Path(__file__).parents[3] / "core" / "zu-yu-dashi-3" / "scripts" / "predict.py")
SPEC = importlib.util.spec_from_file_location("released_predict", CORE)
predict = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(predict)


def test_released_score_lambda_matches_same_source_time_split_winner():
    """m4's score/O-U matrix must match the independently admitted λ3=0.20."""
    assert predict.SCORE_LAMBDA3 == 0.20
    assert predict.ENGINE_VERSION == "3.4.5"
