from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "tune_late", Path(__file__).with_name("tune_late_info_residual.py"))
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)

UTC = timezone.utc


def test_late_gate_requires_info_after_odds_and_before_kickoff():
    odds = datetime(2026, 8, 2, 2, 0, tzinfo=UTC)
    info = datetime(2026, 8, 2, 4, 0, tzinfo=UTC)
    kick = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
    assert mod.is_late_info(info, odds, kick)
    assert not mod.is_late_info(odds, info, kick)
    assert not mod.is_late_info(kick + timedelta(hours=1), odds, kick)
    assert not mod.is_late_info(None, odds, kick)


def test_naive_datetime_is_china_local():
    dt = mod.parse_dt("2026-08-02 11:42:00")
    assert dt == datetime(2026, 8, 2, 3, 42, tzinfo=UTC)


def test_absence_sum_and_adjust_moves_lambda():
    inj = {
        "home": {"attack_absence": 0.2, "defense_absence": 0, "gk_absence": 0},
        "away": {"attack_absence": 0, "defense_absence": 0, "gk_absence": 0},
    }
    adj = mod.absence_dict(inj)
    assert adj["attack_absence_home"] == 0.2
    assert mod.absence_sum(adj) == 0.2
    lh, la, tags = mod.P.apply_fact_adjustments(adj, 1.5, 1.2)
    assert lh < 1.5
    assert "INJURY_ADJUSTED" in tags


def test_decide_adopt_too_small_even_if_better():
    ok, reason = mod.decide_adopt(1.0, 0.5, 20)
    assert not ok and reason == "too_small"
    ok, reason = mod.decide_adopt(1.0, 0.99, 200)
    assert ok


def test_load_late_info_events_reads_research_jsonl(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps({
        "kind": "injury",
        "research_only": True,
        "match_id": 2040907,
        "home": "A",
        "away": "B",
        "kickoff": "2026-08-17T01:00:00+08:00",
        "collected_at": "2026-08-16T12:00:00+00:00",
        "absence": {
            "attack_absence_home": 0.1,
            "attack_absence_away": 0,
            "defense_absence_home": 0,
            "defense_absence_away": 0,
            "gk_absence_home": 0,
            "gk_absence_away": 0,
            "home": {"count": 1},
            "away": {"count": 0},
        },
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    rows = mod.load_late_info_events(path)
    assert len(rows) == 1
    assert rows[0]["match_id"] == 2040907
    assert rows[0]["absence"]["attack_absence_home"] == 0.1
