from __future__ import annotations

import importlib.util
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
