from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import store_view as sv

CST = timezone(timedelta(hours=8))


def test_light_evidence_defaults_two_source_xi_and_opener_form():
    import light_evidence as le
    text = le.build_one(1, {
        "match_num": "周日022", "home": "西班牙人", "away": "莱万特",
        "league": "西甲", "kickoff_iso": "2026-08-17T01:00:00+08:00",
        "match_id": 2040907, "model_odds": [1.85, 3.18, 3.65],
    }, "C")
    assert "两个独立媒体" in text
    assert "20个独立主机投票" in text
    assert "得票最高的缺阵名单直接当可用伤停" in text
    assert "对其他对手" in text
    assert "getLeagueData/La_liga/2025" in text
    assert "以赛前官方名单为准" not in text
    assert "未抓取双方近 5 场" not in text


def test_classify_evidence_two_source_and_previous_form():
    text = """## 1. 伤停/阵容
- 两家独立媒体一致即视为该位置可用首发 | source(https://www.sportsmole.co.uk/a) | collected_at(2026-08-16T12:00:00+08:00)
- 左后卫仍是 2 对 2 | source(https://www.estadiodeportivo.com/b) | collected_at(2026-08-16T12:00:00+08:00)
## 3. 近况/状态
- 揭幕战取各队对其他对手的上季正式近5场 | source(https://understat.com/getLeagueData/La_liga/2025) | collected_at(2026-08-16T12:00:00+08:00)
"""
    got = sv.classify_evidence(text)
    assert got["form"] == "previous"
    assert got["lineup"] == "conflict"
    assert got["injury"] == "none"
    assert "没有可引用的伤停" in got["injury_reason"]
    assert got["form_zh"] == "上季正式"
    assert "部分位置" in got["lineup_reason"]


def test_classify_evidence_missing_form_and_no_lineup():
    text = """## 1. 伤停/阵容
- 体彩官方接口无伤病/大名单字段 | source(http://webapi.sporttery.cn/x) | collected_at(t)
## 3. 近况/状态
- 完整近5场比分未核验 | source(https://example.test/a) | collected_at(t)
"""
    got = sv.classify_evidence(text)
    assert got["form"] == "missing"
    assert got["lineup"] == "not_collected"
    assert "没有首发采集" in got["lineup_reason"]
    assert got["injury"] == "none"
    assert "无伤停字段" in got["injury_reason"]


def test_classify_voted_xi_and_form_beats_official_gap():
    text = """## 1. 伤停/阵容
- 二十源整合预测首发（加的夫 4-2-3-1，非官方）：Trott；Kpakio, Ng, Osho, Bagan | source(https://www.flashscore.com/a) | collected_at(t)
- 两个独立媒体对上述位置一致，视为可用首发 | source(https://www.sportsmole.co.uk/b) | collected_at(t)
> 说明：投票结果就是可用首发，不再等官方名单。
## 3. 近况/状态
- 二十源整合投票近5场，得票最高：杯赛3-2斯温登 | source(https://www.bbc.co.uk/a) | collected_at(t)
- 对其他对手的上季正式赛计入 | source(https://www.flashscore.com/b) | collected_at(t)
"""
    got = sv.classify_evidence(text)
    assert got["lineup"] == "two_source"
    assert "不再等官方" in got["lineup_reason"]
    assert got["form"] == "previous"
    assert "20 源投票" in got["form_reason"]


def test_classify_voted_injury_is_usable():
    text = """## 1. 伤停/阵容
- 二十源整合伤停：Windass 缺席 | source(https://www.bbc.co.uk/a) | collected_at(t)
- 二十源整合预测首发 4-2-3-1 Trott | source(https://www.flashscore.com/a) | collected_at(t)
## 3. 近况/状态
- 二十源整合投票近5场 | source(https://www.bbc.co.uk/b) | collected_at(t)
"""
    got = sv.classify_evidence(text)
    assert got["injury"] == "dual"
    assert "不再等官方" in got["injury_reason"]


