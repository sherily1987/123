#!/usr/bin/env python3
"""Offline tests for the apifootball.com adapter.

These tests never use a real API key or make a network request.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path


MODULE = Path(__file__).with_name("apifootball_com_adapter.py")
SPEC = importlib.util.spec_from_file_location("apifootball_com_adapter", MODULE)
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(adapter)


def test_build_url_uses_provider_protocol_without_leaking_key():
    url = adapter.build_url("get_countries", {"lang": "cn"}, "secret-key")
    assert "https://apiv3.apifootball.com/?" in url
    assert "action=get_countries" in url
    assert "APIkey=secret-key" in url


def test_redact_url_hides_query_key():
    url = "https://apiv3.apifootball.com/?action=get_countries&APIkey=secret-key"
    assert "secret-key" not in adapter.redact_url(url)
    assert "APIkey=%5BREDACTED%5D" in adapter.redact_url(url)


def test_normalize_leagues_keeps_provider_ids_and_names():
    payload = {
        "success": 1,
        "result": [
            {"league_key": "2", "league_name": "Champions League", "country_key": "1", "country_name": "World"}
        ],
    }
    rows = adapter.normalize_leagues(payload)
    assert rows == [{"league_id": 2, "league_name": "Champions League", "country_id": 1, "country_name": "World"}]


def test_normalize_leagues_accepts_actual_provider_field_names():
    payload = [{"league_id": "146", "league_name": "FA Cup", "country_id": "44", "country_name": "England"}]
    assert adapter.normalize_leagues(payload) == [{"league_id": 146, "league_name": "FA Cup", "country_id": 44, "country_name": "England"}]


def test_normalize_countries_accepts_provider_top_level_array():
    payload = [{"country_id": "18", "country_name": "Austria"}]
    assert adapter.normalize_countries(payload) == [{"country_id": 18, "country_name": "Austria"}]


def test_normalize_events_is_stable_for_missing_optional_fields():
    payload = {
        "success": 1,
        "result": [{
            "match_id": "99",
            "match_date": "2026-08-11",
            "match_time": "20:00",
            "match_hometeam_name": "Home",
            "match_awayteam_name": "Away",
            "match_status": "Not Started",
            "league_name": "Test League",
        }],
    }
    rows = adapter.normalize_events(payload)
    assert rows[0]["match_id"] == 99
    assert rows[0]["home"] == "Home"
    assert rows[0]["away"] == "Away"
    assert rows[0]["goals"] == {"home": None, "away": None}


def test_normalize_standings_accepts_documented_fields():
    payload = [{
        "team_id": "141", "team_name": "Arsenal", "overall_league_position": "1",
        "overall_league_payed": "38", "overall_league_W": "28", "overall_league_D": "5",
        "overall_league_L": "5", "overall_league_PTS": "89", "overall_league_GF": "91",
        "overall_league_GA": "29",
    }]
    row = adapter.normalize_standings(payload)[0]
    assert row["team_id"] == 141
    assert row["team"] == "Arsenal"
    assert row["rank"] == 1
    assert row["played"] == 38
    assert row["points"] == 89


def test_normalize_teams_accepts_documented_badge_field():
    payload = [{"team_key": "141", "team_name": "Arsenal", "team_country": "England", "team_badge": "badge.jpg"}]
    assert adapter.normalize_teams(payload)[0]["logo"] == "badge.jpg"


def test_normalize_match_objects_unwraps_match_id_keyed_statistics():
    payload = {"86392": {"statistics": [{"type": "Corners", "home": "6", "away": "1"}]}}
    rows = adapter.normalize_match_objects(payload)
    assert rows[0]["match_id"] == 86392
    assert rows[0]["statistics"][0]["type"] == "Corners"


def test_normalize_odds_marks_bookmaker_market_not_sporttery():
    rows = adapter.normalize_odds([{
        "match_id": "9", "odd_bookmakers": "bwin", "odd_date": "2026-08-11 12:00:00",
        "odd_1": "2.1", "odd_x": "3.2", "odd_2": "3.6",
    }])
    assert rows[0]["source_type"] == "bookmaker_odds"
    assert rows[0]["odds_1x2"] == [2.1, 3.2, 3.6]
    assert rows[0]["sporttery_compatible"] is False


def test_normalize_predictions_is_provider_benchmark_not_edge():
    rows = adapter.normalize_predictions([{"match_id": "9", "prob_HW": "42", "prob_D": "28", "prob_AW": "30"}])
    assert rows[0]["source_type"] == "PROVIDER_BENCHMARK"
    assert rows[0]["edge_eligible"] is False
    assert rows[0]["probabilities_1x2"] == [0.42, 0.28, 0.30]


def test_client_reads_only_dedicated_environment_variable(monkeypatch):
    monkeypatch.delenv("APIFOOTBALL_COM_KEY", raising=False)
    monkeypatch.setenv("API_FOOTBALL_KEY", "wrong-provider-key")
    try:
        adapter.client()
    except SystemExit as exc:
        assert "APIFOOTBALL_COM_KEY" in str(exc)
    else:
        raise AssertionError("missing dedicated key must fail closed")


def test_request_keeps_no_event_404_as_a_valid_empty_events_response(monkeypatch):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setenv("APIFOOTBALL_COM_KEY", "test-key")
    payload = adapter.request(
        "get_events",
        {"league_id": 152, "from": "2021-07-01", "to": "2021-07-31"},
        opener=lambda request, timeout: Response(b'{"error": 404, "message": "No event found (please check your plan)!"}'),
    )

    assert payload == {"error": 404, "message": "No event found (please check your plan)!"}


def test_skill_runtime_entry_uses_its_own_workspace_source():
    entry = Path(__file__).parents[2] / "project018_技能工作区整合" / "02_脚本" / "skill" / "football-quant-fusion" / "scripts" / "apifootball_com_adapter.py"
    proc = subprocess.run([sys.executable, str(entry), "--help"], text=True, capture_output=True)
    assert proc.returncode == 0
    assert "predictions" in proc.stdout
