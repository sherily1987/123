from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "collect_late_info",
    SCRIPTS / "collect_late_info.py",
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)

UTC = timezone.utc


def test_fold_injuries_caps_and_splits_attack_defense():
    raw = {
        "home": {
            "teamShortName": "H",
            "injuriesAndSuspensionsList": [{
                "personName": "Pedrinho",
                "playerPositionCode": "Forward",
                "playerPositionDesc": "前锋",
                "appearanceCnt": 10,
                "startedMatchCnt": 10,
                "injuryFlag": 1,
                "suspensionFlag": 0,
            }],
        },
        "away": {"injuriesAndSuspensionsList": []},
    }
    folded = mod.fold_injuries(raw)
    assert folded["attack_absence_home"] == 0.10
    assert folded["defense_absence_home"] == 0.0
    assert folded["home"]["count"] == 1
    assert folded["away"]["count"] == 0


def test_empty_injury_response_is_traced_but_not_treated_as_clear(tmp_path: Path, monkeypatch):
    rec = {
        "sporttery_meta": {"match_id": 2041028}, "competition": "意甲",
        "home": "博洛尼亚", "away": "拉齐奥",
        "kickoff": "2026-08-25T00:30:00+08:00",
    }
    monkeypatch.setattr(mod, "fetch_injury", lambda _: {"home": {}, "away": {}})

    rows = mod.collect_one(rec, "initial_prematch", want_injury=True,
                           want_lineup=False, events_path=tmp_path / "events.jsonl",
                           now_utc=datetime(2026, 8, 24, 12, 0, tzinfo=UTC))

    assert rows[0]["status"] == "EMPTY_UNCONFIRMED"
    assert rows[0]["absence"]["home"]["status"] == "EMPTY_UNCONFIRMED"


def test_post_kickoff_injury_is_not_fetched_or_admitted(tmp_path: Path, monkeypatch):
    rec = {
        "sporttery_meta": {"match_id": 2041028},
        "home": "博洛尼亚", "away": "拉齐奥",
        "kickoff": "2026-08-25T00:30:00+08:00",
    }
    monkeypatch.setattr(mod, "fetch_injury", lambda _: (_ for _ in ()).throw(AssertionError("post-match fetch")))

    rows = mod.collect_one(rec, "prematch_poll", want_injury=True,
                           want_lineup=False, events_path=tmp_path / "events.jsonl",
                           now_utc=datetime(2026, 8, 25, 1, 0, tzinfo=mod.CST))

    assert rows[0]["kind"] == "injury"
    assert rows[0]["status"] == "POST_KICKOFF"


def test_t75_window_only_inside_75_minutes():
    kick = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    assert mod.in_t75_window(kick, kick - timedelta(minutes=30))
    assert not mod.in_t75_window(kick, kick - timedelta(minutes=120))
    assert not mod.in_t75_window(kick, kick + timedelta(minutes=1))


def test_api_sports_fixture_resolver_matches_chinese_alias_and_kickoff():
    """Removing alias/time matching would leave the dynamic lineup chain without an ID."""
    matches = [{
        "sporttery_meta": {"match_id": 2041028},
        "home": "博洛尼亚",
        "away": "拉齐奥",
        "kickoff": "2026-08-25T00:30:00+08:00",
    }]
    fixtures = [{
        "fixture": {"id": 1550089, "date": "2026-08-24T16:30:00+00:00"}, "league": {"name": "Serie A"},
        "teams": {"home": {"name": "Bologna"}, "away": {"name": "Lazio"}},
    }]

    resolved = mod.resolve_api_sports_fixture_ids(matches, fetch_by_utc_date=lambda _: fixtures)

    assert resolved == {2041028: {"status": "resolved", "fixture_id": 1550089}}
    assert matches[0]["api_sports_fixture_id"] == 1550089


