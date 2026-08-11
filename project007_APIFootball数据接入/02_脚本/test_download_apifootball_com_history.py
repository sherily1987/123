from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).with_name("download_apifootball_com_history.py")
SPEC = importlib.util.spec_from_file_location("history", MODULE)
history = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(history)


def test_normalize_finished_event_keeps_only_training_safe_fields():
    row = history.normalize_event({"match_id": "7", "league_id": "152", "league_name": "Premier League", "league_year": "2025/2026", "match_status": "Finished", "match_date": "2025-08-10", "match_time": "20:00", "match_hometeam_id": "1", "match_hometeam_name": "Home", "match_awayteam_id": "2", "match_awayteam_name": "Away", "match_hometeam_score": "2", "match_awayteam_score": "1", "statistics": [{"type": "Shots Total"}]}, "2026-08-11T00:00:00+00:00")
    assert row["actual"] == [2, 1]
    assert row["field_availability"]["statistics"] == "POST_MATCH"
    assert "statistics" not in row


def test_deduplicate_prefers_one_provider_match_id():
    rows = [{"provider": "apifootball.com", "match_id": 7}, {"provider": "apifootball.com", "match_id": 7}]
    assert history.deduplicate(rows) == [rows[0]]
