from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import app as web
import store_view as sv

CST = timezone(timedelta(hours=8))


def test_board_keeps_sales_day_separate_from_cross_midnight_kickoff(tmp_path: Path):
    """A 00:30 Wednesday fixture numbered Tuesday belongs to Tuesday's sales day."""
    now = datetime(2026, 8, 25, 20, 0, tzinfo=CST)
    live = [{
        "matchId": 2042001,
        "matchNumStr": "周二001",
        "leagueAbbName": "意甲",
        "homeTeamAbbName": "甲",
        "awayTeamAbbName": "乙",
        "matchDate": "2026-08-26",
        "matchTime": "00:30",
        "matchStatusName": "已开售",
        "h": "2.10", "d": "3.20", "a": "3.40",
    }]

    row = sv.board(now=now, live_rows=live, root=tmp_path)["matches"][0]

    assert row["sales_day"] == "2026-08-25"
    assert row["kickoff_date"] == "2026-08-26"
    assert row["kickoff"].startswith("2026-08-26T00:30:00+08:00")


def test_matches_api_filters_by_explicit_sales_day_not_kickoff_date(monkeypatch):
    cross_midnight = {
        "match_id": "sporttery-2042001",
        "sales_day": "2026-08-25",
        "kickoff_date": "2026-08-26",
        "kickoff": "2026-08-26T00:30:00+08:00",
    }
    next_sale = {
        "match_id": "sporttery-2042002",
        "sales_day": "2026-08-26",
        "kickoff_date": "2026-08-26",
        "kickoff": "2026-08-26T20:00:00+08:00",
    }
    monkeypatch.setattr(sv, "board", lambda: {
        "matches": [cross_midnight, next_sale], "summary": {},
    })

    payload = TestClient(web.app).get("/api/matches?sales_day=2026-08-25").json()

    assert payload["sales_day"] == "2026-08-25"
    assert [row["match_id"] for row in payload["matches"]] == ["sporttery-2042001"]


def test_light_evidence_discloses_uncollected_lineup_and_form():
    import light_evidence as le
    text = le.build_one(1, {
        "match_num": "周日022", "home": "西班牙人", "away": "莱万特",
        "league": "西甲", "kickoff_iso": "2026-08-17T01:00:00+08:00",
        "match_id": 2040907, "model_odds": [1.85, 3.18, 3.65],
    }, "C")
    assert "以上仅为采集规则，不是本场事实" in text
    assert "未深度搜索" in text
    assert "双方近况/轮次背景未抓取" in text
    assert "两个独立媒体" not in text
    assert "20个独立主机投票" not in text
    assert "getLeagueData/La_liga/2025" in text
    assert "以赛前官方名单为准" not in text


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
    assert sv.status_zh("UNAVAILABLE") == "未采集"
    assert sv.status_zh("VALID") == "有效"
    assert sv.status_zh("MARKET_BASELINE") == "市场基线"


def test_load_late_info_exposes_next_scheduled_refresh(tmp_path: Path):
    due = tmp_path / "forward" / "2026-08-24"
    due.mkdir(parents=True)
    next_refresh = "2999-08-24T00:00:00+00:00"
    (due / "late_info_due.json").write_text(json.dumps({
        "matches": [{
            "match_id": "sporttery-2040999",
            "home": "主队",
            "away": "客队",
            "next_refresh_at": next_refresh,
        }],
    }), encoding="utf-8")

    _, summary = sv.load_late_info(tmp_path)

    assert summary["scheduled_refresh_pending"] == 1
    assert summary["next_refresh_at"] == next_refresh
    assert summary["next_refresh_match_id"] == "sporttery-2040999"


