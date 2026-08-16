from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import store_view as sv

CST = timezone(timedelta(hours=8))


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
