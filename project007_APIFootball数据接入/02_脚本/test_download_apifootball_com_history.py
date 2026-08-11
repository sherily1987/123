from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
import pytest

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


FINISHED_EVENT = {
    "match_id": "7", "league_id": "152", "league_name": "Premier League", "league_year": "2021/2022",
    "match_status": "Finished", "match_date": "2021-07-10", "match_time": "20:00",
    "match_hometeam_id": "1", "match_hometeam_name": "Home", "match_awayteam_id": "2", "match_awayteam_name": "Away",
    "match_hometeam_score": "2", "match_awayteam_score": "1",
}


def test_download_history_reuses_a_valid_monthly_raw_block(tmp_path, monkeypatch):
    raw = tmp_path / "04_素材" / "apifootball_com_raw" / "premier_league" / "2021-07.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"response": [FINISHED_EVENT]}), encoding="utf-8")
    monkeypatch.setattr(history.adapter, "request", lambda *_: pytest.fail("must reuse cached month"))

    report = history.download_history(152, date(2021, 7, 1), date(2021, 7, 31), tmp_path, "premier_league", False, 0, 0)

    assert report["months_reused"] == ["2021-07"]
    assert len(report["rows"]) == 1


def test_download_history_records_month_failure_without_leaking_a_key(tmp_path, monkeypatch):
    monkeypatch.setattr(
        history.adapter,
        "request",
        lambda *_: (_ for _ in ()).throw(RuntimeError("HTTP 429 APIkey=secret-value")),
    )

    report = history.download_history(152, date(2021, 7, 1), date(2021, 7, 31), tmp_path, "premier_league", True, 0, 0)

    assert report["rows"] == []
    assert report["failures"][0]["error_type"] == "RuntimeError"
    assert "secret-value" not in report["failures"][0]["error"]
