import pytest

import understat_xg as ux


def _match(date, xg, xga, xpts=1.0, scored=1, missed=1):
    return {"date": date, "xG": xg, "xGA": xga, "xpts": xpts,
            "npxG": xg, "npxGA": xga, "scored": scored, "missed": missed}


HISTORY = [
    _match("2026-08-01 18:00:00", 1.5, 0.5, 2.1, scored=2, missed=0),
    _match("2026-08-08 18:00:00", 1.0, 1.0, 1.2, scored=1, missed=1),
    _match("2026-08-15 18:00:00", 2.0, 0.4, 2.4, scored=1, missed=0),
]


def test_league_name_accepts_chinese_and_understat_codes():
    assert ux.resolve_league("西甲") == "La_liga"
    assert ux.resolve_league("EPL") == "EPL"


def test_unknown_league_is_rejected_rather_than_guessed():
    with pytest.raises(ValueError):
        ux.resolve_league("韩职")


def test_cutoff_without_timezone_offset_is_refused():
    """数据契约：无 offset 不猜测。"""
    with pytest.raises(ValueError, match="offset"):
        ux.is_definitely_before("2026-08-01 18:00:00", "2026-08-17T00:00:00")


def test_match_well_before_cutoff_counts():
    assert ux.is_definitely_before("2026-08-01 18:00:00", "2026-08-17T00:00:00+08:00")


def test_match_after_cutoff_is_excluded():
    assert not ux.is_definitely_before("2026-08-20 18:00:00", "2026-08-17T00:00:00+08:00")


def test_naive_date_inside_timezone_uncertainty_is_dropped_conservatively():
    """裸时间落在 cutoff 前 14h 内——某些时区解释下已是赛后，宁可丢弃。"""
    assert not ux.is_definitely_before("2026-08-16 20:00:00", "2026-08-17T00:00:00+08:00")


def test_summary_aggregates_and_reports_finishing_delta():
    summary = ux.team_xg_summary(HISTORY)

    assert summary["matches"] == 3
    assert summary["xG"] == 4.5
    assert summary["xGA"] == 1.9
    assert summary["xPTS"] == 5.7
    assert summary["scored"] == 4
    assert summary["finishing_delta"] == -0.5  # 进4球 vs xG 4.5，略欠收


def test_cutoff_filters_history_and_reports_how_many_were_dropped():
    summary = ux.team_xg_summary(HISTORY, cutoff_iso="2026-08-10T00:00:00+08:00")

    assert summary["matches"] == 2
    assert summary["excluded_by_cutoff"] == 1
    assert summary["xG"] == 2.5


def test_last_n_takes_the_most_recent_after_cutoff_filtering():
    summary = ux.team_xg_summary(HISTORY, last_n=1)

    assert summary["matches"] == 1
    assert summary["xG"] == 2.0  # 08-15 那场


def test_empty_history_reports_none_rather_than_dividing_by_zero():
    summary = ux.team_xg_summary([])

    assert summary["matches"] == 0
    assert summary["xG_per_match"] is None
    assert summary["finishing_delta"] is None


def test_summarise_league_filters_by_team_name():
    payload = {"teams": {
        "1": {"id": "1", "title": "Barcelona", "history": HISTORY},
        "2": {"id": "2", "title": "Getafe", "history": HISTORY[:1]},
    }}

    rows = ux.summarise_league(payload, teams_filter=["Getafe"])

    assert [r["team"] for r in rows] == ["Getafe"]
    assert rows[0]["matches"] == 1