def test_load_late_info_preserves_detailed_injury_and_lineup(tmp_path: Path):
    folder = tmp_path / "late_info"
    folder.mkdir()
    events = [
        {
            "kind": "injury", "match_id": 2041038, "status": "VALID",
            "collected_at": "2026-08-24T22:30:00+00:00", "snapshot": "T-75",
            "absence": {
                "home": {"team": "博塔弗戈", "players": [{"name": "甲球员", "pos": "后卫", "type": "伤"}]},
                "away": {"team": "巴竞技", "players": [{"name": "乙球员", "pos": "前锋", "type": "停赛"}]},
            },
        },
        {
            "kind": "lineup", "match_id": 2041038, "status": "VALID",
            "collected_at": "2026-08-24T22:31:00+00:00", "snapshot": "T-75",
            "lineup": {
                "home": {"starting_count": 2, "starting": ["主门将", "主后卫"], "missing": []},
                "away": {"starting_count": 2, "starting": ["客门将", "客前锋"], "missing": ["客中场"]},
            },
        },
    ]
    (folder / "events.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in events) + "\n", encoding="utf-8",
    )

    by_match, _ = sv.load_late_info(tmp_path)

    detail = by_match["sporttery-2041038"]
    assert detail["injury_zh"] == "有效"
    assert detail["injury_detail"]["home"]["players"][0] == {"name": "甲球员", "pos": "后卫", "type": "伤"}
    assert detail["lineup_zh"] == "有效"
    assert detail["lineup_detail"]["away"]["starting"] == ["客门将", "客前锋"]
    assert detail["lineup_detail"]["away"]["missing"] == ["客中场"]
    assert detail["lineup_collected_at"] == "2026-08-24T22:31:00+00:00"


def test_load_evidence_details_projects_audited_collected_facts(tmp_path: Path):
    folder = tmp_path / "forward" / "2026-08-25" / "evidence_snapshots"
    folder.mkdir(parents=True)
    (folder / "sporttery-2041038.json").write_text(json.dumps({
        "match_id": "sporttery-2041038",
        "collected_at": "2026-08-24T04:18:25+00:00",
        "evidence_audit": {"entries": {
            "team_stats": {"status": "VALID", "source_id": "sporttery.preview", "source_url": "https://example.test/stats", "refreshed_at": "2026-08-24T04:18:25+00:00", "value": {"strength": {"sample_legs": 10, "raw": {"home_goal_avg": 1.6, "away_goal_avg": 2.2, "home_loss_avg": 1.3, "away_loss_avg": 1.5}, "note": "近10场统计"}}},
            "recent_form": {"status": "VALID", "source_id": "api-sports.io", "source_url": "https://example.test/form", "refreshed_at": "2026-08-24T04:18:25+00:00", "value": {"home": [{"date": "2026-05-23", "league": "意甲", "home": "博洛尼亚", "away": "国际米兰", "score_90": "3-3"}], "away": [{"date": "2026-05-23", "league": "意甲", "home": "拉齐奥", "away": "比萨", "score_90": "2-1"}]}},
            "injury": {"status": "VALID", "source_id": "sporttery.preview", "value": {"home": {"team": "博洛尼亚", "players": [{"name": "甲", "pos": "中场", "type": "伤"}]}, "away": {"team": "拉齐奥", "players": []}}},
            "suspensions": {"status": "EMPTY_UNCONFIRMED", "source_id": "api-sports.io", "value": {"home": [], "away": []}},
            "starting_xi": {"status": "PENDING_REFRESH", "source_id": "official.lineup.pending", "value": None, "missing_reason": "OFFICIAL_XI_NOT_PUBLISHED_OR_NOT_ATTACHED"},
        }},
    }, ensure_ascii=False), encoding="utf-8")

    detail = sv.load_evidence_details(tmp_path)["sporttery-2041038"]

    assert detail["team_stats"]["status_zh"] == "有效"
    assert detail["team_stats"]["summary"]["home_goal_avg"] == 1.6
    assert detail["recent_form"]["home"][0]["score_90"] == "3-3"
    assert detail["injury"]["home"]["players"][0]["name"] == "甲"
    assert detail["suspensions"]["status_zh"] == "空结果未确认"
    assert detail["starting_xi"]["status_zh"] == "待刷新"
    assert detail["starting_xi"]["missing_reason_zh"] == "官方首发尚未发布或未附加"


def test_load_evidence_details_can_read_explicit_shared_fact_root(tmp_path: Path):
    isolated = tmp_path / "isolated"
    shared = tmp_path / "shared"
    folder = shared / "forward" / "2026-08-25" / "evidence_snapshots"
    folder.mkdir(parents=True)
    (folder / "sporttery-2041038.json").write_text(json.dumps({
        "match_id": "sporttery-2041038", "collected_at": "2026-08-24T04:18:25+00:00",
        "evidence_audit": {"entries": {}},
    }), encoding="utf-8")

    details = sv.load_evidence_details(isolated, shared_root=shared)

    assert "sporttery-2041038" in details


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


