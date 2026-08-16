import pytest

import kleague_portal as kp


PLAYED = ('log([{"playerId":"20240277","name":"\\uae40\\uc885\\uc11d","backNo":29,'
          '"positionName":"GK","haGubunCd":"H","teamId":"K22","captainYn":"N",'
          '"workTime":90,"goalQty":1,"assistQty":0,"changeIQty":0,"changeOQty":0},'
          '{"playerId":"20240278","name":"Away Player","backNo":7,'
          '"positionName":"FW","haGubunCd":"A","teamId":"K03","captainYn":"Y",'
          '"workTime":0,"goalQty":0,"assistQty":0,"changeIQty":0,"changeOQty":0}]);')

ANNOUNCED = PLAYED.replace('"workTime":90', '"workTime":0').replace('"goalQty":1', '"goalQty":0')


def test_players_come_from_embedded_json_not_dom_attributes():
    players = kp.extract_players(PLAYED)

    assert len(players) == 2
    assert players[0]["name"] == "김종석"


def test_unrelated_script_arrays_are_ignored():
    html = 'init([{"foo":1}]); log([{"playerId":"1","name":"X","haGubunCd":"H"}]);'

    players = kp.extract_players(html)

    assert [p["playerId"] for p in players] == ["1"]


def test_missing_payload_yields_empty_list_not_an_exception():
    assert kp.extract_players("<html>no data</html>") == []
    assert kp.extract_players("") == []


def test_played_match_is_flagged_post_match():
    assert kp.looks_post_match(kp.extract_players(PLAYED)) is True


def test_all_zero_stats_is_not_flagged_post_match():
    """名单已公布但未开赛：各项赛后字段应全为 0。"""
    assert kp.looks_post_match(kp.extract_players(ANNOUNCED)) is False


def test_non_numeric_stat_does_not_crash_the_check():
    assert kp.looks_post_match([{"goalQty": "", "workTime": None}]) is False


def test_sides_split_by_home_away_flag():
    sides = kp.split_by_side(kp.extract_players(PLAYED))

    assert [p["name"] for p in sides["home"]] == ["김종석"]
    assert [p["name"] for p in sides["away"]] == ["Away Player"]
    assert sides["away"][0]["captain"] is True


FIXTURES = {"resultCode": "200", "resultMsg": "성공", "data": {"all": [
    {"gameId": 136, "leagueId": 1, "meetSeq": 1, "roundId": 23,
     "gameDate": "2026.08.16", "gameTime": "19:30", "endYn": "N",
     "homeTeam": "K18", "homeTeamName": "인천", "awayTeam": "K35",
     "awayTeamName": "김천", "homeGoal": 0, "awayGoal": 0, "fieldName": "인천"},
    {"gameId": 133, "leagueId": 1, "meetSeq": 1, "roundId": 22,
     "gameDate": "2026.08.15", "gameTime": "19:00", "endYn": "Y",
     "homeTeam": "K22", "homeTeamName": "광주", "awayTeam": "K03",
     "awayTeamName": "포항", "homeGoal": 2, "awayGoal": 1, "fieldName": "광주"},
]}}

STANDINGS = {"resultCode": "200", "data": {"league1": [
    {"rank": 1, "teamId": "K09", "teamName": "서울", "gainPoint": 47, "gameCount": 23,
     "winCnt": 14, "tieCnt": 5, "lossCnt": 4, "gainGoal": 39, "lossGoal": 19,
     "game01": "승", "game02": "무", "game03": "무", "game04": "패",
     "game05": "승", "game06": "승"},
]}}


def test_api_error_envelope_is_raised_not_silently_empty():
    with pytest.raises(RuntimeError, match="resultCode"):
        kp.parse_fixtures({"resultCode": "500", "resultMsg": "실패", "data": {}})


def test_fixtures_expose_gameid_and_team_codes_for_the_player_endpoint():
    rows = kp.parse_fixtures(FIXTURES)
    upcoming = next(r for r in rows if r["game_id"] == 136)

    assert (upcoming["home_team_code"], upcoming["away_team_code"]) == ("K18", "K35")
    assert upcoming["meet_seq"] == 1


def test_unfinished_match_is_pre_match_and_hides_the_placeholder_score():
    upcoming = next(r for r in kp.parse_fixtures(FIXTURES) if r["game_id"] == 136)

    assert upcoming["finished"] is False
    assert upcoming["pre_match_status"] == "PRE_MATCH_CANDIDATE"
    # 未开赛时接口给 0-0，不能当比分透出
    assert upcoming["home_goal"] is None and upcoming["away_goal"] is None


def test_finished_match_keeps_score_and_is_marked_unusable_pre_match():
    played = next(r for r in kp.parse_fixtures(FIXTURES) if r["game_id"] == 133)

    assert (played["home_goal"], played["away_goal"]) == (2, 1)
    assert played["pre_match_status"] == "POST_MATCH_NOT_USABLE"


def test_kickoff_stays_naive_unless_an_offset_is_explicitly_supplied():
    """接口不声明时区，模块不替调用方猜。"""
    row = kp.parse_fixtures(FIXTURES)[0]

    assert row["kickoff_naive"].startswith("2026-08-15T19:00")
    assert row["kickoff_iso"] is None
    assert row["assumed_offset"] is None


def test_supplied_offset_produces_a_tz_aware_kickoff():
    row = kp.parse_fixtures(FIXTURES, assume_offset="+09:00")[0]

    assert row["kickoff_iso"] == "2026-08-15T19:00:00+09:00"
    assert row["assumed_offset"] == "+09:00"


def test_standings_translate_korean_form_codes():
    table = kp.parse_standings(STANDINGS)["league1"]

    assert table[0]["team_code"] == "K09"
    assert table[0]["points"] == 47
    assert table[0]["recent_form"] == ["W", "D", "D", "L", "W", "W"]


def test_standings_tolerate_a_missing_league_tier():
    assert kp.parse_standings(STANDINGS)["league2"] == []


def test_players_without_back_number_sort_last():
    sides = kp.split_by_side([
        {"haGubunCd": "H", "name": "no-number", "backNo": None},
        {"haGubunCd": "H", "name": "seven", "backNo": 7},
    ])

    assert [p["name"] for p in sides["home"]] == ["seven", "no-number"]
