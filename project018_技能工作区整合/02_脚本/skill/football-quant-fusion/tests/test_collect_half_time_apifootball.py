from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "collect_half_time_apifootball.py"
SPEC = importlib.util.spec_from_file_location("collect_half_time_apifootball", MODULE)
collector = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(collector)


def test_kickoff_dates_only_include_finished_90_minute_registered_matches():
    rows = [
        ({"match": {"kickoff": "2026-08-02T00:00:00+08:00"}},
         {"status": "finished", "settlement_scope": "90min"}),
        ({"match": {"kickoff": "2026-08-03T00:00:00+08:00"}},
         {"status": "finished", "settlement_scope": "extra_time"}),
        ({"match": {"kickoff": "bad"}}, {"status": "finished", "settlement_scope": "90min"}),
    ]

    assert collector.kickoff_dates(rows) == ["2026-08-02"]


def test_payload_rows_accept_provider_list_and_reject_non_list():
    assert collector.payload_rows([{"match_id": "1"}]) == [{"match_id": "1"}]
    assert collector.payload_rows({"result": []}) == []
