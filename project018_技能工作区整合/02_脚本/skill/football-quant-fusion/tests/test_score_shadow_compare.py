from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "score_shadow_compare.py"
SPEC = importlib.util.spec_from_file_location("score_shadow_compare", MODULE)
shadow = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(shadow)


def test_candidate_score_matrix_is_normalized_and_shadow_only():
    matrix = shadow.bivariate_matrix(1.6, 0.9, lambda3=0.15, temperature=1.1)

    assert round(sum(matrix.values()), 12) == 1.0
    assert matrix["0-0"] > 0

    report = shadow.compare_rows([
        {"league": "西甲", "xg": [1.6, 0.9], "actual_score": "2-0"},
    ])

    assert report["research_only"] is True
    assert report["production_unchanged"] is True
    assert report["big5_candidate"]["n"] == 1
    assert report["big5_candidate"]["score_matrix"]["baseline"]["temperature"] == 1.0
    assert report["big5_candidate"]["score_matrix"]["candidate"]["temperature"] == 1.0
    assert report["big5_candidate"]["top_scores"]["baseline"]["temperature"] == 1.3
    assert report["big5_candidate"]["top_scores"]["candidate"]["temperature"] == 1.1
    assert report["big5_candidate"]["admission"] == "insufficient_n"
