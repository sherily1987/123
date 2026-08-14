from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE = Path(__file__).with_name("football_data_couk_adapter.py")
SPEC = importlib.util.spec_from_file_location("fd", MODULE)
fd = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(fd)


def test_team_slug_merges_real_world_spelling_variants():
    """实测源里存在这两组异写，必须归一化为同一支球队。"""
    assert fd.team_slug("Colon Santa FE") == fd.team_slug("Colon Santa Fe")
    assert fd.team_slug("Ham-Kam") == fd.team_slug("HamKam")
    assert fd.team_slug("Palmeiras") != fd.team_slug("Portuguesa")


def test_stable_match_id_is_deterministic_and_distinct():
    """本源无比赛 id，合成的必须重跑一致，且不同比赛不相撞。"""
    a = fd.stable_match_id("BRA", "2012-05-19", "Palmeiras", "Portuguesa")
    assert a == fd.stable_match_id("BRA", "2012-05-19", "Palmeiras", "Portuguesa")
    assert a == fd.stable_match_id("BRA", "2012-05-19", "palmeiras", "PORTUGUESA")  # 队名异写不改 id
    assert a != fd.stable_match_id("BRA", "2012-05-20", "Palmeiras", "Portuguesa")
    assert a != fd.stable_match_id("ARG", "2012-05-19", "Palmeiras", "Portuguesa")
    assert a != fd.stable_match_id("BRA", "2012-05-19", "Portuguesa", "Palmeiras")  # 主客不可互换


@pytest.mark.parametrize("value,expected", [
    ("19/05/2012", "2012-05-19"), ("06/08/21", "2021-08-06"),
    ("2024-03-02", "2024-03-02"), ("", None), ("garbage", None),
])
def test_parse_date_handles_source_formats(value, expected):
    assert fd.parse_date(value) == expected


def test_devig_normalizes_and_rejects_bad_odds():
    # 引擎有概率守恒强制审计。逐项独立舍入会留下 ~1e-6 的残差，必须并入某一项；
    # 但三个六位小数的**二进制**浮点相加不可能恒等于 1.0，故判据用 1e-12 而非精确相等。
    for odds in ([2.0, 4.0, 4.0], [2.35, 3.4, 3.1], [1.75, 3.86, 5.25], [1.01, 50.0, 60.0]):
        probs = fd.devig(odds)
        assert abs(sum(probs) - 1.0) < 1e-12
        assert round(sum(probs), 6) == 1.0        # 十进制层面精确守恒
    probs = fd.devig([2.0, 4.0, 4.0])
    assert probs[0] == pytest.approx(0.5)
    assert fd.devig([2.0, 4.0]) is None          # 缺一项
    assert fd.devig([1.0, 4.0, 4.0]) is None     # 赔率必须 >1
    assert fd.devig([2.0, None, 4.0]) is None


def test_pick_closing_follows_bookmaker_priority():
    """Pinnacle 收盘优先于市场均值收盘。"""
    row = {"PSCH": "2.0", "PSCD": "4.0", "PSCA": "4.0",
           "AvgCH": "1.5", "AvgCD": "5.0", "AvgCA": "6.0"}
    probs, source = fd.pick_closing(row, fd.NEW_ODDS_PRIORITY)
    assert source == "PSC" and probs[0] == pytest.approx(0.5)
    # Pinnacle 不完整时退到下一档
    probs2, source2 = fd.pick_closing({**row, "PSCH": ""}, fd.NEW_ODDS_PRIORITY)
    assert source2 == "AvgC"


NEW_ROW = {"Country": "Brazil", "League": "Serie A", "Season": "2012", "Date": "19/05/2012",
           "Time": "22:30", "Home": "Palmeiras", "Away": "Portuguesa", "HG": "1", "AG": "1",
           "Res": "D", "PSCH": "1.75", "PSCD": "3.86", "PSCA": "5.25"}


def test_normalize_new_marks_closing_basis_and_name_derived_ids():
    row = fd.normalize_new(NEW_ROW, "BRA", "2026-08-12T00:00:00+00:00")
    assert row["actual"] == [1, 1]
    assert row["home_id"] == "fd:BRA:palmeiras"
    assert row["team_id_basis"] == "name_derived"      # 不是供应商主键
    assert row["closing_market_meta"]["basis"] == "closing_line"
    assert abs(sum(row["closing_market_1x2"]) - 1.0) < 1e-12
    # 收盘口径不得写进 provider_market 字段，否则会与赛前快照口径混用
    assert "provider_market_1x2" not in row


def test_normalize_new_skips_unplayed_rows():
    assert fd.normalize_new({**NEW_ROW, "HG": "", "AG": ""}, "BRA", "t") is None


MMZ_ROW = {"Div": "E1", "Date": "06/08/2021", "Time": "19:45", "HomeTeam": "Bournemouth",
           "AwayTeam": "West Brom", "FTHG": "2", "FTAG": "1", "HS": "7", "AS": "15",
           "HST": "4", "AST": "5", "HC": "4", "AC": "8",
           "PSCH": "2.0", "PSCD": "4.0", "PSCA": "4.0"}


def test_normalize_mmz_stats_flags_missing_box_split():
    """英冠只有总射门与射正，没有禁区内外切分——xG 口径与五大联赛不同。"""
    stat = fd.normalize_mmz_stats(MMZ_ROW, "E1", "t")
    assert stat["shots_on_target"] == [4.0, 5.0]
    assert stat["split_available"] is False
    assert stat["xg_basis"] == "shots_on_target"
    assert stat["xg_usable"] is True
    assert stat["data_class"] == "POST_MATCH"


def test_normalize_mmz_and_stats_share_one_match_id():
    """赛果与统计必须能按 match_id 关联上。"""
    ev = fd.normalize_mmz(MMZ_ROW, "E1", "2122", "t")
    st = fd.normalize_mmz_stats(MMZ_ROW, "E1", "t")
    assert ev["match_id"] == st["match_id"]
    assert ev["season"] == "2122"


def test_download_league_writes_prematch_safe_events(tmp_path, monkeypatch):
    monkeypatch.setattr(fd, "fetch_csv", lambda url, *a, **k: [NEW_ROW])
    report = fd.download_league("BRA", tmp_path)
    rows = [json.loads(l) for l in (tmp_path / "fd_bra_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert report["closing_coverage_pct"] == 100.0
    # 赛前训练集不得含射门等赛后统计
    assert not ({"shots_total", "shots_on_target", "statistics"} & set(rows[0]))


def test_download_league_rejects_unknown_code(tmp_path):
    with pytest.raises(SystemExit):
        fd.download_league("ZZZ", tmp_path)