def test_classify_evidence_injury_only_is_not_search_failed():
    raw = """## 1. 伤停/阵容
- FotMob：腓特烈不可用 Sigurd Kvile | source(https://www.fotmob.com/m) | collected_at(t)
- SportsGambler 伤停表另列 Joachim Nysveen | source(https://www.sportsgambler.com/x) | collected_at(t)
> 证据缺口：官方首发未公布。
## 3. 近况/状态
- 近5场完整比分未从官方联赛页逐场核验 | source(https://example.test/a) | collected_at(t)
"""
    got = sv.classify_evidence(raw)
    assert got["lineup"] == "not_written"
    assert "不是检索结论" in got["lineup_reason"]
    assert got["injury"] == "dual"
    assert "fotmob.com" in got["injury_reason"]


def test_status_zh_unavailable_is_chinese():
    assert sv.status_zh("UNAVAILABLE") == "暂无数据"
    assert sv.status_zh("VALID") == "有效"
    assert sv.status_zh("MARKET_BASELINE") == "市场基线"


def test_extract_quant_reads_registry_output_block():
    got = sv.extract_quant({
        "mode": "market_only",
        "output": {
            "final_1x2_pct": [80.6, 12.2, 7.3],
            "top_scores": [{"score": "2-0"}, {"score": "3-0"}, {"score": "2-1"}],
            "recommendation_gate": {"status": "MARKET_BASELINE"},
        },
    })
    assert got["final_1x2_pct"] == [80.6, 12.2, 7.3]
    assert got["top_scores"] == ["2-0", "3-0", "2-1"]
    assert got["gate"] == "MARKET_BASELINE"


def test_sporttery_id_and_classify():
    assert sv.sporttery_id(2040915) == "sporttery-2040915"
    assert sv.sporttery_id("sporttery-2040915") == "sporttery-2040915"
    assert sv.classify(True, True, False, False) == "missing_pred"
    assert sv.classify(True, True, True, False) == "predicted"
    assert sv.classify(False, True, False, False) == "no_odds"


def test_remap_legacy_suite_path(tmp_path: Path):
    raw = "C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/football-quant-fusion/backtest/predictions/x.json"
    got = sv.remap_pred_path(raw, tmp_path)
    assert got == tmp_path / "backtest" / "predictions" / "x.json"


def test_board_counts_paused_sales_in_on_sale_window(tmp_path: Path):
    now = datetime(2026, 8, 16, 23, 40, tzinfo=CST)
    live = [
        {"matchId": 2040907, "matchNumStr": "周日022", "leagueAbbName": "西甲",
         "homeTeamAbbName": "西班牙人", "awayTeamAbbName": "莱万特",
         "matchDate": "2026-08-17", "matchTime": "01:00", "matchStatusName": "暂停销售",
         "h": "1.85", "d": "3.18", "a": "3.65"},
        {"matchId": 2040998, "matchNumStr": "周二001", "leagueAbbName": "巴甲",
         "homeTeamAbbName": "甲", "awayTeamAbbName": "乙",
         "matchDate": "2026-08-19", "matchTime": "06:00", "matchStatusName": "待开售"},
        {"matchId": 2040895, "matchNumStr": "周日008", "leagueAbbName": "荷甲",
         "homeTeamAbbName": "特温特", "awayTeamAbbName": "兹沃勒",
         "matchDate": "2026-08-16", "matchTime": "20:30", "matchStatusName": "待开奖"},
    ]
    board = sv.board(now=now, live_rows=live, root=tmp_path)
    assert board["summary"]["listed"] == 3
    assert board["summary"]["on_sale"] == 1
    assert board["summary"]["has_odds"] == 1
    assert board["matches"][0]["status_name"] == "暂停销售" or any(
        m["status_name"] == "暂停销售" for m in board["matches"])
    assert all(g["league"] != "巴甲" for g in board["by_league"])
    assert board["by_league"][0]["league"] == "西甲"


