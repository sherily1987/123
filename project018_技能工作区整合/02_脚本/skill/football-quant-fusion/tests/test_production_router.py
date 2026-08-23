import sys
import unittest
from pathlib import Path

SCRIPTS = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts")
sys.path.insert(0, str(SCRIPTS))

from production_router import GOALS_ONLY, load_event_rows, route_matches, _same_team


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
    def test_sporttery_chinese_names_match_understat(self):
        pairs = [
            ("阿森纳", "Arsenal"),
            ("曼城", "Manchester City"),
            ("曼彻斯特城", "Manchester City"),
            ("狼队", "Wolverhampton Wanderers"),
            ("塞维利亚", "Sevilla"),
            ("巴列卡诺", "Rayo Vallecano"),
            ("皇马", "Real Madrid"),
            ("毕尔巴鄂竞技", "Athletic Club"),
            ("AC米兰", "AC Milan"),
            ("国际米兰", "Inter"),
            ("帕尔马", "Parma Calcio 1913"),
            ("巴黎圣日尔曼", "Paris Saint Germain"),
            ("巴黎圣曼", "Paris Saint Germain"),
            ("拜仁慕尼黑", "Bayern Munich"),
            ("门兴", "Borussia M.Gladbach"),
            ("莱比锡红牛", "RasenBallsport Leipzig"),
        ]
        for zh, en in pairs:
            self.assertTrue(_same_team(en, zh), f"{zh} should match {en}")

    def test_trained_league_sporttery_names_match_events(self):
        pairs = [
            ("前进之鹰", "Go Ahead Eagles"),
            ("前进之鹰", "GO Ahead Eagles"),
            ("PSV埃因霍温", "PSV"),
            ("埃因霍温", "PSV"),
            ("里斯本竞技", "Sporting CP"),
            ("博德闪耀", "Bodo/Glimt"),
            ("汉坎", "Ham-Kam"),
            ("汉坎", "HamKam"),
            ("蔚山现代", "Ulsan Hyundai FC"),
            ("吉达联合", "Al-Ittihad FC"),
            ("拉斯永恒", "Al Kholood"),
            ("拉斯决心", "Al-Hazm"),
            ("穆拜征服", "Al-Fateh"),
            ("达曼协定", "Al-Ettifaq"),
            ("迈季宽广", "Al-Fayha"),
            ("库奥皮奥", "KuPS"),
            ("布鲁马波", "IF Brommapojkarna"),
            ("谢菲联", "Sheffield Utd"),
            ("弗鲁米嫩", "Fluminense"),
            ("鹿岛鹿角", "Kashima Antlers"),
            ("兹林尼斯基", "Zrinjski"),
            ("比森阿泰尔", "Atert Bissen"),
            ("沙尔克04", "Schalke 04"),
            ("盐湖城", "Real Salt Lake"),
            ("迈阿密国际", "Inter Miami"),
        ]
        for zh, en in pairs:
            self.assertTrue(_same_team(en, zh), f"{zh} should match {en}")

    def test_big5_uses_only_pre_kickoff_rolling_xg_and_sets_audit(self):
        rows = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            rows.append(xg_row(day, "Arsenal", f"Team{i}", 1.5, 0.8))
            rows.append(xg_row(day, f"Team{i}", "Chelsea", 1.1, 1.0))
        rows.append(xg_row("2026-08-11", "Arsenal", "Chelsea", 9.0, 9.0))
        result = route_matches({"matches": [base_match("英超", "Arsenal", "Chelsea")]}, rows, [], min_history=5)
        match = result["matches"][0]
        self.assertEqual(match["mode"], "market_only")
        self.assertNotIn("lambda_prior", match)
        self.assertEqual(match["research_candidate"]["lambda_prior"]["source"], "understat_rolling_xg")
        self.assertEqual(match["field_meta"]["production_router"]["route"], "understat_xg")
        self.assertTrue(match["field_meta"]["production_router"]["no_future_leakage"])
        self.assertEqual(match["research_candidate"]["lambda_prior"]["team_sample_sizes"],
                         {"home": 6, "away": 6})
        self.assertLess(match["research_candidate"]["lambda_prior"]["lambda_home"], 3)

    def test_explicit_research_route_can_apply_experimental_prior(self):
        rows = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            rows.append(xg_row(day, "Arsenal", f"Team{i}", 1.5, 0.8))
            rows.append(xg_row(day, f"Team{i}", "Chelsea", 1.1, 1.0))
        result = route_matches(base_match("英超", "Arsenal", "Chelsea"), rows, [],
                               min_history=5, enable_experimental=True)
        self.assertEqual(result["mode"], "hybrid")
        self.assertEqual(result["lambda_prior"]["source"], "understat_rolling_xg")
        self.assertTrue(result["research_only"])

    def test_other_league_uses_goals_only_route(self):
        events = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            events.append(event_row(day, "Ajax", f"Club{i}", 2, 0))
            events.append(event_row(day, f"Club{i}", "PSV", 0, 1))
        result = route_matches({"matches": [base_match("荷甲", "Ajax", "PSV")]}, [], events, min_history=5)
        match = result["matches"][0]
        self.assertEqual(match["mode"], "market_only")
        self.assertEqual(match["research_candidate"]["lambda_prior"]["source"], "apifootball_events_goals_only")
        self.assertEqual(match["field_meta"]["production_router"]["route"], "apifootball_goals_only")

    def test_goals_only_accepts_api_sports_completion_labels_and_90_minute_score(self):
        events = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            events.append({"date": day, "status": "FT", "home": "Ajax", "away": f"Club{i}", "score_90": "2-0"})
            events.append({"date": day, "status": "After Pen.", "home": f"Club{i}", "away": "PSV",
                           "score": {"fulltime": {"home": 0, "away": 1}}, "score_penalty": {"home": 4, "away": 3}})
        result = route_matches({"matches": [base_match("荷甲", "Ajax", "PSV")]}, [], events, min_history=5)
        match = result["matches"][0]
        self.assertEqual(match["mode"], "market_only")
        self.assertEqual(match["research_candidate"]["lambda_prior"]["source"], "apifootball_events_goals_only")

    def test_goals_only_accepts_configured_chinese_team_alias(self):
        events = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            events.append(event_row(day, "KuPS", f"Club{i}", 2, 0))
            events.append(event_row(day, f"Club{i}", "PSV", 0, 1))
        result = route_matches({"matches": [base_match("荷甲", "库奥皮奥", "PSV")]}, [], events, min_history=5)
        match = result["matches"][0]
        self.assertEqual(match["mode"], "market_only")
        self.assertEqual(match["research_candidate"]["lambda_prior"]["source"], "apifootball_events_goals_only")

    def test_each_team_must_independently_meet_history_minimum(self):
        rows = [xg_row(f"2026-08-0{i}", "Arsenal", f"Team{i}", 1.5, 0.8) for i in range(1, 7)]
        rows.append(xg_row("2026-08-01", "Other", "Chelsea", 1.0, 1.1))
        match = route_matches(base_match("英超", "Arsenal", "Chelsea"), rows, [], min_history=5)
        self.assertEqual(match["mode"], "market_only")
        self.assertNotIn("research_candidate", match)
        self.assertEqual(match["field_meta"]["production_router"]["fallback_reason"],
                         "understat_pre_kickoff_history_unavailable")

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

    def test_sporttery_aliases_open_goals_only_routes(self):
        self.assertIn("瑞超", GOALS_ONLY)
        self.assertIn("沙职", GOALS_ONLY)
        self.assertIn("芬超", GOALS_ONLY)
        self.assertIn("韩职", GOALS_ONLY)
        self.assertIn("日职", GOALS_ONLY)
        self.assertIn("巴甲", GOALS_ONLY)
        self.assertIn("英冠", GOALS_ONLY)
        self.assertIn("法乙", GOALS_ONLY)
        self.assertIn("苏超", GOALS_ONLY)
        self.assertIn("欧冠", GOALS_ONLY)
        self.assertIn("欧罗巴", GOALS_ONLY)
        self.assertIn("欧联", GOALS_ONLY)
        self.assertIn("欧协联", GOALS_ONLY)
        self.assertEqual(GOALS_ONLY["欧冠"], 3)
        self.assertEqual(GOALS_ONLY["欧罗巴"], 4)
        self.assertEqual(GOALS_ONLY["欧协联"], 683)
        for name in (
            "欧超杯", "解放者杯", "南美杯", "亚冠精英", "亚冠乙", "世界杯",
            "阿甲", "美职", "荷乙", "日乙", "德乙", "澳超", "英甲", "英社区盾",
            "中超", "英足总杯", "非洲杯",
        ):
            self.assertIn(name, GOALS_ONLY)

    def test_actual_scores_and_string_league_id_route_championship(self):
        events = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            events.append({
                "match_id": f"{day}-su", "league_id": "E1", "kickoff": f"{day}T12:00:00+00:00",
                "status": "Finished", "home": "Sheffield United", "away": f"Club{i}",
                "actual": [2, 0],
            })
            events.append({
                "match_id": f"{day}-bir", "league_id": "E1", "kickoff": f"{day}T15:00:00+00:00",
                "status": "Finished", "home": f"Club{i}", "away": "Birmingham",
                "actual": [0, 1],
            })
        match = route_matches(base_match("英冠", "谢菲联", "伯明翰"), [], events, min_history=5)
        self.assertEqual(match["mode"], "market_only")
        self.assertEqual(match["research_candidate"]["lambda_prior"]["source"], "apifootball_events_goals_only")
        self.assertEqual(match["field_meta"]["production_router"]["route"], "apifootball_goals_only")

    def test_ucl_goals_route_uses_champions_league_events_only(self):
        events = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            events.append({
                "match_id": f"{day}-ucl", "league_id": 3, "kickoff": f"{day}T19:00:00+00:00",
                "status": "Finished", "home": "Benfica", "away": f"Club{i}", "actual": [2, 0],
            })
            events.append({
                "match_id": f"{day}-ucl2", "league_id": 3, "kickoff": f"{day}T21:00:00+00:00",
                "status": "Finished", "home": f"Club{i}", "away": "Ajax", "actual": [0, 1],
            })
            events.append({
                "match_id": f"{day}-ere", "league_id": 244, "kickoff": f"{day}T18:00:00+00:00",
                "status": "Finished", "home": "Ajax", "away": f"Club{i}", "actual": [6, 0],
            })
        match = route_matches(base_match("欧冠", "本菲卡", "阿贾克斯"), [], events, min_history=5)
        self.assertEqual(match["mode"], "market_only")
        self.assertNotIn("lambda_prior", match)
        prior = match["research_candidate"]["lambda_prior"]
        self.assertEqual(prior["source"], "apifootball_events_goals_only")
        self.assertLess(prior["lambda_home"], 4.0)

    def test_norway_253_does_not_eat_mls_events(self):
        events = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            events.append({
                "match_id": f"{day}-nor", "league_id": 253, "provider": "apifootball.com",
                "league_name": "Eliteserien", "kickoff": f"{day}T17:00:00+00:00",
                "status": "Finished", "home": "Brann", "away": f"Club{i}", "actual": [2, 0],
            })
            events.append({
                "match_id": f"{day}-nor2", "league_id": 253, "provider": "apifootball.com",
                "league_name": "Eliteserien", "kickoff": f"{day}T19:00:00+00:00",
                "status": "Finished", "home": f"Club{i}", "away": "HamKam", "actual": [0, 1],
            })
            events.append({
                "match_id": f"{day}-mls", "league_id": 253, "provider": "api-sports.io",
                "league_name": "Major League Soccer", "kickoff": f"{day}T01:00:00+00:00",
                "status": "Finished", "home": "Brann", "away": f"Club{i}", "actual": [8, 0],
            })
            events.append({
                "match_id": f"{day}-mls2", "league_id": 253, "provider": "api-sports.io",
                "league_name": "Major League Soccer", "kickoff": f"{day}T03:00:00+00:00",
                "status": "Finished", "home": f"Club{i}", "away": "HamKam", "actual": [0, 1],
            })
        norway = route_matches(base_match("挪超", "布兰", "汉坎"), [], events, min_history=5)
        mls = route_matches(base_match("美职", "布兰", "汉坎"), [], events, min_history=5)
        self.assertEqual(norway["research_candidate"]["lambda_prior"]["source"], "apifootball_events_goals_only")
        self.assertEqual(mls["research_candidate"]["lambda_prior"]["source"], "apifootball_events_goals_only")
        self.assertGreater(
            mls["research_candidate"]["lambda_prior"]["lambda_home"],
            norway["research_candidate"]["lambda_prior"]["lambda_home"],
        )

    def test_continental_cups_open_goals_route(self):
        events = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            events.append({
                "match_id": f"{day}-lib", "league_id": 13, "kickoff": f"{day}T00:00:00+00:00",
                "status": "Finished", "home": "Palmeiras", "away": f"Club{i}", "actual": [2, 0],
            })
            events.append({
                "match_id": f"{day}-lib2", "league_id": 13, "kickoff": f"{day}T02:00:00+00:00",
                "status": "Finished", "home": f"Club{i}", "away": "Flamengo RJ", "actual": [0, 1],
            })
            events.append({
                "match_id": f"{day}-afc", "league_id": 17, "kickoff": f"{day}T12:00:00+00:00",
                "status": "Finished", "home": "Ulsan Hyundai FC", "away": f"Club{i}", "actual": [1, 0],
            })
            events.append({
                "match_id": f"{day}-afc2", "league_id": 17, "kickoff": f"{day}T14:00:00+00:00",
                "status": "Finished", "home": f"Club{i}", "away": "Gamba Osaka", "actual": [0, 2],
            })
        lib = route_matches(base_match("解放者杯", "帕梅拉斯", "弗拉门戈"), [], events, min_history=5)
        afc = route_matches(base_match("亚冠精英", "蔚山现代", "大阪钢巴"), [], events, min_history=5)
        self.assertEqual(lib["mode"], "market_only")
        self.assertEqual(afc["mode"], "market_only")
        self.assertEqual(lib["research_candidate"]["lambda_prior"]["source"], "apifootball_events_goals_only")
        self.assertEqual(afc["research_candidate"]["lambda_prior"]["source"], "apifootball_events_goals_only")

    def test_sweden_and_saudi_307_do_not_share_history(self):
        events = []
        for i in range(1, 7):
            day = f"2026-08-0{i}"
            events.append({
                "match_id": f"{day}-swe", "league_id": 307, "provider": "apifootball.com",
                "league_name": "Allsvenskan - Regular Season", "kickoff": f"{day}T18:00:00+00:00",
                "status": "Finished", "home": "GAIS", "away": f"Club{i}", "actual": [4, 0],
            })
            events.append({
                "match_id": f"{day}-sau", "league_id": 307, "provider": "api-sports.io",
                "league_name": "Pro League", "kickoff": f"{day}T18:00:00+00:00",
                "status": "Finished", "home": "Al-Ittihad FC", "away": f"Club{i}", "actual": [1, 0],
            })
            events.append({
                "match_id": f"{day}-swe2", "league_id": 307, "provider": "apifootball.com",
                "league_name": "Allsvenskan - Regular Season", "kickoff": f"{day}T20:00:00+00:00",
                "status": "Finished", "home": f"Club{i}", "away": "Malmo FF", "actual": [0, 2],
            })
            events.append({
                "match_id": f"{day}-sau2", "league_id": 307, "provider": "api-sports.io",
                "league_name": "Pro League", "kickoff": f"{day}T20:00:00+00:00",
                "status": "Finished", "home": f"Club{i}", "away": "Al Kholood", "actual": [0, 1],
            })
        sweden = route_matches(base_match("瑞超", "盖斯", "马尔默"), [], events, min_history=5)
        saudi = route_matches(base_match("沙职", "吉达联合", "拉斯永恒"), [], events, min_history=5)
        self.assertEqual(sweden["mode"], "market_only")
        self.assertEqual(saudi["mode"], "market_only")
        self.assertEqual(sweden["research_candidate"]["lambda_prior"]["source"], "apifootball_events_goals_only")
        self.assertEqual(saudi["research_candidate"]["lambda_prior"]["source"], "apifootball_events_goals_only")
        self.assertGreater(
            sweden["research_candidate"]["lambda_prior"]["lambda_home"],
            saudi["research_candidate"]["lambda_prior"]["lambda_home"],
        )

    def test_real_standardized_events_open_trained_league_routes(self):
        std = Path(r"F:\HM足球比赛预测\project021_五大联赛APIFootball训练\04_素材\标准化")
        if not std.is_dir():
            self.skipTest("standardized events unavailable")
        kickoff = "2026-08-16T20:00:00+08:00"
        cases = [
            ("瑞超", "布鲁马波", "厄格里特", "sweden_allsvenskan_events.jsonl"),
            ("沙职", "吉达联合", "拉斯永恒", "saudi_pro_league_events.jsonl"),
            ("芬超", "玛丽港", "塞伊奈", "finland_veikkausliiga_events.jsonl"),
            ("英冠", "谢菲联", "伯明翰", "fd_e1_events.jsonl"),
            ("韩职", "仁川联", "金泉尚武", "apisports_korea_k_league_1_events.jsonl"),
            ("日职", "浦和红钻", "广岛三箭", "apisports_japan_j1_league_events.jsonl"),
            ("巴甲", "弗鲁米嫩", "帕梅拉斯", "fd_bra_events.jsonl"),
            ("法乙", "蒙彼利埃", "阿纳西", "fd_f2_events.jsonl"),
            ("欧冠", "本菲卡", "阿贾克斯", "uefa_champions_league_events.jsonl"),
            ("欧罗巴", "本菲卡", "流浪者", "uefa_europa_league_events.jsonl"),
            ("欧协联", "库奥皮奥", "阿尔克马", "europe_uefa_conference_league_events.jsonl"),
            ("阿甲", "River Plate", "Boca Juniors", "fd_arg_events.jsonl"),
            ("世界杯", "Argentina", "France", "world_cup_events.jsonl"),
            ("挪超", "布兰", "汉坎", "norway_eliteserien_events.jsonl"),
        ]
        for league, home, away, filename in cases:
            events = load_event_rows(std / filename)
            self.assertTrue(events, f"{filename} should load")
            match = route_matches(base_match(league, home, away, kickoff), [], events, min_history=5)
            self.assertEqual(match["mode"], "market_only", league)
            self.assertNotIn("lambda_prior", match, league)
            prior = (match.get("research_candidate") or {}).get("lambda_prior") or {}
            self.assertEqual(prior.get("source"), "apifootball_events_goals_only", league)
            self.assertGreaterEqual(prior.get("team_sample_sizes", {}).get("home", 0), 5, league)


if __name__ == "__main__":
    unittest.main()
