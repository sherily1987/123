# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import runner

N8N_LLM = Path(__file__).resolve().parent / "n8n" / "工作流_LLM轨预测.json"

CST = timezone(timedelta(hours=8))


def test_start_backtest_is_not_aliased_to_settle():
    assert runner.start_backtest is not runner.start_settle
    assert callable(runner.task_backtest)


def test_fusion_to_llm_match_maps_sporttery_meta():
    got = runner.fusion_to_llm_match({
        "home": "赫根",
        "away": "哈尔姆斯",
        "competition": "瑞超",
        "kickoff": "2026-08-18T01:00:00+08:00",
        "mode": "market_only",
        "odds": [1.21, 5.6, 8.05],
        "sporttery_meta": {
            "match_id": 2040915,
            "match_num": "周一002",
            "home_full": "赫根",
            "away_full": "哈尔姆斯塔德",
        },
        "hhad": {"line": -1.0, "odds": [1.71, 4.0, 3.4]},
        "evidence_chain": {"starting_xi": {"status": "PREDICTED", "source_id": "fotmob", "refreshed_at": "2026-08-18T00:00:00+08:00"}},
        "evidence_snapshot_ref": "F:/evidence/sporttery-2040915.json",
    })
    assert got["match_id"] == 2040915
    assert got["match_num"] == "周一002"
    assert got["league"] == "瑞超"
    assert got["model_odds"] == [1.21, 5.6, 8.05]
    assert got["kickoff_iso"] == "2026-08-18T01:00:00+08:00"
    assert got["team_ids"]["away_full"] == "哈尔姆斯塔德"
    assert got["evidence_chain"]["starting_xi"]["status"] == "PREDICTED"
    assert got["evidence_snapshot_ref"].endswith("sporttery-2040915.json")


def test_future_llm_matches_skips_kicked_off():
    now = datetime(2026, 8, 18, 2, 0, tzinfo=CST)
    rows = runner._future_llm_matches([
        {"home": "甲", "away": "乙", "kickoff": "2026-08-18T01:00:00+08:00",
         "mode": "market_only", "odds": [2, 3, 4],
         "sporttery_meta": {"match_id": 1, "match_num": "周一001"}},
        {"home": "丙", "away": "丁", "kickoff": "2026-08-18T20:00:00+08:00",
         "mode": "market_only", "odds": [2, 3, 4],
         "sporttery_meta": {"match_id": 2, "match_num": "周一002"}},
    ], now)
    assert [m["match_id"] for m in rows] == [2]


def test_attach_collected_evidence_projects_snapshot_and_late_info(tmp_path: Path):
    forward = tmp_path / "forward"
    snap_dir = forward / "2026-08-24" / "evidence_snapshots"
    snap_dir.mkdir(parents=True)
    (snap_dir / "sporttery-2041021.json").write_text(json.dumps({
        "match_id": "sporttery-2041021",
        "evidence_audit": {
            "entries": {
                "recent_form": {"status": "VALID", "source_id": "sporttery.preview",
                                 "refreshed_at": "2026-08-23T12:00:00+00:00",
                                 "value": {"home": ["W"], "away": ["D"]}},
                "starting_xi": {"status": "PENDING_REFRESH", "source_id": "official.lineup.pending"},
            }
        },
    }), encoding="utf-8")
    late = tmp_path / "late.jsonl"
    late.write_text(json.dumps({
        "match_id": 2041021, "kind": "lineup", "status": "PREDICTED",
        "lineup": {"home": ["A"], "away": ["B"]},
        "collected_at": "2026-08-23T20:00:00+08:00",
        "gate": {"minutes_to_kickoff": 60},
    }) + "\n", encoding="utf-8")
    matches = [{"match_id": 2041021, "evidence_chain": {
        "team_stats": {"status": "VALID", "source_id": "quant"}
    }}]
    got = runner.attach_collected_evidence(
        matches, "2026-08-24", forward_root=forward, late_events_path=late
    )
    assert got["snapshots_attached"] == 1
    assert got["late_info_matches_merged"] == 1
    assert matches[0]["evidence_chain"]["recent_form"]["status"] == "VALID"
    assert matches[0]["evidence_chain"]["starting_xi"]["status"] == "PREDICTED"
    assert "starting_xi" not in matches[0]["evidence_audit"]["missing_fields"]
    assert matches[0]["evidence_audit"]["evidence_status"] == "GAP"
    import light_evidence
    rendered = light_evidence.render_fusion_evidence(matches[0])
    assert "missing_fields=injury,suspensions" in rendered
    assert "starting_xi: status=PREDICTED" in rendered
    assert matches[0]["evidence_snapshot_ref"].endswith("sporttery-2041021.json")