def test_board_join_marks_missing_and_keeps_llm_off_quant(tmp_path: Path):
    mid = 2040999
    pred_dir = tmp_path / "backtest" / "predictions"
    pred_dir.mkdir(parents=True)
    payload = {
        "mode": "market_only",
        "prediction_as_of": "2026-08-16T00:00:00+00:00",
        "forecast": {"final_1x2_pct": [40.0, 30.0, 30.0], "top_scores": [{"score": "1-1"}]},
        "recommendation_gate": {"status": "MARKET_BASELINE"},
        "build_identity": {"engine_bundle_sha256": "a" * 64},
    }
    p = pred_dir / "sporttery-2040915.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "backtest").mkdir(exist_ok=True)
    (tmp_path / "backtest" / "registry.jsonl").write_text(json.dumps({
        "match_id": "sporttery-2040915",
        "created_at": "2026-08-16T00:00:00+00:00",
        "path": str(p),
        "prediction_id": "demo",
    }) + "\n", encoding="utf-8")
    job_dir = tmp_path / "jobs" / "2026-08-18"
    job_dir.mkdir(parents=True)
    (job_dir / "sporttery-2040915.json").write_text(json.dumps({
        "identity": {"match_id": "sporttery-2040915"},
        "outputs": [{"track": "llm", "direction": "主胜", "strength": {"type": "vote_share", "value": 0.67}, "action": "skip"}],
    }), encoding="utf-8")
    now = datetime(2026, 8, 16, 16, 0, tzinfo=CST)
    live = [
        {"matchId": 2040915, "matchNumStr": "周一002", "leagueAbbName": "瑞超",
         "homeTeamAbbName": "赫根", "awayTeamAbbName": "哈尔姆斯",
         "matchDate": "2026-08-18", "matchTime": "01:00", "matchStatusName": "已开售",
         "h": "1.21", "d": "5.6", "a": "8.05"},
        {"matchId": mid, "matchNumStr": "周一099", "leagueAbbName": "英冠",
         "homeTeamAbbName": "甲", "awayTeamAbbName": "乙",
         "matchDate": "2026-08-18", "matchTime": "03:00", "matchStatusName": "已开售",
         "h": "2.2", "d": "3.3", "a": "3.1"},
    ]
    board = sv.board(now=now, live_rows=live, root=tmp_path)
    assert board["summary"]["missing_pred"] == 1
    assert board["summary"]["predicted"] == 1
    by_id = {r["match_id"]: r for r in board["matches"]}
    q = by_id["sporttery-2040915"]["quant"]
    assert q["mode"] == "market_only"
    assert q["final_1x2_pct"][0] == 40.0
    assert "vote_share" not in q
    llm = by_id["sporttery-2040915"]["llm"]
    assert llm["note"] == "证据方向，不是概率"
    assert llm["direction"] == "主胜"
    assert by_id["sporttery-2040999"]["bucket"] == "missing_pred"
    names = [g["league"] for g in board["by_league"]]
    assert names.index("瑞超") < names.index("英冠")
    assert board["by_league"][0]["n"] == 1


def test_board_reads_llm_pred_file_scores(tmp_path: Path):
    pred_dir = tmp_path / "llm_preds"
    pred_dir.mkdir()
    (pred_dir / "predictions_2040922.json").write_text(json.dumps({
        "match_id": "sporttery-2040922",
        "direction": "主胜",
        "alt_direction": "平局",
        "probs_1x2": [45.5, 28.1, 26.4],
        "top_scores": ["1-0", "2-1", "1-1"],
    }), encoding="utf-8")
    now = datetime(2026, 8, 17, 2, 0, tzinfo=CST)
    live = [
        {"matchId": 2040922, "matchNumStr": "周一004", "leagueAbbName": "西甲",
         "homeTeamAbbName": "拉科", "awayTeamAbbName": "埃尔切",
         "matchDate": "2026-08-18", "matchTime": "03:00", "matchStatusName": "已开售",
         "h": "2.16", "d": "2.95", "a": "3.05"},
    ]
    board = sv.board(now=now, live_rows=live, root=tmp_path)
    llm = board["matches"][0]["llm"]
    assert llm["direction"] == "主胜"
    assert llm["alt_direction"] == "平局"
    assert llm["top_scores"] == ["1-0", "2-1", "1-1"]
    assert llm["probs_1x2"][0] == 45.5
    assert board["summary"]["llm_predicted"] == 1


def test_fetch_live_selling_timeout_uses_cache(monkeypatch):
    sv._LIVE_CACHE["rows"] = [{"matchId": 1}]
    sv._LIVE_CACHE["at"] = None

    def slow(now=None):
        import time
        time.sleep(1)
        return [{"matchId": 2}]

    monkeypatch.setattr(sv, "_fetch_live_selling_impl", slow)
    got = sv.fetch_live_selling(timeout_s=0.05)
    assert got == [{"matchId": 1}]


