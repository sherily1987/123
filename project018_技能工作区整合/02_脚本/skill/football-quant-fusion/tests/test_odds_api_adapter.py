import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import odds_api_adapter as oa


def test_unmatched_bulk_fetch_does_not_append_empty_research_row(tmp_path):
    adapter = oa.OddsApiAdapter(
        {"regions": ["eu"], "odds_format": "decimal", "league_map": {},
         "default_sport_keys": ["soccer_epl"]}, "test-key")
    adapter.fetch_odds = lambda sport_key, markets: [{"id": "event-1", "bookmakers": []}]
    report = adapter.run(
        match_file=None, out_path=None, store_dir=tmp_path,
        sport_keys=["soccer_epl"], markets=["h2h"], dry_run=False,
        matches_override=[])
    assert report["matches"] == []
    assert report["write_skipped_reason"] == "no_matched_sporttery_matches"
    assert not (tmp_path / "intl_production.jsonl").exists()


def test_match_event_requires_team_identity_and_pre_match_time_window():
    adapter = oa.OddsApiAdapter(
        {"team_aliases": {"纽卡斯尔": ["Newcastle United"], "利物浦": ["Liverpool"]}}, "test-key")
    events = [{
        "id": "e1", "home_team": "Newcastle United", "away_team": "Liverpool",
        "commence_time": "2026-08-25T19:00:00Z",
    }]
    hit, status = adapter.match_event(
        "soccer_epl", "英超", "2026-08-26T03:00:00+08:00",
        "纽卡斯尔", "利物浦", events)
    assert status == "ok"
    assert hit[1]["id"] == "e1"
    no_hit, no_status = adapter.match_event(
        "soccer_epl", "英超", "2026-08-26T03:00:00+08:00",
        "纽卡斯尔", "阿森纳", events)
    assert no_hit is None and no_status == "no_intl_event"
