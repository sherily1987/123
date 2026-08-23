import importlib
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
hir = importlib.import_module("historical_independent_market_replay")
ims = importlib.import_module("independent_lambda_market_shadow")


def _match():
    return {
        "matchId": 123,
        "matchNumStr": "周六001",
        "kickoff_iso": "2026-08-23T18:00:00+08:00",
        "leagueAbbName": "测试联赛",
        "homeTeamAbbName": "主队",
        "awayTeamAbbName": "客队",
        "sectionsNo999": "2:1",
        "sectionsNo1": "1:0",
        "closing_pre_match": {
            "had": {"h": "2.00", "d": "3.20", "a": "4.10", "updateDate": "2026-08-23", "updateTime": "17:50:00"},
            "ttg": {**{f"s{i}": str(3 + i) for i in range(8)}, "updateDate": "2026-08-23", "updateTime": "17:51:00"},
            "hafu": {
                "hh": "4", "hd": "8", "ha": "20", "dh": "6", "dd": "5",
                "da": "9", "ah": "25", "ad": "12", "aa": "7",
                "updateDate": "2026-08-23", "updateTime": "17:52:00",
            },
            "crs": {
                "s00s00": "8", "s01s00": "7", "s02s01": "9",
                "s-1sh": "30", "s-1sd": "40", "s-1sa": "35",
                "updateDate": "2026-08-23", "updateTime": "17:53:00",
            },
        },
    }


def test_match_to_pair_preserves_corresponding_pools_and_verified_scores():
    seen = {}

    def route_fn(match, understat, events, min_history, enable_experimental):
        seen.update(match)
        return {
            **match,
            "lambda_prior": {
                "lambda_home": 1.4,
                "lambda_away": 0.9,
                "source": "apifootball_events_goals_only",
                "sample_legs": 20,
                "team_sample_sizes": {"home": 10, "away": 10},
            },
            "field_meta": {"production_router": {
                "no_future_leakage": True,
                "history_latest": "2026-08-20T18:00:00+00:00",
            }},
        }

    pair, reason = hir.match_to_pair(_match(), [], [], route_fn=route_fn)

    assert reason is None
    job, result = pair
    assert seen["kickoff"] == "2026-08-23T18:00:00+08:00"
    assert job["input"]["odds"] == [2.0, 3.2, 4.1]
    assert job["input"]["ttg"]["odds"] == [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert job["input"]["hafu"]["odds"] == [4.0, 8.0, 20.0, 6.0, 5.0, 9.0, 25.0, 12.0, 7.0]
    assert job["input"]["crs"]["2-1"] == 9.0
    assert set(("胜其他", "平其他", "负其他")) <= set(job["input"]["crs"])
    assert result["score_90"] == {"home": 2, "away": 1}
    assert result["score_ht"] == {"home": 1, "away": 0}
    labels = ims.actual_market_labels(result, crs_labels=list(job["input"]["crs"]))
    assert labels == {"HAD": "胜", "TTG": "3球", "CRS": "2-1", "HAFU": "胜胜"}
    assert ims.lambda_evidence_class(job) == "strict_no_future_leakage"


def test_match_to_pair_rejects_missing_independent_history():
    def no_prior(match, understat, events, min_history, enable_experimental):
        return {**match, "field_meta": {"production_router": {"fallback_reason": "no_history"}}}

    pair, reason = hir.match_to_pair(_match(), [], [], route_fn=no_prior)

    assert pair is None
    assert reason == "no_independent_lambda"


def test_build_report_counts_route_failures_without_calling_them_samples():
    matches = [_match(), {**_match(), "matchId": 124, "homeTeamAbbName": "未知队"}]

    def route_fn(match, understat, events, min_history, enable_experimental):
        if match["home"] == "未知队":
            return {**match, "field_meta": {"production_router": {"fallback_reason": "no_history"}}}
        return {
            **match,
            "lambda_prior": {
                "lambda_home": 1.4, "lambda_away": 0.9, "source": "test",
                "sample_legs": 20, "team_sample_sizes": {"home": 10, "away": 10},
            },
            "field_meta": {"production_router": {
                "no_future_leakage": True,
                "history_latest": "2026-08-20T18:00:00+00:00",
            }},
        }

    report = hir.build_report(matches, [], [], route_fn=route_fn)

    assert report["coverage"]["source_matches"] == 2
    assert report["coverage"]["independent_lambda_pairs"] == 1
    assert report["coverage"]["excluded_by_reason"] == {"no_independent_lambda": 1}
    assert report["evaluation"]["markets"]["TTG"]["n"] == 1
    assert report["source_policy"]["same_match_odds_used_as_probability_input"] is False


def test_chronological_lambda_calibration_fits_only_early_score_totals():
    pairs = []
    for day, score in enumerate(((2, 1), (2, 1), (2, 1), (0, 4)), start=1):
        match = _match()
        match["matchId"] = 200 + day
        match["kickoff_iso"] = f"2026-08-{day:02d}T18:00:00+08:00"
        for pool in match["closing_pre_match"].values():
            pool["updateDate"] = f"2026-08-{day:02d}"
            pool["updateTime"] = "17:00:00"
        match["sectionsNo999"] = f"{score[0]}:{score[1]}"

        def route_fn(route_input, understat, events, min_history, enable_experimental):
            return {
                **route_input,
                "lambda_prior": {
                    "lambda_home": 1.0, "lambda_away": 1.0, "source": "test",
                    "sample_legs": 20, "team_sample_sizes": {"home": 10, "away": 10},
                },
                "field_meta": {"production_router": {
                    "no_future_leakage": True,
                    "history_latest": "2025-12-31T18:00:00+00:00",
                }},
            }

        pair, reason = hir.match_to_pair(match, [], [], route_fn=route_fn)
        assert reason is None
        pairs.append(pair)

    report = hir.chronological_lambda_calibration(pairs, train_fraction=0.75)

    assert report["train_n"] == 3
    assert report["test_n"] == 1
    assert report["lambda_multipliers"] == {"home": 2.0, "away": 1.0}
    # The late 0:4 result must not contaminate the fitted away multiplier.
    assert report["fit_policy"] == "score_only_train_period_no_same_match_odds"
    assert report["calibrated_test_evaluation"]["markets"]["HAD"]["n"] == 1
