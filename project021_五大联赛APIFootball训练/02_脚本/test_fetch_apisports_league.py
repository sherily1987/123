from __future__ import annotations

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("fetch_apisports", Path(__file__).with_name("fetch_apisports_league.py"))
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


def test_normalize_keeps_finished_score_and_provider():
    row = {
        "fixture": {"id": 1, "date": "2024-08-16T18:00:00+00:00", "status": {"long": "Match Finished"}},
        "teams": {"home": {"id": 10, "name": "ADO Den Haag"}, "away": {"id": 11, "name": "Cambuur"}},
        "goals": {"home": 2, "away": 1},
    }
    rec = mod.normalize(row, 89, "Eerste Divisie", 2024, "t")
    assert rec["provider"] == "api-sports.io"
    assert rec["league_id"] == 89
    assert rec["status"] == "Finished"
    assert rec["actual"] == [2, 1]
    assert rec["home"] == "ADO Den Haag"
    assert "provider_market" not in rec
    assert "closing_market_1x2" not in rec
