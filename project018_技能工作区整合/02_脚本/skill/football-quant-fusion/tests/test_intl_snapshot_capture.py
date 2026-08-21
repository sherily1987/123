from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "intl_snapshot_capture.py"
SPEC = importlib.util.spec_from_file_location("intl_snapshot_capture", MODULE)
capture = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(capture)


def test_capture_plan_assigns_only_matches_in_requested_time_windows():
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    raw = {
        "matches": [
            {"match_id": "1", "kickoff": "2026-08-22T12:00:00Z", "league": "英超"},
            {"match_id": "2", "kickoff": "2026-08-21T18:00:00Z", "league": "英超"},
            {"match_id": "3", "kickoff": "2026-08-21T13:15:00Z", "league": "英超"},
            {"match_id": "4", "kickoff": "2026-08-21T14:00:00Z", "league": "英超"},
        ]
    }

    plan = capture.build_plan(raw, now, window_minutes=5)

    assert plan["status"] == "READY"
    assert {(row["match_id"], row["capture_label"]) for row in plan["due_matches"]} == {
        ("sporttery-1", "T-24h"),
        ("sporttery-2", "T-6h"),
        ("sporttery-3", "T-75m"),
    }
    assert plan["outside_window_count"] == 1


def test_capture_plan_is_empty_not_an_api_request_when_no_match_is_due():
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    plan = capture.build_plan({"matches": [
        {"match_id": "1", "kickoff": "2026-08-22T12:30:00Z", "league": "英超"},
    ]}, now, window_minutes=5)

    assert plan["status"] == "NO_DUE_MATCHES"
    assert plan["due_matches"] == []


def test_capture_rejects_a_provider_it_does_not_implement():
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    plan = capture.build_plan({"matches": [
        {"match_id": "1", "kickoff": "2026-08-22T12:00:00Z", "league": "英超"},
    ]}, now, window_minutes=5)

    reports = capture.capture(plan, {"provider": "apifootball"}, Path("unused"), dry_run=False)

    assert reports == [{"status": "skipped", "reason": "unsupported_provider_for_scheduled_capture"}]