def test_api_sports_fixture_resolver_covers_provider_team_name_variants():
    matches = [
        {"sporttery_meta": {"match_id": 2041033}, "competition": "意甲", "home": "罗马", "away": "佛罗伦萨",
         "kickoff": "2026-08-25T02:45:00+08:00"},
        {"sporttery_meta": {"match_id": 2041037}, "competition": "西甲", "home": "马拉加", "away": "拉科",
         "kickoff": "2026-08-25T03:30:00+08:00"},
        {"sporttery_meta": {"match_id": 2041038}, "competition": "巴甲", "home": "博塔弗戈", "away": "巴竞技",
         "kickoff": "2026-08-25T07:00:00+08:00"},
    ]
    fixtures = [
        {"fixture": {"id": 1550087, "date": "2026-08-24T18:45:00+00:00"}, "league": {"name": "Serie A"},
         "teams": {"home": {"name": "AS Roma"}, "away": {"name": "Fiorentina"}}},
        {"fixture": {"id": 1570349, "date": "2026-08-24T19:30:00+00:00"}, "league": {"name": "La Liga"},
         "teams": {"home": {"name": "Malaga"}, "away": {"name": "Deportivo La Coruna"}}},
        {"fixture": {"id": 1492340, "date": "2026-08-24T23:00:00+00:00"}, "league": {"name": "Serie A"},
         "teams": {"home": {"name": "Botafogo"}, "away": {"name": "Atletico Paranaense"}}},
    ]

    resolved = mod.resolve_api_sports_fixture_ids(matches, fetch_by_utc_date=lambda _: fixtures)

    assert {mid: row["fixture_id"] for mid, row in resolved.items()} == {
        2041033: 1550087, 2041037: 1570349, 2041038: 1492340,
    }


def test_api_sports_fixture_resolver_covers_20260823_sporttery_alias_gaps():
    """Known Sporttery labels must resolve to provider fixtures used by the late-info chain."""
    matches = [
        {"sporttery_meta": {"match_id": 2041018}, "competition": "意甲", "home": "弗洛西诺", "away": "尤文图斯",
         "kickoff": "2026-08-24T00:30:00+08:00"},
        {"sporttery_meta": {"match_id": 2041019}, "competition": "意甲", "home": "威尼斯", "away": "莱切",
         "kickoff": "2026-08-24T00:30:00+08:00"},
        {"sporttery_meta": {"match_id": 2041021}, "competition": "西甲", "home": "赫塔费", "away": "桑坦德",
         "kickoff": "2026-08-24T01:30:00+08:00"},
        {"sporttery_meta": {"match_id": 2041026}, "competition": "美职", "home": "新英格兰", "away": "纽约城",
         "kickoff": "2026-08-24T04:30:00+08:00"},
    ]
    fixtures = [
        {"fixture": {"id": 1550090, "date": "2026-08-23T16:30:00+00:00"}, "league": {"name": "Serie A"},
         "teams": {"home": {"name": "Frosinone"}, "away": {"name": "Juventus"}}},
        {"fixture": {"id": 1550096, "date": "2026-08-23T16:30:00+00:00"}, "league": {"name": "Serie A"},
         "teams": {"home": {"name": "Venezia"}, "away": {"name": "Lecce"}}},
        {"fixture": {"id": 1570348, "date": "2026-08-23T17:30:00+00:00"}, "league": {"name": "La Liga"},
         "teams": {"home": {"name": "Getafe"}, "away": {"name": "Racing Santander"}}},
        {"fixture": {"id": 1490419, "date": "2026-08-23T20:30:00+00:00"}, "league": {"name": "Major League Soccer"},
         "teams": {"home": {"name": "New England Revolution"}, "away": {"name": "New York City FC"}}},
    ]

    resolved = mod.resolve_api_sports_fixture_ids(matches, fetch_by_utc_date=lambda _: fixtures)

    assert {mid: row["fixture_id"] for mid, row in resolved.items()} == {
        2041018: 1550090, 2041019: 1550096, 2041021: 1570348, 2041026: 1490419,
    }


def test_api_sports_fixture_resolver_falls_back_to_adjacent_calendar_date():
    """Provider calendar dates can differ from the UTC date derived from kickoff."""
    matches = [{
        "sporttery_meta": {"match_id": 2041101}, "competition": "意甲",
        "home": "博洛尼亚", "away": "拉齐奥",
        "kickoff": "2026-08-24T00:30:00+08:00",
    }]
    queried = []
    fixture = [{
        "fixture": {"id": 1550101, "date": "2026-08-24T00:30:00+08:00"},
        "league": {"name": "Serie A"},
        "teams": {"home": {"name": "Bologna"}, "away": {"name": "Lazio"}},
    }]

    def fetch(day):
        queried.append(day)
        return fixture if str(day) == "2026-08-24" else []

    resolved = mod.resolve_api_sports_fixture_ids(matches, fetch_by_utc_date=fetch)

    assert resolved == {2041101: {"status": "resolved", "fixture_id": 1550101}}
    assert matches[0]["api_sports_fixture_id"] == 1550101
    assert "2026-08-24" in queried


