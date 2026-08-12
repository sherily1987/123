import json

import settle_from_apifootball as runner


def finished_event(mid):
    return {
        "match_id": str(mid),
        "league_id": "3",
        "league_name": "UEFA Champions League",
        "match_date": "2026-03-11",
        "match_time": "20:00",
        "match_status": "Finished",
        "match_hometeam_id": "1",
        "match_hometeam_name": "Arsenal",
        "match_awayteam_id": "2",
        "match_awayteam_name": "PSG",
        "match_hometeam_score": "2",
        "match_awayteam_score": "1",
    }


def extra_time_event(mid):
    return {
        **finished_event(mid),
        "match_hometeam_extra_score": "2",
        "match_awayteam_extra_score": "1",
    }


def make_pending_store(tmp_path, provider_match_id=7, existing_score=None):
    store = tmp_path / "backtest"
    records = store / "records"
    records.mkdir(parents=True)
    record_path = records / "prediction.json"
    record = {
        "match_id": "sporttery-1",
        "provider_refs": {"apifootball_match_id": provider_match_id},
        "match": {
            "home": "Arsenal",
            "away": "PSG",
            "kickoff": "2026-03-11T20:00:00+08:00",
            "league": "欧冠",
        },
    }
    record_path.write_text(json.dumps(record), encoding="utf-8")
    (store / "registry.jsonl").write_text(
        json.dumps({"match_id": "sporttery-1", "path": str(record_path)}) + "\n",
        encoding="utf-8",
    )
    if existing_score:
        home, away = [int(value) for value in existing_score.split("-")]
        results = store / "results"
        results.mkdir()
        (results / "sporttery-1.json").write_text(
            json.dumps({"match_id": "sporttery-1", "score_90": {"home": home, "away": away}}),
            encoding="utf-8",
        )
    return store, record


def test_verified_candidate_is_written_once(tmp_path):
    store, _ = make_pending_store(tmp_path, provider_match_id=7)
    written = []
    report = runner.run_settlement(store, [finished_event(7)], {}, False, written.append)
    assert report["settled"] == 1
    assert written[0]["score_90"] == "2-1"


def test_existing_same_result_is_idempotent(tmp_path):
    store, _ = make_pending_store(tmp_path, provider_match_id=7, existing_score="2-1")
    report = runner.run_settlement(store, [finished_event(7)], {}, False, lambda _: None)
    assert report["report"][0]["status"] == "existing_same"


def test_existing_different_result_becomes_source_conflict(tmp_path):
    store, _ = make_pending_store(tmp_path, provider_match_id=7, existing_score="0-0")
    report = runner.run_settlement(store, [finished_event(7)], {}, False, lambda _: None)
    assert report["conflicts"] == 1
    assert report["report"][0]["status"] == "source_conflict"


def test_ambiguous_extra_time_is_needs_review(tmp_path):
    store, _ = make_pending_store(tmp_path, provider_match_id=7)
    report = runner.run_settlement(store, [extra_time_event(7)], {}, False, lambda _: None)
    assert report["report"][0]["status"] == "needs_review"


def test_redact_removes_api_key_from_errors():
    assert "secret" not in runner.redact("URL?APIkey=secret&league_id=3")