def test_attach_reports_missing_snapshot_ids(tmp_path: Path):
    matches = [{"match_id": 2041999}, {"match_id": 2042000}]
    got = runner.attach_collected_evidence(matches, "2026-08-24", forward_root=tmp_path)
    assert got["snapshots_attached"] == 0
    assert got["missing_snapshot_ids"] == ["sporttery-2041999", "sporttery-2042000"]


def test_attach_rejects_snapshot_collected_after_kickoff(tmp_path: Path):
    snap_dir = tmp_path / "2026-08-24" / "evidence_snapshots"
    snap_dir.mkdir(parents=True)
    (snap_dir / "sporttery-2041999.json").write_text(json.dumps({
        "match_id": "sporttery-2041999",
        "collected_at": "2026-08-24T04:00:00+00:00",
        "evidence_audit": {"collected_at": "2026-08-24T04:00:00+00:00", "entries": {}},
    }), encoding="utf-8")
    matches = [{"match_id": 2041999, "kickoff_iso": "2026-08-24T03:00:00+08:00"}]
    got = runner.attach_collected_evidence(matches, "2026-08-24", forward_root=tmp_path)
    assert got["snapshots_attached"] == 0
    assert got["missing_snapshot_ids"] == ["sporttery-2041999"]
    assert got["snapshot_rejections"] == [{"match_id": "sporttery-2041999", "reason": "SNAPSHOT_AFTER_KICKOFF"}]


def test_fusion_evidence_markdown_exposes_audit_summary():
    import light_evidence
    text = light_evidence.render_fusion_evidence({
        "kickoff_iso": "2026-08-24T03:00:00+08:00",
        "evidence_audit": {
            "evidence_status": "GAP", "missing_fields": ["starting_xi"],
            "collected_at": "2026-08-23T12:00:00+00:00",
            "kickoff": "2026-08-24T03:00:00+08:00",
        },
        "evidence_chain": {"starting_xi": {"status": "PENDING_REFRESH", "source_id": "official.lineup.pending"}},
    })
    assert "evidence_audit: status=GAP" in text
    assert "missing_fields=starting_xi" in text


def test_fusion_evidence_blockquotes_do_not_break_llm_source_gate():
    import light_evidence
    import importlib.util
    llm = runner.llm_repo()
    import sys
    if str(llm) not in sys.path:
        sys.path.insert(0, str(llm))
    spec = importlib.util.spec_from_file_location("llm_predict_source_gate", llm / "predict.py")
    predict = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(predict)
    match = {
        "match_num": "周一001", "home": "甲", "away": "乙", "league": "测试联赛",
        "kickoff_iso": "2026-08-25T03:00:00+08:00", "match_id": 1,
        "model_odds": [2, 3, 4], "team_ids": {"home_full": "甲", "away_full": "乙"},
        "evidence_chain": {
            "team_stats": {"status": "VALID", "source_id": "api", "refreshed_at": "2026-08-24T12:00:00+00:00", "value": {"sample": 5}},
            "recent_form": {"status": "VALID", "source_id": "api", "refreshed_at": "2026-08-24T12:00:00+00:00", "value": {"home": ["W"], "away": ["L"]}},
        },
        "evidence_audit": {"evidence_status": "OK", "missing_fields": [], "collected_at": "2026-08-24T12:00:00+00:00", "kickoff": "2026-08-25T03:00:00+00:00"},
    }
    text = light_evidence.build_one(1, match, "C")
    result = predict.assess_evidence(text, kickoff=match["kickoff_iso"], now="2026-08-24T20:00:00+08:00")
    assert result["ok"] is True


