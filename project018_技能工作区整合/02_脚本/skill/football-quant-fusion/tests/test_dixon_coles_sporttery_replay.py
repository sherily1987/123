import importlib
import sys
from datetime import date
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
dcsr = importlib.import_module("dixon_coles_sporttery_replay")


def test_replay_chunk_fits_only_training_matches_before_chunk_start():
    training = [
        {"day": date(2026, 1, day).toordinal(), "home": "Home", "away": "Away"}
        for day in range(1, 11)
    ]
    sporttery = [{
        "matchId": 1,
        "kickoff_iso": "2026-01-10T18:00:00+08:00",
        "leagueAbbName": "英超",
        "homeTeamAbbName": "Home",
        "awayTeamAbbName": "Away",
        "sectionsNo999": "2:1",
        "sectionsNo1": "1:0",
        "closing_pre_match": {
            "had": {"h": "2", "d": "3", "a": "4", "updateDate": "2026-01-10", "updateTime": "17:00:00"},
            "ttg": {**{f"s{i}": str(3 + i) for i in range(8)}, "updateDate": "2026-01-10", "updateTime": "17:00:00"},
            "hafu": {**dict(zip(("hh", "hd", "ha", "dh", "dd", "da", "ah", "ad", "aa"), (4, 8, 20, 6, 5, 9, 25, 12, 7))), "updateDate": "2026-01-10", "updateTime": "17:00:00"},
            "crs": {"s00s00": "8", "s02s01": "9", "s-1sh": "30", "s-1sd": "40", "s-1sa": "35", "updateDate": "2026-01-10", "updateTime": "17:00:00"},
        },
    }]
    captured = {}

    def fit_fn(rows, half_life):
        captured["days"] = [row["day"] for row in rows]
        return {"teams": {"Home": {}, "Away": {}}}

    def predict_fn(model, home, away):
        return {"status": "VALID", "lambda_home": 1.5, "lambda_away": 0.8}

    pairs, excluded = dcsr.replay_league_pairs(
        sporttery,
        training,
        half_life=120,
        min_train=1,
        fit_fn=fit_fn,
        predict_fn=predict_fn,
    )

    assert len(pairs) == 1
    assert max(captured["days"]) < date(2026, 1, 10).toordinal()
    job, _ = pairs[0]
    assert job["research"]["hybrid"]["lambda_prior"]["source"] == "dixon_coles_walk_forward"
    assert excluded == {}
    league_reports = dcsr.competition_reports(pairs)
    assert league_reports["英超"]["evaluation"]["markets"]["HAD"]["n"] == 1


def test_canonical_team_requires_controlled_exact_or_alias_match():
    assert dcsr.canonical_team({"Manchester City", "Arsenal"}, "Manchester City") == "Manchester City"
    assert dcsr.canonical_team({"id:1": {"Manchester City"}, "id:2": {"Arsenal"}}, "Manchester City") == "id:1"
    assert dcsr.canonical_team({"Manchester City", "Arsenal"}, "Unknown") is None


def test_predict_with_fallback_uses_train_fitted_newcomer_prior():
    model = {
        "teams": ["id:1"], "alpha": [0.1], "beta": [-0.1], "home_adv": 0.2,
        "fallback": {"alpha": -0.2, "beta": 0.2, "basis": "newcomer_prior"},
    }

    result = dcsr.predict_with_fallback(model, "id:new", "id:1", lambda _: {"id:1": 0})

    assert result["status"] == "VALID"
    assert result["fallback_used"] is True
    assert result["lambda_home"] > 0
    assert result["lambda_away"] > 0


def test_replay_reports_unmatched_team_name_instead_of_generic_no_lambda():
    training = [{"day": date(2026, 1, 1).toordinal(), "home": "id:1", "away": "id:2", "home_name": "Home", "away_name": "Away"}]
    match = {
        "matchId": 2, "kickoff_iso": "2026-01-10T18:00:00+08:00", "leagueAbbName": "英超",
        "homeTeamAbbName": "Unknown", "awayTeamAbbName": "Away",
    }

    pairs, excluded = dcsr.replay_league_pairs(
        [match], training, half_life=120, min_train=1,
        fit_fn=lambda rows, half_life: {}, predict_fn=lambda model, home, away: {},
    )

    assert pairs == []
    assert excluded == {"unmatched_team:Unknown": 1}
