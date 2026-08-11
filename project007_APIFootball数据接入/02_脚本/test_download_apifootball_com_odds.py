from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).with_name("download_apifootball_com_odds.py")
SPEC = importlib.util.spec_from_file_location("odds_history", MODULE)
odds_history = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(odds_history)


def test_attach_provider_market_uses_last_pre_kickoff_quote_per_bookmaker():
    events = [{"match_id": 7, "kickoff": "2024-08-17T20:00:00", "actual": [1, 0]}]
    odds = [
        {"match_id": 7, "bookmaker": "A", "observed_at": "2024-08-17 18:00:00", "odds_1x2": [2.0, 3.0, 4.0]},
        {"match_id": 7, "bookmaker": "A", "observed_at": "2024-08-17 21:00:00", "odds_1x2": [9.0, 9.0, 1.1]},
        {"match_id": 7, "bookmaker": "B", "observed_at": "2024-08-17 19:00:00", "odds_1x2": [2.2, 3.1, 3.8]},
    ]

    rows, audit = odds_history.attach_provider_market(events, odds)

    assert rows[0]["provider_market_1x2"] is not None
    assert rows[0]["provider_market_meta"]["bookmaker_count"] == 2
    assert audit["rejected_after_kickoff"] == 1