def test_matches_api_preserves_explicit_empty_job_evidence_arrays(tmp_path: Path, monkeypatch):
    """Dropping falsey canonical arrays must make this API-boundary assertion fail."""
    jobs = tmp_path / "jobs" / "2026-08-25"
    jobs.mkdir(parents=True)
    (jobs / "sporttery-2041050.json").write_text(json.dumps({
        "identity": {"match_id": "sporttery-2041050", "sales_day": "2026-08-25",
                     "kickoff": "2026-08-26T00:30:00+08:00", "competition": "韩职"},
        "outputs": [{
            "track": "llm",
            "direction": "主胜",
            "evidence_missing_fields": [],
            "evidence_chain_fields": [],
            "evidence_status": "OK",
            "evidence_collected_at": "2026-08-25T00:00:00+08:00",
            "evidence_age_minutes": 30.0,
            "evidence_refs": {"snapshot": "snapshot.json"},
            "evidence_conflicts": [],
        }],
    }), encoding="utf-8")
    live = [{
        "matchId": 2041050,
        "matchNumStr": "周二002",
        "leagueAbbName": "韩职",
        "homeTeamAbbName": "济州SK",
        "awayTeamAbbName": "浦项制铁",
        "matchDate": "2026-08-25",
        "matchTime": "18:30",
        "matchStatusName": "已开售",
        "h": "2.10",
        "d": "3.10",
        "a": "2.92",
    }]
    monkeypatch.setattr(sv, "store_root", lambda: tmp_path)
    monkeypatch.setattr(sv, "fetch_live_selling", lambda now=None: live)

    response = TestClient(web.app).get("/api/matches?sales_day=2026-08-25")

    assert response.status_code == 200
    llm = response.json()["matches"][0]["llm"]
    assert llm["evidence_missing_fields"] == []
    assert llm["evidence_chain_fields"] == []
    assert llm["evidence_status"] == "OK"
    assert llm["evidence_collected_at"] == "2026-08-25T00:00:00+08:00"
    assert llm["evidence_age_minutes"] == 30.0
    assert llm["evidence_refs"] == {"snapshot": "snapshot.json"}
    assert llm["evidence_conflicts"] == []
    assert llm["sales_day"] == "2026-08-25"
    assert llm["kickoff"] == "2026-08-26T00:30:00+08:00"


def test_board_never_attaches_same_team_evidence_from_a_different_match_id(tmp_path: Path):
    ev_dir = tmp_path / "evidence_old_day"
    ev_dir.mkdir()
    (ev_dir / "evidence_001_甲_乙.md").write_text(
        "赛事：英超\n体彩 sporttery-2040001 周一001 甲 vs 乙\n",
        encoding="utf-8",
    )
    live = [{
        "matchId": 2049999, "matchNumStr": "周二001", "leagueAbbName": "英超",
        "homeTeamAbbName": "甲", "awayTeamAbbName": "乙",
        "matchDate": "2026-08-26", "matchTime": "00:30", "matchStatusName": "已开售",
        "h": "2.10", "d": "3.20", "a": "3.40",
    }]

    row = sv.board(
        now=datetime(2026, 8, 25, 12, 0, tzinfo=CST), live_rows=live, root=tmp_path,
    )["matches"][0]

    assert row["match_id"] == "sporttery-2049999"
    assert row["llm"] is None
    assert row["lights"] is None


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


def test_board_reads_run_isolated_forward_llm_evidence(tmp_path: Path):
    ev = tmp_path / "forward" / "2026-08-18" / "llm_evidence_run_77"
    ev.mkdir(parents=True)
    (ev / "evidence_001_赫根_哈尔姆斯.md").write_text(
        "赛事：瑞超\n体彩 sporttery-2040915 周一002 赫根 vs 哈尔姆斯\n",
        encoding="utf-8",
    )
    now = datetime(2026, 8, 16, 16, 0, tzinfo=CST)
    live = [{
        "matchId": 2040915, "matchNumStr": "周一002", "leagueAbbName": "瑞超",
        "homeTeamAbbName": "赫根", "awayTeamAbbName": "哈尔姆斯",
        "matchDate": "2026-08-18", "matchTime": "01:00", "matchStatusName": "已开售",
        "h": "1.21", "d": "5.6", "a": "8.05",
    }]
    board = sv.board(now=now, live_rows=live, root=tmp_path)
    assert board["matches"][0]["llm"]["source"] == "file"


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


