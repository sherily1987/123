from apifootball_matcher import match_record


def candidate(
    mid,
    home="Arsenal",
    away="PSG",
    kickoff="2026-03-11T20:00:00+08:00",
):
    return {
        "provider_match_id": mid,
        "provider_league_id": 3,
        "competition": "UEFA Champions League",
        "kickoff": kickoff,
        "home": {"name": home},
        "away": {"name": away},
        "score_90_status": "verified",
        "score_90": {"home": 1, "away": 0},
    }


def test_provider_match_id_has_priority():
    record = {
        "provider_refs": {"apifootball_match_id": 22},
        "match": {"home": "wrong", "away": "wrong"},
    }
    result = match_record(record, [candidate(21), candidate(22)], {})
    assert result["status"] == "matched"
    assert result["matched_by"] == "provider_match_id"
    assert result["candidate"]["provider_match_id"] == 22


def test_unique_identity_match_requires_aliases_and_time_window():
    record = {
        "match": {
            "home": "阿森纳",
            "away": "巴黎圣日耳曼",
            "kickoff": "2026-03-11T12:05:00+00:00",
            "league": "欧冠",
        }
    }
    aliases = {"阿森纳": "Arsenal", "巴黎圣日耳曼": "PSG"}
    result = match_record(record, [candidate(22)], aliases)
    assert result["status"] == "matched"
    assert result["matched_by"] == "identity_unique"


def test_multiple_identity_candidates_are_not_auto_settled():
    record = {
        "match": {
            "home": "Arsenal",
            "away": "PSG",
            "kickoff": "2026-03-11T12:00:00+00:00",
            "league": "欧冠",
        }
    }
    result = match_record(record, [candidate(21), candidate(22)], {})
    assert result["status"] == "ambiguous_match"


def test_reversed_home_and_away_do_not_match():
    record = {
        "match": {
            "home": "Arsenal",
            "away": "PSG",
            "kickoff": "2026-03-11T12:00:00+00:00",
            "league": "欧冠",
        }
    }
    result = match_record(record, [candidate(22, home="PSG", away="Arsenal")], {})
    assert result["status"] == "no_match"