def test_due_manifest_carries_api_sports_fixture_identity(tmp_path: Path):
    matches = [{
        "sporttery_meta": {"match_id": 2041028},
        "home": "博洛尼亚",
        "away": "拉齐奥",
        "kickoff": "2026-08-25T00:30:00+08:00",
        "api_sports_fixture_id": 1550089,
    }]

    due = mod.write_due(tmp_path / "late_info_due.json", matches, "prematch",
                        now_utc=datetime(2026, 8, 24, 12, 0, tzinfo=UTC))

    assert due[0]["api_sports_fixture_id"] == 1550089
    assert due[0]["lineup_provider"] == "api-sports.io"
    assert due[0]["refresh_policy"] == "scheduled_repoll_until_kickoff"
    assert len(due[0]["refresh_schedule"]) == 7
    assert due[0]["next_refresh_at"] is not None


def test_main_resolves_api_sports_identity_before_writing_due(tmp_path: Path, monkeypatch):
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"matches": [{
        "sporttery_meta": {"match_id": 2041028},
        "home": "博洛尼亚",
        "away": "拉齐奥",
        "kickoff": "2026-08-25T00:30:00+08:00",
    }]}), encoding="utf-8")
    fixture = [{
        "fixture": {"id": 1550089, "date": "2026-08-24T16:30:00+00:00"},
        "teams": {"home": {"name": "Bologna"}, "away": {"name": "Lazio"}},
    }]
    monkeypatch.setattr(mod, "fetch_api_sports_fixtures", lambda _: fixture)
    monkeypatch.setattr(mod, "fetch_injury", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["collect_late_info.py", "--from-collect", str(source),
                                       "--work-dir", str(tmp_path), "--events", str(tmp_path / "events.jsonl")])

    mod.main()

    due = json.loads((tmp_path / "late_info_due.json").read_text(encoding="utf-8"))
    assert due["matches"][0]["api_sports_fixture_id"] == 1550089


def test_main_reuses_one_clock_for_each_batch_and_poll_iteration(tmp_path: Path, monkeypatch):
    """Near kickoff, due scheduling and collection must agree on the same instant."""
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"matches": [{
        "sporttery_meta": {"match_id": 2041028}, "home": "博洛尼亚", "away": "拉齐奥",
        "kickoff": "2026-08-25T00:30:00+08:00",
    }]}), encoding="utf-8")
    batch_now = datetime(2026, 8, 24, 16, 0, tzinfo=UTC)
    poll_now = datetime(2026, 8, 24, 16, 15, tzinfo=UTC)
    clocks = iter((batch_now, poll_now))
    seen = {"windows": [], "collections": []}

    monkeypatch.setattr(mod, "_utc_now", lambda _value=None: next(clocks))
    monkeypatch.setattr(mod, "resolve_api_sports_fixture_ids", lambda *_args: {})
    monkeypatch.setattr(mod, "time", type("Clock", (), {"sleep": staticmethod(lambda _seconds: None)}))

    def write_due(path, matches, snapshot, *, now_utc):
        seen["due"] = now_utc
        return [{}]

    def in_window(kickoff, at=None, window=mod.INITIAL_REFRESH_MINUTES):
        seen["windows"].append(at)
        return True

    def collect_one(*_args, now_utc, **_kwargs):
        seen["collections"].append(now_utc)
        return [{"kind": "lineup", "status": "VALID"}]

    monkeypatch.setattr(mod, "write_due", write_due)
    monkeypatch.setattr(mod, "in_collection_window", in_window)
    monkeypatch.setattr(mod, "collect_one", collect_one)
    monkeypatch.setattr(mod, "should_retry_lineup", lambda _rows: False)
    monkeypatch.setattr(sys, "argv", [
        "collect_late_info.py", "--from-collect", str(source), "--work-dir", str(tmp_path),
        "--events", str(tmp_path / "events.jsonl"), "--watch", "--poll-seconds", "0",
    ])

    mod.main()

    assert seen["due"] is batch_now
    assert seen["windows"] == [batch_now, poll_now]
    assert seen["collections"] == [batch_now, poll_now]


