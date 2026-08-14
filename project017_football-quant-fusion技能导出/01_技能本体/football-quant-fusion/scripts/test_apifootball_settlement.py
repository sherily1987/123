from apifootball_settlement import normalize_event


BASE = {
    "match_id": "7",
    "league_id": "3",
    "league_name": "UEFA Champions League",
    "match_date": "2026-03-11",
    "match_time": "20:00",
    "match_status": "Finished",
    "match_hometeam_id": "1",
    "match_hometeam_name": "Home",
    "match_awayteam_id": "2",
    "match_awayteam_name": "Away",
    "match_hometeam_score": "2",
    "match_awayteam_score": "1",
}


def test_plain_finished_match_has_verified_90_minute_score():
    row = normalize_event(BASE, "2026-08-12T00:00:00+00:00")
    assert row["score_90"] == {"home": 2, "away": 1}
    assert row["score_90_status"] == "verified"


def test_unfinished_match_is_not_settleable():
    row = normalize_event({**BASE, "match_status": "Postponed"}, "t")
    assert row["score_90"] is None
    assert row["score_90_status"] == "not_finished"


def test_extra_time_without_explicit_90_score_is_ambiguous():
    event = {
        **BASE,
        "match_hometeam_extra_score": "2",
        "match_awayteam_extra_score": "1",
    }
    row = normalize_event(event, "t")
    assert row["score_90"] is None
    assert row["score_90_status"] == "ambiguous_extra_time"


def test_penalties_without_explicit_90_score_are_ambiguous():
    event = {
        **BASE,
        "match_hometeam_penalty_score": "5",
        "match_awayteam_penalty_score": "4",
    }
    row = normalize_event(event, "t")
    assert row["score_90"] is None
    assert row["score_penalties"] == {"home": 5, "away": 4}
    assert row["score_90_status"] == "ambiguous_penalties"
