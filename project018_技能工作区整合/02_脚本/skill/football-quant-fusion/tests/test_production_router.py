import sys
import unittest
from pathlib import Path

SCRIPTS = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts")
sys.path.insert(0, str(SCRIPTS))

from production_router import route_matches


def base_match(competition, home, away, kickoff="2026-08-10T20:00:00+08:00"):
    return {
        "home": home, "away": away, "competition": competition, "stage": competition,
        "kickoff": kickoff, "mode": "market_only", "odds": [2.5, 3.2, 2.8], "field_meta": {},
    }


def xg_row(day, home, away, home_xg, away_xg):
    return {"league": "EPL", "datetime": f"{day} 19:00:00", "home": home, "away": away,
            "home_xg": home_xg, "away_xg": away_xg, "home_goals": 1, "away_goals": 0}


def event_row(day, home, away, home_score, away_score, league_id=244):
    return {"match_id": f"{day}-{home}-{away}", "league_id": league_id, "date": day,
            "status": "Finished", "home": home, "away": away,
            "score_home": home_score, "score_away": away_score}


class ProductionRouterTests(unittest.TestCase):
    def test_big5_uses_only_pre_kickoff_rolling_xg_and_sets_audit(self):
        rows = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            rows.append(xg_row(day, "Arsenal", f"Team{i}", 1.5, 0.8))
            rows.append(xg_row(day, f"Team{i}", "Chelsea", 1.1, 1.0))
        rows.append(xg_row("2026-08-11", "Arsenal", "Chelsea", 9.0, 9.0))
        result = route_matches({"matches": [base_match("英超", "Arsenal", "Chelsea")]}, rows, [], min_history=5)
        match = result["matches"][0]
        self.assertEqual(match["mode"], "hybrid")
        self.assertEqual(match["lambda_prior"]["source"], "understat_rolling_xg")
        self.assertEqual(match["field_meta"]["production_router"]["route"], "understat_xg")
        self.assertTrue(match["field_meta"]["production_router"]["no_future_leakage"])
        self.assertEqual(match["lambda_prior"]["sample_legs"], 12)
        self.assertLess(match["lambda_prior"]["lambda_home"], 3)

    def test_other_league_uses_goals_only_route(self):
        events = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            events.append(event_row(day, "Ajax", f"Club{i}", 2, 0))
            events.append(event_row(day, f"Club{i}", "PSV", 0, 1))
        result = route_matches({"matches": [base_match("荷甲", "Ajax", "PSV")]}, [], events, min_history=5)
        match = result["matches"][0]
        self.assertEqual(match["mode"], "hybrid")
        self.assertEqual(match["lambda_prior"]["source"], "apifootball_events_goals_only")
        self.assertEqual(match["field_meta"]["production_router"]["route"], "apifootball_goals_only")

    def test_goals_only_accepts_configured_chinese_team_alias(self):
        events = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            events.append(event_row(day, "KuPS", f"Club{i}", 2, 0))
            events.append(event_row(day, f"Club{i}", "PSV", 0, 1))
        result = route_matches({"matches": [base_match("荷甲", "库奥皮奥", "PSV")]}, [], events, min_history=5)
        match = result["matches"][0]
        self.assertEqual(match["mode"], "hybrid")
        self.assertEqual(match["lambda_prior"]["source"], "apifootball_events_goals_only")

    def test_missing_features_fallbacks_to_market_baseline_with_reason(self):
        result = route_matches({"matches": [base_match("英超", "Unknown A", "Unknown B")]}, [], [], min_history=5)
        match = result["matches"][0]
        self.assertEqual(match["mode"], "market_only")
        audit = match["field_meta"]["production_router"]
        self.assertEqual(audit["route"], "market_baseline")
        self.assertTrue(audit["fallback_reason"])
        self.assertTrue(audit["no_future_leakage"])

    def test_unknown_league_does_not_silently_use_experiment(self):
        result = route_matches({"matches": [base_match("未知联赛", "A", "B")]}, [], [], min_history=1)
        match = result["matches"][0]
        self.assertEqual(match["mode"], "market_only")
        self.assertEqual(match["field_meta"]["production_router"]["route"], "market_baseline")


if __name__ == "__main__":
    unittest.main()