def test_auto_collect_prematch_evidence_is_id_scoped(tmp_path: Path, monkeypatch):
    seen = {}

    class Result:
        returncode = 0
        stdout = '{"count": 1, "rows": []}\n'
        stderr = ""

    def fake_cli(args, timeout=0):
        seen["args"] = args
        seen["timeout"] = timeout
        return Result()

    monkeypatch.setattr(runner, "_cli", fake_cli)
    monkeypatch.setattr(runner, "forward_work_dir", lambda: tmp_path / "forward")
    got = runner.auto_collect_prematch_evidence(
        tmp_path / "inputs.json", "2026-08-24", ["sporttery-2", "sporttery-1", "sporttery-2"]
    )
    assert got["status"] == "ok"
    assert got["attempted"] == 2
    assert seen["args"][:3] == ["prematch-evidence", "--input", str((tmp_path / "inputs.json").resolve())]
    assert seen["args"].count("--match-id") == 2


def test_auto_collect_late_info_is_only_run_within_24h(tmp_path: Path, monkeypatch):
    seen = {}

    class Result:
        returncode = 0
        stdout = '{"matches": 1, "lineup_valid": 1}\n'
        stderr = ""

    def fake_cli(args, timeout=0):
        seen["args"] = args
        seen["timeout"] = timeout
        return Result()

    monkeypatch.setattr(runner, "_cli", fake_cli)
    monkeypatch.setattr(runner, "forward_work_dir", lambda: tmp_path / "forward")
    now = datetime(2026, 8, 23, 12, 0, tzinfo=CST)
    matches = [{"match_id": 2041021, "kickoff_iso": "2026-08-24T03:30:00+08:00"}]
    got = runner.auto_collect_late_info(tmp_path / "inputs.json", "2026-08-24", matches, now=now)
    assert got["status"] == "ok"
    assert got["attempted"] == 1
    assert seen["args"][0] == "late-info"
    assert "--watch" not in seen["args"]
    far = runner.auto_collect_late_info(
        tmp_path / "inputs.json", "2026-08-24",
        [{"match_id": 2041022, "kickoff_iso": "2026-08-25T13:00:00+08:00"}], now=now
    )
    assert far["status"] == "not_needed"


def test_parse_llm_log_extracts_direction_and_skips():
    text = """
⚽ 第1/2场 [周一002] 赫根 VS 哈尔姆斯 | 瑞超 | 2026-08-18 01:00
   证据: evidence_001_赫根_哈尔姆斯.md
  📊 综合方向: 主胜  (2.0/2.0票, 强度100%)
  🎯 比分偏好: 2-0
{"match_index": 2, "status": "evidence_insufficient", "reason": "missing_evidence_file"}
"""
    got = runner.parse_llm_log(text)
    assert got["ok"] == 1
    assert got["skipped"] == 1
    row = got["rows"][0]
    assert row["num"] == "周一002"
    assert row["dir"] == "主胜"
    assert row["strength"] == 100
    assert row["score"] == "2-0"


def test_parse_llm_log_reads_top3_scores():
    text = """
⚽ 第1/1场 [周一004] 拉科 VS 埃尔切 | 西甲 | 2026-08-18 03:00
  📊 综合方向: 主胜  (0.9/1.4票, 强度67%)
  🎯 比分Top3: 1-0, 2-1, 1-1
  🚨 谨慎(证据存在缺口): 建议双选 主胜/平局
"""
    got = runner.parse_llm_log(text)
    row = got["rows"][0]
    assert row["dir"] == "主胜"
    assert row["score"] == "1-0"
    assert row["top_scores"] == ["1-0", "2-1", "1-1"]
    assert row["alt"] == "平局"


