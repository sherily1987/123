"""Regression coverage for fixed-date evidence fixtures.

These examples intentionally retain the August 2026 kickoffs used by the
original module tests.  The injected UTC clock keeps their pre-match behavior
deterministic instead of depending on the wall clock that runs the suite.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


bec = _load("bb_browser_evidence_collect")
late = _load("collect_late_info")
hybrid = _load("hybrid_shadow")
prematch = _load("prematch_evidence_collect")

NOW = datetime.fromisoformat("2026-08-24T12:00:00+00:00")


@pytest.mark.parametrize(
    "entry",
    [
        lambda tmp: bec.collect_one({"match_id": "bb"}, None, now_utc=datetime(2026, 8, 24)),
        lambda tmp: late.collect_one(
            {}, "prematch", False, False, tmp / "events.jsonl",
            now_utc=datetime(2026, 8, 24),
        ),
        lambda tmp: hybrid.run_one(
            None, {}, {"match_id": "hybrid"}, [], [], 5, None,
            now_utc=datetime(2026, 8, 24),
        ),
        lambda tmp: prematch.collect_one(
            {"match_id": "prematch"}, now_utc=datetime(2026, 8, 24),
        ),
    ],
    ids=["browser", "late-info", "hybrid", "prematch"],
)
def test_public_entrypoints_reject_naive_injected_utc_clock(entry, tmp_path):
    with pytest.raises(ValueError, match="timezone-aware"):
        entry(tmp_path)


def test_bb_collect_file_keeps_fixed_fixture_in_prematch_window(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"matches": [{
        "home": "A", "away": "B", "competition": "测试联赛",
        "kickoff": "2026-08-26T03:00:00+08:00",
        "sporttery_meta": {"match_id": 2040999},
    }]}), encoding="utf-8")

    report = bec.collect_file(source, tmp_path / "out", None, now_utc=NOW)

    assert report["rows"][0]["status"] == "pending_browser_task"


def test_late_collectors_keep_fixed_fixture_in_prematch_window(tmp_path, monkeypatch):
    rec = {
        "sporttery_meta": {"match_id": 2041028}, "home": "博洛尼亚", "away": "拉齐奥",
        "kickoff": "2026-08-25T00:30:00+08:00", "api_sports_fixture_id": 1550089,
    }
    monkeypatch.setattr(late, "fetch_injury", lambda _: {"home": {}, "away": {}})

    rows = late.collect_one(rec, "initial_prematch", want_injury=True,
                            want_lineup=False, events_path=tmp_path / "events.jsonl", now_utc=NOW)
    due = late.write_due(tmp_path / "due.json", [rec], "prematch", now_utc=NOW)

    assert rows[0]["status"] == "EMPTY_UNCONFIRMED"
    assert due[0]["next_refresh_at"] is not None


def test_hybrid_run_one_keeps_fixed_fixture_in_prematch_window(monkeypatch, tmp_path):
    match = {
        "match_id": "sporttery-1", "home": "A", "away": "B", "competition": "英超",
        "kickoff": "2026-08-25T00:00:00+00:00",
    }
    monkeypatch.setattr(hybrid, "route_match", lambda *_args, **_kwargs: {
        "research_only": True, "field_meta": {"production_router": {"fallback_reason": "no_prior"}},
    })
    monkeypatch.setattr(hybrid, "jobs_root", lambda: tmp_path)
    monkeypatch.setattr(hybrid, "upsert_job", lambda *_args, **_kwargs: tmp_path / "job.json")

    result = hybrid.run_one(None, {}, match, [], [], 5, "2026-08-24", now_utc=NOW)

    assert result["reason"] == "no_prior"


def test_prematch_collect_one_keeps_fixed_fixture_in_prematch_window(monkeypatch):
    monkeypatch.setattr(prematch.preview, "collect", lambda *_args, **_kwargs: {
        "feature": {}, "strength": None, "recent_home": [], "recent_away": [],
        "injuries": {}, "tables": [],
    })

    row = prematch.collect_one({
        "match_id": "sporttery-2", "home": "A", "away": "B",
        "kickoff": "2026-08-25T20:00:00+08:00",
    }, now_utc=NOW)

    assert "collection_guard" not in row