def test_t75_lineup_uses_api_sports_fixture_identity(tmp_path: Path, monkeypatch):
    now = datetime(2026, 8, 24, 16, 0, tzinfo=UTC)
    rec = {
        "sporttery_meta": {"match_id": 2041028},
        "home": "博洛尼亚", "away": "拉齐奥",
        "kickoff": "2026-08-25T00:30:00+08:00",
        "api_sports_fixture_id": 1550089,
    }
    payload = [{
        "team": {"name": "Bologna"},
        "startXI": [{"player": {"name": "Home Starter"}}],
        "substitutes": [],
    }, {
        "team": {"name": "Lazio"},
        "startXI": [{"player": {"name": "Away Starter"}}],
        "substitutes": [],
    }]
    monkeypatch.setattr(mod, "fetch_api_sports_lineup", lambda fixture_id: payload)

    rows = mod.collect_one(rec, "T-75", want_injury=False, want_lineup=True,
                           events_path=tmp_path / "events.jsonl", now_utc=now)

    assert rows[0]["status"] == "VALID"
    assert rows[0]["api_sports_fixture_id"] == 1550089
    assert rows[0]["lineup"]["home"]["starting"] == ["Home Starter"]
    assert rows[0]["lineup"]["away"]["starting"] == ["Away Starter"]


def test_lineup_collection_uses_dynamic_prematch_window_not_t75(tmp_path: Path, monkeypatch):
    now = datetime(2026, 8, 24, 16, 0, tzinfo=UTC)
    rec = {
        "sporttery_meta": {"match_id": 2041028},
        "home": "博洛尼亚", "away": "拉齐奥",
        "kickoff": "2026-08-25T00:30:00+08:00",
        "api_sports_fixture_id": 1550089,
    }
    monkeypatch.setattr(mod, "fetch_api_sports_lineup", lambda fixture_id: [])

    rows = mod.collect_one(rec, "initial_prematch", want_injury=False,
                           want_lineup=True, events_path=tmp_path / "events.jsonl", now_utc=now)

    # 8 hours before kickoff is collected even though it is outside the old
    # The dynamic window is active; a missing provider response remains UNAVAILABLE and is retryable.
    assert rows[0]["status"] == "UNAVAILABLE"
    assert mod.in_collection_window(rec["kickoff"], now)


def test_t75_watcher_retries_until_a_valid_lineup_arrives():
    unavailable = [
        {"kind": "injury", "status": "UNAVAILABLE"},
        {"kind": "lineup", "status": "UNAVAILABLE"},
    ]
    valid = [{"kind": "lineup", "status": "VALID"}]

    assert mod.should_retry_lineup(unavailable) is True
    assert mod.should_retry_lineup(valid) is False


def test_due_and_jsonl_are_research_only(tmp_path: Path):
    matches = [{
        "match_id": 2040907,
        "home": "A",
        "away": "B",
        "kickoff_iso": "2026-08-17T01:00:00+08:00",
        "had_updated_at": "2026-08-16 12:00:00",
        "mode": "market_only",
    }]
    due_path = tmp_path / "late_info_due.json"
    due = mod.write_due(due_path, matches, "T-7h")
    data = json.loads(due_path.read_text(encoding="utf-8"))
    assert data["research_only"] is True
    assert due[0]["match_id"] == 2040907
    assert "t75_at" not in due[0]
    assert data["refresh_policy"] == "initial_plus_poll_until_kickoff"
    row = mod.base_row(
        matches[0], "injury", "T-7h",
        datetime(2026, 8, 16, 8, 0, tzinfo=UTC),
        datetime(2026, 8, 16, 4, 0, tzinfo=UTC),
        datetime(2026, 8, 16, 17, 0, tzinfo=UTC),
    )
    assert row["research_only"] is True
    assert row["production_unchanged"] is True
    assert row["gate"]["late"] is True
    assert "mode" not in row


def test_daily_pipeline_hooks_research_collector_not_record_merge():
    text = (Path(__file__).resolve().parents[1] / "scripts" / "fusion_daily_pipeline.py").read_text(encoding="utf-8")
    assert "collect_late_info.py" in text
    assert "不并入下面的正式登记 input" in text
    rec_idx = text.index("fusion_cli.py', 'record'")
    late_idx = text.index("collect_late_info.py")
    assert late_idx < rec_idx