def test_fetch_live_selling_success_updates_cache(monkeypatch):
    sv._LIVE_CACHE["rows"] = []

    monkeypatch.setattr(sv, "_fetch_live_selling_impl", lambda now=None: [{"matchId": 3}])
    got = sv.fetch_live_selling(timeout_s=2)
    assert got == [{"matchId": 3}]
    assert sv._LIVE_CACHE["rows"] == [{"matchId": 3}]


def test_parse_evidence_match_id_from_url_and_sporttery():
    assert sv.parse_evidence_match_id(
        "source(http://webapi.sporttery.cn/x?matchId=2040915)"
    ) == "sporttery-2040915"
    assert sv.parse_evidence_match_id("体彩 sporttery-2040914 周一001") == "sporttery-2040914"
    assert sv.parse_evidence_match_id("竞彩编号：周日007（体彩 matchId 2040894）") == "sporttery-2040894"
    assert sv.parse_evidence_match_id("没有编号") is None


def test_board_marks_llm_collected_from_evidence_file(tmp_path: Path):
    ev_dir = tmp_path / "evidence_rerun33"
    ev_dir.mkdir()
    (ev_dir / "evidence_030_赫根_哈尔姆斯.md").write_text(
        "赛事：瑞超\n体彩 sporttery-2040915 周一002 赫根 vs 哈尔姆斯\n",
        encoding="utf-8",
    )
    now = datetime(2026, 8, 16, 16, 0, tzinfo=CST)
    live = [
        {"matchId": 2040915, "matchNumStr": "周一002", "leagueAbbName": "瑞超",
         "homeTeamAbbName": "赫根", "awayTeamAbbName": "哈尔姆斯",
         "matchDate": "2026-08-18", "matchTime": "01:00", "matchStatusName": "已开售",
         "h": "1.21", "d": "5.6", "a": "8.05"},
        {"matchId": 2040999, "matchNumStr": "周一099", "leagueAbbName": "英冠",
         "homeTeamAbbName": "甲", "awayTeamAbbName": "乙",
         "matchDate": "2026-08-18", "matchTime": "03:00", "matchStatusName": "已开售",
         "h": "2.2", "d": "3.3", "a": "3.1"},
    ]
    board = sv.board(now=now, live_rows=live, root=tmp_path)
    by_id = {r["match_id"]: r for r in board["matches"]}
    llm = by_id["sporttery-2040915"]["llm"]
    assert llm["note"] == "已采集"
    assert llm["direction"] is None
    assert llm["source"] == "file"
    assert by_id["sporttery-2040999"]["llm"] is None
    assert board["summary"]["llm_collected"] == 1


def test_load_results_reads_numeric_filename(tmp_path: Path):
    folder = tmp_path / "backtest" / "results"
    folder.mkdir(parents=True)
    (folder / "2040821.json").write_text(json.dumps({
        "match_id": "2040821",
        "status": "finished",
        "score_90": {"home": 2, "away": 1},
        "settlement_scope": "90min",
    }), encoding="utf-8")
    got = sv.load_results(tmp_path)
    assert got["sporttery-2040821"]["score_90"] == [2, 1]
    assert got["sporttery-2040821"]["direction"] == "主胜"


def test_history_groups_by_kickoff_and_scores_hit(tmp_path: Path):
    pred_dir = tmp_path / "backtest" / "predictions"
    pred_dir.mkdir(parents=True)
    payload = {
        "mode": "market_only",
        "snapshot_type": "prematch",
        "match": {
            "competition": "瑞超",
            "kickoff": "2026-08-15T20:00:00+08:00",
            "home": "甲",
            "away": "乙",
            "sporttery_meta": {"match_id": 2040800, "match_num": "周五001"},
        },
        "output": {"final_1x2_pct": [55.0, 25.0, 20.0], "top_scores": [{"score": "1-0"}]},
    }
    p = pred_dir / "sporttery-2040800.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "backtest" / "registry.jsonl").write_text(json.dumps({
        "match_id": "sporttery-2040800",
        "created_at": "2026-08-15T00:00:00+00:00",
        "path": str(p),
        "prediction_id": "demo-hist",
    }) + "\n", encoding="utf-8")
    res_dir = tmp_path / "backtest" / "results"
    res_dir.mkdir(parents=True)
    (res_dir / "2040800.json").write_text(json.dumps({
        "match_id": "2040800",
        "status": "finished",
        "score_90": {"home": 2, "away": 0},
        "settlement_scope": "90min",
    }), encoding="utf-8")
    idx = sv.history_index(tmp_path)
    assert idx["total"] == 1
    assert idx["days"][0]["day"] == "2026-08-15"
    assert idx["days"][0]["settled"] == 1
    assert idx["days"][0]["hit"] == 1
    assert idx["days"][0]["hit_rate"] == 100.0
    assert idx["days"][0]["hit_rate_text"] == "1/1"
    assert idx["hit_rate"] == 100.0
    assert idx["days"][0]["leagues"][0]["league"] == "瑞超"
    day = sv.history_day("2026-08-15", tmp_path)
    assert day["matches"][0]["quant"]["direction"] == "主胜"
    assert day["matches"][0]["hit"] is True
    assert day["matches"][0]["result"]["score_90"] == [2, 0]
    assert day["summary"]["hit_rate"] == 100.0
    assert day["by_league"][0]["league"] == "瑞超"
    assert day["by_league"][0]["hit_rate"] == 100.0


