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


def test_collect_defaults_describe_real_snapshot_only_policy():
    import evidence_collect_defaults as ecd
    form = "\n".join(ecd.form_lines("西甲", "2026-08-16T12:00:00+08:00"))
    assert "正式比赛页面/API快照" in form
    assert "候选 URL 不是事实" in form
    assert "https://understat.com/getLeagueData/La_liga/2025" in form
    lineup = "\n".join(ecd.lineup_lines("2026-08-16T12:00:00+08:00", league="西甲"))
    assert "真实页面/API快照" in lineup
    assert "不是本场事实" in lineup
    assert "源1 sportsmole.co.uk" not in lineup


def test_unknown_league_does_not_invent_fotmob_id():
    got = lfs.sources_for("中超")
    assert got["known"] is False
    assert got["urls"][0] == "https://www.fotmob.com/api/data/allLeagues"
    assert "id=" not in got["urls"][0]
    assert got["urls"][-1] == "https://www.flashscore.com/"
