from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_sporttery_riji_maps_to_apisports_xG_slug():
    collector = _load("collector", Path(r"F:\HM足球比赛预测\project023_足球预测Web应用\02_脚本\collector.py"))
    assert collector.LEAGUE_SLUG["日职"] == "apisports_japan_j1_league"
    assert collector.LEAGUE_SLUG["日职"] != "fd_jpn"


def test_full_backtest_has_japan_xg_closing_tier_inputs():
    data = json.loads((PROJ / "05_交付" / "full_backtest.json").read_text(encoding="utf-8"))
    row = data["leagues"]["apisports_japan_j1_league"]
    assert row["baseline"] == "closing_market"
    assert "xG" in row["config"]
    assert row["n_subset"] >= 120
    assert isinstance(row["market"], float)