def test_board_reads_forward_llm_evidence(tmp_path: Path):
    ev = tmp_path / "forward" / "2026-08-18" / "llm_evidence"
    ev.mkdir(parents=True)
    (ev / "evidence_001_赫根_哈尔姆斯.md").write_text(
        "赛事：瑞超\n体彩 sporttery-2040915 周一002 赫根 vs 哈尔姆斯\n",
        encoding="utf-8",
    )
    now = datetime(2026, 8, 16, 16, 0, tzinfo=CST)
    live = [
        {"matchId": 2040915, "matchNumStr": "周一002", "leagueAbbName": "瑞超",
         "homeTeamAbbName": "赫根", "awayTeamAbbName": "哈尔姆斯",
         "matchDate": "2026-08-18", "matchTime": "01:00", "matchStatusName": "已开售",
         "h": "1.21", "d": "5.6", "a": "8.05"},
    ]
    board = sv.board(now=now, live_rows=live, root=tmp_path)
    llm = board["matches"][0]["llm"]
    assert llm["note"] == "已采集"
    assert llm["source"] == "file"
    assert board["summary"]["llm_collected"] == 1


def test_history_skips_registry_without_prediction(tmp_path: Path):
    pred_dir = tmp_path / "backtest" / "predictions"
    pred_dir.mkdir(parents=True)
    empty = pred_dir / "sporttery-2040801.json"
    empty.write_text(json.dumps({
        "mode": "market_only",
        "match": {
            "competition": "瑞超",
            "kickoff": "2026-08-15T21:00:00+08:00",
            "home": "丙",
            "away": "丁",
            "sporttery_meta": {"match_id": 2040801, "match_num": "周五002"},
        },
        "output": {},
    }), encoding="utf-8")
    (tmp_path / "backtest" / "registry.jsonl").write_text(
        json.dumps({
            "match_id": "sporttery-2040801",
            "created_at": "2026-08-15T00:00:00+00:00",
            "path": str(empty),
            "prediction_id": "empty",
        }) + "\n",
        encoding="utf-8",
    )
    idx = sv.history_index(tmp_path)
    assert idx["total"] == 0
    assert idx["days"] == []
    assert idx["hit_rate"] is None


def _write_hist_match(root: Path, mid: int, league: str, kickoff: str, pct, score, match_num: str):
    pred_dir = root / "backtest" / "predictions"
    pred_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "market_only",
        "snapshot_type": "prematch",
        "match": {
            "competition": league,
            "kickoff": kickoff,
            "home": "甲",
            "away": "乙",
            "sporttery_meta": {"match_id": mid, "match_num": match_num},
        },
        "output": {"final_1x2_pct": pct, "top_scores": [{"score": "1-0"}]},
    }
    p = pred_dir / f"sporttery-{mid}.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    res_dir = root / "backtest" / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    if score is not None:
        (res_dir / f"{mid}.json").write_text(json.dumps({
            "match_id": str(mid),
            "status": "finished",
            "score_90": {"home": score[0], "away": score[1]},
            "settlement_scope": "90min",
        }), encoding="utf-8")
    return {
        "match_id": f"sporttery-{mid}",
        "created_at": "2026-08-15T00:00:00+00:00",
        "path": str(p),
        "prediction_id": f"demo-{mid}",
    }