def test_parse_llm_log_preserves_model_timestamp_for_calibration():
    text = '''
⚽ 第1/1场 [周一004] 拉科 VS 埃尔切 | 西甲 | 2026-08-18 03:00
  📊 综合方向: 主胜  (1.0/1.0票, 强度100%)
{"direction":"主胜","prediction_as_of":"2026-08-18T00:11:12+00:00","probs_1x2":[55,25,20],"top_scores":["1-0","2-0","1-1"]}
'''
    row = runner.parse_llm_log(text)["rows"][0]
    assert row["model_id"] == "deepseek/deepseek-v4-flash"
    assert row["prediction_as_of"] == "2026-08-18T00:11:12+00:00"
    assert row["probs_1x2"] == [55, 25, 20]
    assert row["top_scores"] == ["1-0", "2-0", "1-1"]


def test_parse_llm_log_keeps_deepseek_single_model_json_without_legacy_banner():
    text = '''
⚽ 第1/1场 [周一001] 博洛尼亚 VS 拉齐奥 | 意甲 | 2026-08-25 00:30
{"direction":"主胜","votes":0.85,"total_votes":1.275,"strength":null,"top_score_pref":"1-0","top_scores":["1-0","1-1","2-1"],"alt_direction":"平局","evidence_gap":true,"models_used":["deepseek/deepseek-v4-flash"],"prediction_as_of":"2026-08-23T15:28:43+00:00"}
'''
    row = runner.parse_llm_log(text)["rows"][0]
    assert row["num"] == "周一001"
    assert row["dir"] == "主胜"
    assert row["strength"] is None
    assert row["score"] == "1-0"
    assert row["model_id"] == "deepseek/deepseek-v4-flash"
    assert row["evidence_gap"] is True


def test_write_llm_jobs_persists_evidence_age_and_missing_fields(tmp_path, monkeypatch):
    import job_ticket

    captured = {}
    monkeypatch.setattr(job_ticket, "jobs_root", lambda: tmp_path)

    def fake_upsert(root, identity, **kwargs):
        captured["identity"] = identity
        captured["llm"] = kwargs["llm"]
        return tmp_path / "job.json"

    monkeypatch.setattr(job_ticket, "upsert_job", fake_upsert)
    n = runner.write_llm_jobs(
        "2026-08-24",
        [{
            "match_num": "周一001", "home": "主队", "away": "客队",
            "competition": "测试联赛", "kickoff": "2026-08-25T00:30:00+08:00",
            "sporttery_meta": {"match_id": 2041028, "match_num": "周一001"},
            "evidence_audit": {
                "evidence_status": "GAP", "missing_fields": ["starting_xi"],
                "collected_at": "2026-08-24T00:00:00+00:00",
            },
            "evidence_snapshot_ref": "F:/evidence/sporttery-2041028.json",
            "evidence_chain": {"recent_form": {"status": "VALID"}},
        }],
        [{
            "num": "周一001", "model_id": "deepseek/deepseek-v4-flash",
            "prediction_as_of": "2026-08-24T01:00:00+00:00", "dir": "主胜",
            "strength": None, "evidence_gap": True, "top_scores": ["1-0"],
        }],
    )
    assert n == 1
    assert captured["llm"]["evidence_status"] == "GAP"
    assert captured["llm"]["evidence_missing_fields"] == ["starting_xi"]
    assert captured["llm"]["evidence_collected_at"] == "2026-08-24T00:00:00+00:00"
    assert captured["llm"]["evidence_age_minutes"] == 60.0
    assert captured["llm"]["evidence_chain_fields"] == ["recent_form"]
    assert captured["llm"]["evidence_refs"]["evidence_snapshot_ref"].endswith("2041028.json")


