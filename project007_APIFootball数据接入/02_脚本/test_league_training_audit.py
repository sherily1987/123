from __future__ import annotations
import importlib.util
from pathlib import Path
import pytest

SPEC=importlib.util.spec_from_file_location("audit",Path(__file__).with_name("league_training_audit.py")); audit=importlib.util.module_from_spec(SPEC); assert SPEC and SPEC.loader; SPEC.loader.exec_module(audit)

def rows(n, seasons, coverage=1.0):
    return [{"league_id":152,"season":str(i%seasons),"kickoff":f"{2020+i//300:04d}-01-{i%28+1:02d}","home_id":i if i/n<coverage else None,"away_id":i+1,"actual":[1,0]} for i in range(n)]

def test_independent_requires_all_thresholds():
    assert audit.classify(rows(900,3,.96),"domestic_league")["tier"] == "independent"

def test_small_league_is_pooled():
    assert audit.classify(rows(299,3),"domestic_league")["tier"] == "pooled"

def test_post_match_statistics_are_rejected():
    with pytest.raises(ValueError,match="POST_MATCH fields: statistics"):
        audit.validate_prematch_record({"statistics":[]})
