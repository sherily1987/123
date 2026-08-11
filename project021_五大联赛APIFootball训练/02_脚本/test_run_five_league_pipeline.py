from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path


MODULE = Path(__file__).with_name("run_five_league_pipeline.py")
SPEC = importlib.util.spec_from_file_location("pipeline", MODULE)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(pipeline)


def test_pipeline_writes_all_league_statuses_when_one_download_fails(monkeypatch, tmp_path):
    def fake_one_failure(*args, **kwargs):
        return {"rows": [], "failures": [{"month": "2021-07", "error_type": "RuntimeError", "error": "test"}]}

    monkeypatch.setattr(pipeline, "download_history", fake_one_failure)

    result = pipeline.run_pipeline(tmp_path, refresh=False)

    assert set(result["leagues"]) == {"premier_league", "la_liga", "serie_a", "bundesliga", "ligue_1"}
    assert result["status"] == "partial"


def test_pipeline_downloads_provider_odds_once_for_all_event_dates(monkeypatch, tmp_path):
    def fake_complete_history(league_id, start, end, project, slug, *args):
        output = project / "04_素材" / "标准化" / f"{slug}_events.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"match_id": league_id, "league_id": league_id, "kickoff": "2024-08-17T20:00:00", "actual": [1, 0]}) + "\n", encoding="utf-8")
        return {"rows": [{}], "failures": [], "months_reused": [], "months_downloaded": [], "output": str(output)}

    calls = []
    monkeypatch.setattr(pipeline, "download_history", fake_complete_history)
    monkeypatch.setattr(pipeline, "download_odds_for_dates", lambda dates, *args, **kwargs: calls.append(dates) or {"rows": [], "failures": []}, raising=False)
    monkeypatch.setattr(pipeline, "attach_provider_market", lambda events, odds: (events, {}), raising=False)
    monkeypatch.setattr(pipeline.training, "train_one_league", lambda *args, **kwargs: {"status": "trained", "lifecycle": "candidate"})

    pipeline.run_pipeline(tmp_path)

    assert calls == [{date(2024, 8, 17)}]
