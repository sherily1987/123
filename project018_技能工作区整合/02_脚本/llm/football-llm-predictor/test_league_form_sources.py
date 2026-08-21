import league_form_sources as lfs


def test_big_five_uses_understat_not_fotmob_id_guess():
    got = lfs.sources_for("英超", season_start=2026)
    assert got["known"] is True
    assert got["urls"][0] == "https://understat.com/getLeagueData/EPL/2026"
    assert "https://understat.com/getLeagueData/EPL/2025" in got["urls"]
    assert "fbref.com" in got["blocked"]
    assert all("whoscored" not in u for u in got["urls"])


def test_korea_uses_official_kleague_json():
    got = lfs.sources_for("韩职")
    assert "https://www.kleague.com/api/clubRank.do" in got["urls"]
    assert "https://www.kleague.com/api/recentMatchResult.do" in got["urls"]
    assert "id=9080" in " ".join(got["urls"])


def test_jleague_uses_official_site_and_fotmob():
    got = lfs.sources_for("日职")
    assert "https://www.jleague.jp/en/match/" in got["urls"]
    assert "id=223" in " ".join(got["urls"])


def test_collect_defaults_include_previous_season_and_two_source_xi():
    import evidence_collect_defaults as ecd
    form = "\n".join(ecd.form_lines("西甲", "2026-08-16T12:00:00+08:00"))
    assert "对其他对手" in form
    assert "不得当「无近5场」" in form
    assert "https://understat.com/getLeagueData/La_liga/2025" in form
    lineup = "\n".join(ecd.lineup_lines("2026-08-16T12:00:00+08:00", league="西甲"))
    assert "两个独立媒体" in lineup
    assert "20个独立主机投票" in lineup
    assert "得票最高的缺阵名单直接当可用伤停" in lineup
    assert "不得因官方未出整维弃权" in lineup
    assert "源1 sportsmole.co.uk" in lineup
    assert lineup.count("- 源") == 20


def test_unknown_league_does_not_invent_fotmob_id():
    got = lfs.sources_for("中超")
    assert got["known"] is False
    assert got["urls"][0] == "https://www.fotmob.com/api/data/allLeagues"
    assert "id=" not in got["urls"][0]
    assert got["urls"][-1] == "https://www.flashscore.com/"