def test_quant_direction_marks_narrow_home_edge_as_home_or_draw():
    assert sv.quant_direction([39.4, 29.8, 30.7]) == {
        "direction": "主胜",
        "alt_direction": "平局",
        "label": "主胜略优，防平",
    }
    assert sv.quant_direction([37.6, 28.4, 33.9])["alt_direction"] == "平局"


def test_quant_direction_keeps_clear_home_edge_as_single_pick():
    assert sv.quant_direction([55.0, 25.0, 20.0]) == {
        "direction": "主胜",
        "alt_direction": None,
        "label": "主胜",
    }


def test_history_labels_unregistered_quant_cover_as_research_and_excludes_it(tmp_path: Path):
    rec = _write_hist_match(
        tmp_path, 2040888, "欧冠", "2026-08-27T03:00:00+08:00",
        [39.4, 29.8, 30.7], [1, 1], "周日008",
    )
    (tmp_path / "backtest" / "registry.jsonl").write_text(
        json.dumps(rec) + "\n", encoding="utf-8",
    )

    row = sv.history_rows(tmp_path, include_shared=False)[0]

    assert row["hit"] is False
    assert row["quant_double_scored"] is False
    assert row["quant_double_hit"] is False
    assert row["quant"]["direction"] == "主胜"
    assert row["quant"]["alt_direction"] is None
    assert row["quant"]["direction_label"] == "主胜"
    assert row["quant"]["research_simulation"] == {
        "direction": "主胜",
        "alt_direction": "平局",
        "label": "主胜略优，防平",
        "policy": sv.QUANT_DOUBLE_DIRECTION_POLICY,
        "policy_version": sv.QUANT_DOUBLE_DIRECTION_POLICY_VERSION,
        "excluded_from_formal_stats": True,
    }


def test_history_scores_only_prediction_time_registered_quant_cover(tmp_path: Path):
    rec = _write_hist_match(
        tmp_path, 2040889, "欧冠", "2026-08-27T03:00:00+08:00",
        [39.4, 29.8, 30.7], [1, 1], "周日009",
    )
    rec["direction_registration"] = {
        "alt_direction": "平局",
        "policy": sv.QUANT_DOUBLE_DIRECTION_POLICY,
        "policy_version": sv.QUANT_DOUBLE_DIRECTION_POLICY_VERSION,
        "prediction_as_of": "2026-08-26T18:00:00+08:00",
    }
    (tmp_path / "backtest" / "registry.jsonl").write_text(
        json.dumps(rec) + "\n", encoding="utf-8",
    )

    row = sv.history_rows(tmp_path, include_shared=False)[0]

    assert row["hit"] is False
    assert row["quant_double_scored"] is True
    assert row["quant_double_hit"] is True
    assert row["quant"]["alt_direction"] == "平局"
    assert row["quant"]["direction_label"] == "主胜 / 平局"
    assert row["quant"]["direction_policy"] == sv.QUANT_DOUBLE_DIRECTION_POLICY
    assert row["quant"]["direction_policy_version"] == sv.QUANT_DOUBLE_DIRECTION_POLICY_VERSION
    assert row["quant"]["direction_prediction_as_of"] == "2026-08-26T18:00:00+08:00"
    assert row["quant"]["research_simulation"] is None


def test_history_rejects_quant_cover_registered_after_kickoff(tmp_path: Path):
    rec = _write_hist_match(
        tmp_path, 2040788, "欧冠", "2026-08-16T03:00:00+08:00",
        [39.4, 29.8, 30.7], [1, 1], "周日008",
    )
    rec["direction_registration"] = {
        "alt_direction": "平局",
        "policy": sv.QUANT_DOUBLE_DIRECTION_POLICY,
        "policy_version": sv.QUANT_DOUBLE_DIRECTION_POLICY_VERSION,
        "prediction_as_of": "2026-08-16T03:01:00+08:00",
    }
    (tmp_path / "backtest" / "registry.jsonl").write_text(
        json.dumps(rec) + "\n", encoding="utf-8",
    )

    row = sv.history_rows(tmp_path, include_shared=False)[0]

    assert row["quant"]["alt_direction"] is None
    assert row["quant_double_hit"] is False
    assert row["quant"]["research_simulation"]["excluded_from_formal_stats"] is True


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
