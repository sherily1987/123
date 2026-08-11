from __future__ import annotations
import importlib.util
from pathlib import Path
import pytest
SPEC=importlib.util.spec_from_file_location("market",Path(__file__).with_name("provider_market_input.py")); market=importlib.util.module_from_spec(SPEC); assert SPEC and SPEC.loader; SPEC.loader.exec_module(market)

def test_provider_primary_input_has_no_sporttery_labels():
    item=market.build_input({"match_id":9,"home":"A","away":"B"},[{"match_id":9,"bookmaker":"bwin","observed_at":"2026-08-11","odds_1x2":[2.1,3.2,3.6],"source_type":"bookmaker_odds"}])
    assert item["provider_only"] is True and "had" not in item

def test_provider_prediction_cannot_be_market_input():
    with pytest.raises(ValueError,match="PROVIDER_BENCHMARK"):
        market.build_input({"match_id":9},[{"match_id":9,"source_type":"PROVIDER_BENCHMARK"}])
