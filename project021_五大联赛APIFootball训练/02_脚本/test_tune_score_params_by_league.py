from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "tune_score", Path(__file__).with_name("tune_score_params_by_league.py"))
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


def test_market_probs_prefers_closing_and_renormalizes():
    row = {"closing_market_1x2": [0.5, 0.3, 0.25], "provider_market_1x2": [0.4, 0.3, 0.3]}
    p = mod.market_probs(row)
    assert p is not None
    assert abs(sum(p) - 1) < 1e-9
    assert p[0] > p[1]


def test_market_probs_none_without_usable_market():
    assert mod.market_probs({"actual": [1, 0]}) is None


def test_load_group_keeps_only_scored_market_rows(tmp_path: Path):
    p = tmp_path / "demo.jsonl"
    rows = [
        {"kickoff": "2024-01-01T12:00:00", "actual": [1, 0], "provider_market_1x2": [0.5, 0.3, 0.2]},
        {"kickoff": "2024-01-02T12:00:00", "actual": [2, 1]},
        {"kickoff": "bad", "actual": [0, 0], "provider_market_1x2": [0.4, 0.3, 0.3]},
    ]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    got = mod.load_group(tmp_path, ["demo.jsonl"])
    assert len(got) == 1
    assert got[0]["ft"] == (1, 0)
    assert got[0]["day"] == "2024-01-01"