def test_backfill_llm_job_evidence_metadata_preserves_prediction(tmp_path, monkeypatch):
    import job_ticket

    jobs = tmp_path / "jobs" / "2026-08-24"
    jobs.mkdir(parents=True)
    snapshots = tmp_path / "forward" / "2026-08-24" / "evidence_snapshots"
    snapshots.mkdir(parents=True)
    job = {
        "schema": "football-job-1.0",
        "identity": {"match_id": "sporttery-2041028", "match_num": "周一001",
                     "sales_day": "2026-08-24", "home": "主队", "away": "客队",
                     "competition": "测试", "kickoff": "2026-08-25T00:30:00+08:00"},
        "outputs": [{"track": "llm", "model_id": "deepseek/deepseek-v4-flash",
                     "llm_prediction_as_of": "2026-08-24T01:00:00+00:00",
                     "direction": "主胜", "action": "skip", "evidence_gap": True,
                     "strength": {"type": "vote_share", "value": 0.0}}],
    }
    path = jobs / "sporttery-2041028.json"
    path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    (snapshots / "sporttery-2041028.json").write_text(json.dumps({
        "match_id": "sporttery-2041028", "collected_at": "2026-08-24T00:00:00+00:00",
        "evidence_audit": {"evidence_status": "GAP", "missing_fields": ["starting_xi"],
                            "collected_at": "2026-08-24T00:00:00+00:00",
                            "entries": {"recent_form": {"status": "VALID"}}},
    }), encoding="utf-8")
    monkeypatch.setattr(job_ticket, "jobs_root", lambda: tmp_path / "jobs")
    got = runner.backfill_llm_job_evidence_metadata(
        "2026-08-24", forward_root=tmp_path / "forward"
    )
    assert got["updated"] == 1
    updated = json.loads(path.read_text(encoding="utf-8"))
    out = next(x for x in updated["outputs"] if x["track"] == "llm")
    assert out["direction"] == "主胜"
    assert out["evidence_missing_fields"] == ["starting_xi"]
    assert out["evidence_age_minutes"] == 60.0


def test_prepare_reuses_existing_and_falls_back_to_light(tmp_path: Path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    deep = src / "evidence_030_赫根_哈尔姆斯.md"
    deep.write_text("深度证据 sporttery-2040915\n", encoding="utf-8")
    (src / "evidence_030_赫根_哈尔姆斯_mcp.md").write_text("mcp\n", encoding="utf-8")
    monkeypatch.setattr(
        runner, "existing_evidence_index",
        lambda exclude=None: {"sporttery-2040915": deep},
    )
    dest = tmp_path / "llm_evidence"
    done = runner.prepare_llm_evidence([
        {"match_id": 2040915, "home": "赫根", "away": "哈尔姆斯",
         "league": "瑞超", "kickoff_iso": "2026-08-20T01:00:00+08:00",
         "model_odds": [1.21, 5.6, 8.05], "hhad": {},
         "team_ids": {"home_full": "赫根", "away_full": "哈尔姆斯塔德"},
         "evidence_chain": {"starting_xi": {"status": "PREDICTED", "source_id": "fotmob", "refreshed_at": "2026-08-20T00:00:00+08:00", "value": {"home": ["A"], "away": ["B"]}}},
         "evidence_snapshot_ref": "F:/evidence/sporttery-2040915.json"},
        {"match_id": 2999777, "home": "甲", "away": "乙",
         "league": "瑞超", "kickoff_iso": "2026-08-20T03:00:00+08:00",
         "model_odds": [2.1, 3.3, 3.4], "hhad": {},
         "team_ids": {"home_full": "甲", "away_full": "乙"}},
    ], dest)
    assert [x["source"] for x in done] == ["reuse", "light"]
    assert "深度证据" in (dest / "evidence_001_赫根_哈尔姆斯.md").read_text(encoding="utf-8")
    assert "PREDICTED" in (dest / "evidence_001_赫根_哈尔姆斯.md").read_text(encoding="utf-8")
    assert (dest / "evidence_001_赫根_哈尔姆斯_mcp.md").read_text(encoding="utf-8") == "mcp\n"
    light = (dest / "evidence_002_甲_乙.md").read_text(encoding="utf-8")
    assert "## 1. 伤停/阵容" in light
    assert "matchId=2999777" in light


def test_n8n_llm_workflow_posts_to_api_llm():
    wf = json.loads(N8N_LLM.read_text(encoding="utf-8"))
    assert wf["id"] == "hmQuantLlm0001"
    urls = [n["parameters"].get("url", "") for n in wf["nodes"]]
    assert any("/api/llm" in u for u in urls)
    assert any("/api/run/" in u for u in urls)
    assert "readWriteFile" not in {n["type"] for n in wf["nodes"]}