def test_history_splits_by_date_and_league_with_hit_rate(tmp_path: Path):
    recs = [
        _write_hist_match(tmp_path, 2040801, "西甲", "2026-08-16T01:00:00+08:00",
                          [60.0, 22.0, 18.0], [2, 0], "周日001"),
        _write_hist_match(tmp_path, 2040802, "西甲", "2026-08-16T03:00:00+08:00",
                          [20.0, 25.0, 55.0], [1, 0], "周日002"),
        _write_hist_match(tmp_path, 2040803, "英超", "2026-08-16T04:00:00+08:00",
                          [50.0, 30.0, 20.0], [1, 1], "周日003"),
        _write_hist_match(tmp_path, 2040804, "西甲", "2026-08-17T01:00:00+08:00",
                          [70.0, 18.0, 12.0], None, "周一001"),
    ]
    (tmp_path / "backtest" / "registry.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8",
    )
    full = sv.history_full(tmp_path)
    days = {d["day"]: d for d in full["days"]}
    assert days["2026-08-16"]["n"] == 3
    assert days["2026-08-16"]["hit"] == 1
    assert days["2026-08-16"]["miss"] == 2
    assert days["2026-08-16"]["hit_rate"] == 33.3
    assert days["2026-08-17"]["settled"] == 0
    assert days["2026-08-17"]["hit_rate"] is None
    assert full["hit"] == 1
    assert full["settled"] == 3
    assert full["hit_rate"] == 33.3
    sec16 = next(s for s in full["sections"] if s["day"] == "2026-08-16")
    leagues = {g["league"]: g for g in sec16["by_league"]}
    assert set(leagues) == {"西甲", "英超"}
    assert leagues["西甲"]["n"] == 2
    assert leagues["西甲"]["hit"] == 1
    assert leagues["西甲"]["hit_rate"] == 50.0
    assert leagues["英超"]["hit"] == 0
    assert leagues["英超"]["hit_rate"] == 0.0
    day = sv.history_day("2026-08-16", tmp_path)
    assert [g["league"] for g in day["by_league"]] == ["西甲", "英超"]
    assert day["summary"]["llm_n"] == 0
    assert day["summary"]["llm_hit_rate"] is None


def test_parse_llm_pick_splits_double_and_single():
    assert sv.parse_llm_pick("主胜/平局") == {"direction": "主胜", "alt_direction": "平局"}
    assert sv.parse_llm_pick("双选 主胜/平局（H/D）")["direction"] == "主胜"
    assert sv.parse_llm_pick("客胜") == {"direction": "客胜", "alt_direction": None}


def test_history_llm_hit_is_separate_from_quant(tmp_path: Path):
    recs = [
        _write_hist_match(tmp_path, 2040801, "西甲", "2026-08-16T01:00:00+08:00",
                          [60.0, 22.0, 18.0], [2, 0], "周日001"),
        _write_hist_match(tmp_path, 2040802, "西甲", "2026-08-16T03:00:00+08:00",
                          [55.0, 25.0, 20.0], [2, 0], "周日002"),
    ]
    (tmp_path / "backtest" / "registry.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8",
    )
    job_dir = tmp_path / "jobs" / "2026-08-16"
    job_dir.mkdir(parents=True)
    (job_dir / "sporttery-2040801.json").write_text(json.dumps({
        "identity": {"match_id": "sporttery-2040801"},
        "outputs": [{"track": "llm", "direction": "主胜", "action": "research_opinion"}],
    }), encoding="utf-8")
    (job_dir / "sporttery-2040802.json").write_text(json.dumps({
        "identity": {"match_id": "sporttery-2040802"},
        "outputs": [{"track": "llm", "direction": "平局", "action": "research_opinion"}],
    }), encoding="utf-8")
    day = sv.history_day("2026-08-16", tmp_path)
    by_id = {r["match_id"]: r for r in day["matches"]}
    assert by_id["sporttery-2040801"]["hit"] is True
    assert by_id["sporttery-2040801"]["llm_hit"] is True
    assert by_id["sporttery-2040802"]["hit"] is True
    assert by_id["sporttery-2040802"]["llm_hit"] is False
    assert day["summary"]["hit"] == 2
    assert day["summary"]["hit_rate"] == 100.0
    assert day["summary"]["llm_n"] == 2
    assert day["summary"]["llm_hit"] == 1
    assert day["summary"]["llm_hit_rate"] == 50.0
    assert day["summary"]["llm_hit_rate"] != day["summary"]["hit_rate"]
