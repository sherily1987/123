import json
import os
import pytest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as web
import runner


def _run(run_id: int, run_type: str, status: str = "error") -> dict:
    return {
        "id": run_id,
        "run_type": run_type,
        "status": status,
        "total": 2,
        "done": 1,
        "message": "partial failure",
        "started_at": "2026-08-25T00:00:00+00:00",
        "finished_at": "2026-08-25T00:01:00+00:00",
    }


def test_run_start_atomically_rejects_a_second_running_run_type(tmp_path, monkeypatch):
    monkeypatch.setattr(web.db, "DB_PATH", tmp_path / "app.db")
    web.db.init()

    first_id = web.db.run_start("predict")
    with pytest.raises(web.db.RunAlreadyActive) as caught:
        web.db.run_start("predict")

    assert caught.value.active_run["id"] == first_id
    assert [row["id"] for row in web.db.run_active("predict")] == [first_id]
    web.db.run_update(first_id, status="done")
    assert web.db.run_start("predict") != first_id


def test_service_startup_recovers_run_with_dead_matching_owner(tmp_path, monkeypatch):
    """Catches a crashed daemon leaving a permanent same-type 409 behind."""
    monkeypatch.setattr(web.db, "DB_PATH", tmp_path / "app.db")
    web.db.init()
    abandoned_id = web.db.run_start(
        "predict", message="进程关闭前仍在运行",
        owner_pid=41001, owner_identity=web.BUILD_IDENTITY,
    )
    monkeypatch.setattr(web.db, "_owner_is_alive", lambda _pid: False, raising=False)

    with TestClient(web.app):
        pass

    abandoned = web.db.run_get(abandoned_id)
    assert abandoned["status"] == "error"
    assert "服务重启" in abandoned["message"]
    assert abandoned["finished_at"]

    current_id = web.db.run_start("predict")
    assert current_id != abandoned_id
    assert web.db.run_get(current_id)["status"] == "running"


def test_service_startup_preserves_run_with_live_matching_owner(tmp_path, monkeypatch):
    """Catches a second service instance aborting an owner that is still alive."""
    monkeypatch.setattr(web.db, "DB_PATH", tmp_path / "app.db")
    web.db.init()
    live_id = web.db.run_start(
        "llm", owner_pid=os.getpid(), owner_identity=web.BUILD_IDENTITY,
    )
    monkeypatch.setattr(web.db, "_owner_is_alive", lambda _pid: True, raising=False)

    with TestClient(web.app):
        pass

    assert web.db.run_get(live_id)["status"] == "running"
    with pytest.raises(web.db.RunAlreadyActive):
        web.db.run_start("llm")


def test_run_progress_and_recent_logs_survive_database_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(web.db, "DB_PATH", tmp_path / "app.db")
    web.db.init()
    run_id = web.db.run_start("llm", total=2)

    progress = {
        "stage": "生成分析",
        "current": {"match_id": "sporttery-2041051", "home": "甲", "away": "乙"},
        "evidence": {"status": "有缺口", "missing": ["官方首发"]},
    }
    web.db.run_update(run_id, progress=progress, log="开始生成甲 vs 乙")
    web.db.run_update(run_id, log="临时结果已保存")

    row = web.db.run_get(run_id)
    assert row["progress"] == progress
    assert row["logs"] == ["开始生成甲 vs 乙", "临时结果已保存"]

    response = TestClient(web.app).get(f"/api/run/{run_id}")
    assert response.status_code == 200
    assert response.json()["progress"]["stage"] == "生成分析"
    assert response.json()["logs"][-1] == "临时结果已保存"


def test_active_runs_endpoint_is_authoritative_after_reload(monkeypatch):
    active = _run(90, "collect", "running")
    monkeypatch.setattr(web.db, "run_active", lambda run_type=None: [active])

    response = TestClient(web.app).get("/api/runs/active")

    assert response.status_code == 200
    assert response.json() == {"runs": [active]}


def test_duplicate_task_route_returns_409_with_current_run_identity(monkeypatch):
    active = _run(92, "predict", "running")

    def reject(_day):
        raise web.db.RunAlreadyActive(active)

    monkeypatch.setattr(web.runner, "start_predict", reject)
    response = TestClient(web.app).post("/api/predict", json={"sales_day": "2026-08-25"})

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "run_type_running",
        "run_type": "predict",
        "run_id": 92,
        "message": "同类任务已在运行",
    }


def test_retry_failed_rejects_non_itemized_run(monkeypatch):
    monkeypatch.setattr(web.db, "run_get", lambda run_id: _run(run_id, "settle"))
    response = TestClient(web.app).post("/api/run/7/retry-failed")
    assert response.status_code == 409
    assert "不支持逐项重试" in response.json()["detail"]


def test_retry_failed_rejects_running_or_missing_failure_list(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", tmp_path)
    monkeypatch.setattr(web.db, "run_get", lambda run_id: _run(run_id, "predict", "running"))
    running = TestClient(web.app).post("/api/run/8/retry-failed")
    assert running.status_code == 409
    assert "尚未结束" in running.json()["detail"]

    monkeypatch.setattr(web.db, "run_get", lambda run_id: _run(run_id, "predict"))
    missing = TestClient(web.app).post("/api/run/8/retry-failed")
    assert missing.status_code == 409
    assert "失败清单" in missing.json()["detail"]


def test_task_routes_reject_unsafe_sales_day_before_start(monkeypatch):
    started = []
    monkeypatch.setattr(web.runner, "start_llm", lambda day: started.append(day))
    response = TestClient(web.app).post("/api/llm", json={"sales_day": "../../outside"})
    assert response.status_code == 400
    assert "sales_day" in response.json()["detail"]
    assert started == []


def test_task_routes_reject_conflicting_sales_and_kickoff_dates(monkeypatch):
    started = []
    monkeypatch.setattr(web.runner, "start_llm", lambda day: started.append(day))

    response = TestClient(web.app).post("/api/llm", json={
        "sales_day": "2026-08-25",
        "kickoff_date": "2026-08-26",
    })

    assert response.status_code == 400
    assert "sales_day" in response.json()["detail"]
    assert "kickoff_date" in response.json()["detail"]
    assert started == []


def test_retry_failed_passes_only_server_side_failed_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", tmp_path)
    runner.write_run_failures(9, "predict", "2026-08-25", ["sporttery-2", "sporttery-1", "sporttery-2"])
    monkeypatch.setattr(web.db, "run_get", lambda run_id: _run(run_id, "predict"))
    captured = {}

    def fake_start(day, match_ids=None):
        captured.update(day=day, match_ids=match_ids)
        return 19

    monkeypatch.setattr(web.runner, "start_predict", fake_start)
    response = TestClient(web.app).post(
        "/api/run/9/retry-failed",
        json={"match_ids": ["sporttery-client-injected"]},
    )
    assert response.status_code == 200
    assert response.json() == {
        "run_id": 19,
        "status": "started",
        "retry_of": 9,
        "run_type": "predict",
        "match_ids": ["sporttery-1", "sporttery-2"],
    }
    assert captured == {
        "day": "2026-08-25",
        "match_ids": ["sporttery-1", "sporttery-2"],
    }


def test_run_status_exposes_exact_sidecar_failure_count(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", tmp_path)
    runner.write_run_failures(10, "llm", "2026-08-25", ["sporttery-1", "sporttery-2"])
    monkeypatch.setattr(web.db, "run_get", lambda run_id: _run(run_id, "llm"))
    response = TestClient(web.app).get("/api/run/10")
    assert response.status_code == 200
    assert response.json()["failed"] == 2


def test_run_failure_sidecar_is_atomic_and_has_only_contract_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", tmp_path)
    path = runner.write_run_failures(11, "llm", "2026-08-25", ["2042", "sporttery-2041"])
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "run_type": "llm",
        "sales_day": "2026-08-25",
        "match_ids": ["sporttery-2041", "sporttery-2042"],
    }
    assert list(tmp_path.glob("*.tmp")) == []


def test_run_failure_sidecar_rejects_non_numeric_ids_and_unsafe_sales_day(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", tmp_path)
    with pytest.raises(ValueError, match="invalid match id"):
        runner.write_run_failures(12, "predict", "2026-08-25", ["sporttery-../../outside"])
    with pytest.raises(ValueError, match="invalid sales day"):
        runner.write_run_failures(13, "llm", "../../outside", ["sporttery-2041"])


def test_run_failure_sidecar_rejects_mixed_valid_and_invalid_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", tmp_path)
    with pytest.raises(ValueError, match="invalid match id"):
        runner.write_run_failures(
            14, "predict", "2026-08-25", ["sporttery-2041", "bad-id", "sporttery-2041"],
        )
    assert not (tmp_path / "14.json").exists()

    (tmp_path / "15.json").write_text(json.dumps({
        "run_type": "llm",
        "sales_day": "2026-08-25",
        "match_ids": ["sporttery-2041", "bad-id"],
    }), encoding="utf-8")
    assert runner.read_run_failures(15) is None


def test_predict_partial_failure_preserves_success_and_writes_exact_ids(tmp_path, monkeypatch):
    failures = tmp_path / "failures"
    forward = tmp_path / "forward"
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", failures)
    monkeypatch.setattr(runner, "forward_work_dir", lambda: forward)
    monkeypatch.setattr(runner.sv, "board", lambda: {"missing": [
        {"match_id": "sporttery-101", "kickoff": "2026-08-25T12:00:00+08:00"},
        {"match_id": "sporttery-102", "kickoff": "2026-08-25T14:00:00+08:00"},
    ]})

    def fake_cli(args, timeout=3600):
        output = Path(args[args.index("--emit-input") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"matches": [
            {"mode": "market_only", "sporttery_meta": {"match_id": 101, "match_num": "001"}},
            {"mode": "market_only", "sporttery_meta": {"match_id": 102, "match_num": "002"}},
        ]}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    recorded = []

    def fake_record(match, work):
        mid = match["sporttery_meta"]["match_id"]
        if mid == 101:
            raise RuntimeError("one item failed")
        recorded.append(mid)
        return "recorded"

    updates = []
    monkeypatch.setattr(runner, "_cli", fake_cli)
    monkeypatch.setattr(runner, "_record_one", fake_record)
    monkeypatch.setattr(runner.db, "run_update", lambda run_id, **kw: updates.append(kw))

    runner.task_predict(21, "2026-08-25")

    assert recorded == [102]
    assert runner.read_run_failures(21) == {
        "run_type": "predict",
        "sales_day": "2026-08-25",
        "match_ids": ["sporttery-101"],
    }
    assert updates[-1]["status"] == "error"
    assert updates[-1]["done"] == 1
    assert updates[-1]["total"] == 2


def test_predict_sales_day_keeps_cross_midnight_fixture_and_collects_its_kickoff_day(tmp_path, monkeypatch):
    forward = tmp_path / "forward"
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", tmp_path / "failures")
    monkeypatch.setattr(runner, "forward_work_dir", lambda: forward)
    monkeypatch.setattr(runner.sv, "board", lambda: {"missing": [{
        "match_id": "sporttery-103",
        "sales_day": "2026-08-25",
        "kickoff": "2026-08-26T00:30:00+08:00",
    }]})
    collected_days = []

    def fake_cli(args, timeout=3600):
        collected_days.append(args[args.index("--kickoff-date") + 1])
        output = Path(args[args.index("--emit-input") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"matches": [{
            "mode": "market_only",
            "sporttery_meta": {"match_id": 103, "match_num": "周一003"},
        }]}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    recorded = []
    updates = []
    monkeypatch.setattr(runner, "_cli", fake_cli)
    monkeypatch.setattr(runner, "_record_one", lambda match, work: recorded.append(
        (match["sporttery_meta"]["match_id"], work.name),
    ))
    monkeypatch.setattr(runner.db, "run_update", lambda run_id, **kw: updates.append(kw))

    runner.task_predict(33, "2026-08-25")

    assert collected_days == ["2026-08-26"]
    assert recorded == [(103, "2026-08-26")]
    assert updates[-1]["status"] == "done"


def test_sales_day_collection_covers_same_day_and_cross_midnight_day():
    assert runner.sales_day_kickoff_dates("2026-08-25") == ["2026-08-25", "2026-08-26"]


def test_collect_uses_sales_day_once_and_counts_emitted_had_matches(tmp_path, monkeypatch):
    calls = []
    updates = []
    monkeypatch.setattr(runner, "forward_work_dir", lambda: tmp_path)

    def fake_cli(args, timeout=900):
        calls.append(args)
        output = Path(args[args.index("--emit-input") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"matches": [
            {"kickoff": "2026-08-25T20:00:00+08:00"},
            {"kickoff": "2026-08-26T02:00:00+08:00"},
        ]}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_cli", fake_cli)
    monkeypatch.setattr(runner.db, "run_update", lambda run_id, **kw: updates.append(kw))

    runner.task_collect("2026-08-25", 51)

    assert len(calls) == 1
    assert calls[0][calls[0].index("--sales-day") + 1] == "2026-08-25"
    assert "--kickoff-date" not in calls[0]
    assert Path(calls[0][calls[0].index("--emit-input") + 1]).parent.name == "2026-08-25"
    assert updates[-1]["status"] == "done"
    assert updates[-1]["done"] == 2
    assert updates[-1]["total"] == 2


def test_collect_reports_empty_sales_day_had_pool(tmp_path, monkeypatch):
    updates = []
    monkeypatch.setattr(runner, "forward_work_dir", lambda: tmp_path)

    def fake_cli(args, timeout=900):
        output = Path(args[args.index("--emit-input") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"matches": []}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_cli", fake_cli)
    monkeypatch.setattr(runner.db, "run_update", lambda run_id, **kw: updates.append(kw))

    runner.task_collect("2026-08-25", 52)

    assert updates[-1]["status"] == "done"
    assert updates[-1]["done"] == 0
    assert updates[-1]["total"] == 0
    assert updates[-1]["message"] == "当前销售日没有开售且有HAD赔率的比赛"


def test_llm_sales_day_input_includes_explicit_cross_midnight_fixture(tmp_path, monkeypatch):
    for day, matches in {
        "2026-08-25": [{"kickoff": "2026-08-25T20:00:00+08:00", "sales_day": "2026-08-25", "sporttery_meta": {"match_id": 1}}],
        "2026-08-26": [
            {"kickoff": "2026-08-26T00:30:00+08:00", "sales_day": "2026-08-25", "sporttery_meta": {"match_id": 2}},
            {"kickoff": "2026-08-26T19:00:00+08:00", "sales_day": "2026-08-26", "sporttery_meta": {"match_id": 3}},
        ],
    }.items():
        work = tmp_path / day
        work.mkdir()
        (work / "inputs_prematch.json").write_text(json.dumps({"matches": matches}), encoding="utf-8")
    monkeypatch.setattr(runner, "forward_work_dir", lambda: tmp_path)
    got = runner._sales_day_prematch_matches("2026-08-25")
    assert [row["sporttery_meta"]["match_id"] for row in got] == [1, 2]


def test_scoped_predict_unresolved_targets_stay_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", tmp_path / "failures")
    monkeypatch.setattr(runner.sv, "board", lambda: {"missing": []})
    updates = []
    monkeypatch.setattr(runner.db, "run_update", lambda run_id, **kw: updates.append(kw))

    runner.task_predict(31, "2026-08-25", ["sporttery-101"])

    assert updates[-1]["status"] == "error"
    assert updates[-1]["done"] == 0
    assert runner.read_run_failures(31)["match_ids"] == ["sporttery-101"]


def test_scoped_predict_partial_resolution_retains_only_unresolved_id(tmp_path, monkeypatch):
    forward = tmp_path / "forward"
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", tmp_path / "failures")
    monkeypatch.setattr(runner, "forward_work_dir", lambda: forward)
    monkeypatch.setattr(runner.sv, "board", lambda: {"missing": [
        {"match_id": "sporttery-101", "kickoff": "2026-08-25T12:00:00+08:00"},
    ]})

    def fake_cli(args, timeout=3600):
        output = Path(args[args.index("--emit-input") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"matches": [
            {"mode": "market_only", "sporttery_meta": {"match_id": 101, "match_num": "001"}},
        ]}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    updates = []
    monkeypatch.setattr(runner, "_cli", fake_cli)
    monkeypatch.setattr(runner, "_record_one", lambda match, work: "recorded")
    monkeypatch.setattr(runner.db, "run_update", lambda run_id, **kw: updates.append(kw))

    runner.task_predict(32, "2026-08-25", ["sporttery-101", "sporttery-102"])

    assert updates[-1]["status"] == "error"
    assert updates[-1]["done"] == 1
    assert updates[-1]["total"] == 2
    assert runner.read_run_failures(32)["match_ids"] == ["sporttery-102"]


def test_llm_target_filter_never_adds_unrequested_matches():
    matches = [
        {"match_id": "sporttery-1", "kickoff_iso": "2099-01-01T00:00:00+08:00"},
        {"match_id": "sporttery-2", "kickoff_iso": "2099-01-01T00:00:00+08:00"},
    ]
    selected = runner.filter_llm_retry_matches(matches, ["sporttery-2"])
    assert [row["match_id"] for row in selected] == ["sporttery-2"]


def test_llm_retry_non_first_fixture_uses_isolated_evidence_and_scoped_input(tmp_path, monkeypatch):
    day = "2026-08-25"
    work = tmp_path / day
    work.mkdir(parents=True)
    fusion = [
        {"mode": "market_only", "kickoff": "2099-08-25T12:00:00+08:00", "home": "甲", "away": "乙",
         "sporttery_meta": {"match_id": 201, "match_num": "001"}},
        {"mode": "market_only", "kickoff": "2099-08-25T14:00:00+08:00", "home": "丙", "away": "丁",
         "sporttery_meta": {"match_id": 202, "match_num": "002"}},
    ]
    (work / "inputs_prematch.json").write_text(json.dumps({"matches": fusion}), encoding="utf-8")
    old_dir = work / "llm_evidence_run_76"
    old_dir.mkdir()
    old_first = old_dir / "evidence_001_甲_乙.md"
    old_first.write_text("initial-first", encoding="utf-8")
    old_second = old_dir / "evidence_002_丙_丁.md"
    old_second.write_text("initial-second", encoding="utf-8")

    captured = {}
    updates = []
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", tmp_path / "failures")
    monkeypatch.setattr(runner, "forward_work_dir", lambda: tmp_path)
    monkeypatch.setattr(runner, "_sales_day_prematch_matches", lambda selected_day: fusion)
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)

    def fake_late(input_path, selected_day, matches):
        captured["late_input"] = Path(input_path)
        captured["late_ids"] = [
            (m.get("sporttery_meta") or {}).get("match_id") or m.get("match_id")
            for m in json.loads(Path(input_path).read_text(encoding="utf-8"))["matches"]
        ]
        return {"attempted": len(matches), "status": "ok"}

    def fake_prepare(matches, evidence_dir):
        captured["evidence_dir"] = Path(evidence_dir)
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)
        (Path(evidence_dir) / "evidence_001_丙_丁.md").write_text("retry-second", encoding="utf-8")
        return [{"source": "light"}]

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["popen_args"] = args
            self.stdout = iter([
                "⚽ 第1/1场 [002] 丙 VS 丁 | 测试 | 2099-08-25 14:00\n",
                "  📊 综合方向: 主胜  (1.0/1.0票, 强度100%)\n",
            ])

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(runner, "auto_collect_late_info", fake_late)
    monkeypatch.setattr(runner, "attach_collected_evidence", lambda matches, selected_day: {
        "snapshots_attached": 0, "late_info_matches_merged": 0, "missing_snapshot_ids": [],
    })
    monkeypatch.setattr(runner, "auto_collect_prematch_evidence", lambda *args, **kwargs: {"attempted": 0})
    monkeypatch.setattr(runner, "prepare_llm_evidence", fake_prepare)
    monkeypatch.setattr(runner, "llm_repo", lambda: tmp_path)
    monkeypatch.setattr(runner.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(runner, "write_llm_jobs", lambda *args, **kwargs: 1)
    monkeypatch.setattr(runner, "build_deepseek_calibration_audit", lambda path: {"status": "ok", "eligible_settled_rows": 0})
    monkeypatch.setattr(runner.db, "run_update", lambda run_id, **kw: updates.append(kw))

    runner.task_llm(77, day, ["sporttery-202"])

    assert "evidence_dir" in captured, updates
    assert captured["evidence_dir"] == work / "llm_evidence_run_77"
    assert captured["late_input"] == work / "inputs_prematch_run_77.json"
    assert captured["late_ids"] == [202]
    assert captured["popen_args"][-1] == str(work / "llm_evidence_run_77")
    assert old_first.read_text(encoding="utf-8") == "initial-first"
    assert old_second.read_text(encoding="utf-8") == "initial-second"
    assert updates[-1]["status"] == "done"
    assert runner.read_run_failures(77) is None


def test_scoped_llm_unavailable_or_past_targets_stay_failed(tmp_path, monkeypatch):
    day = "2026-08-25"
    work = tmp_path / day
    work.mkdir(parents=True)
    (work / "inputs_prematch.json").write_text(json.dumps({"matches": [{
        "mode": "market_only", "kickoff": "2020-08-25T12:00:00+08:00", "home": "甲", "away": "乙",
        "sporttery_meta": {"match_id": 301, "match_num": "001"},
    }]}), encoding="utf-8")
    updates = []
    monkeypatch.setattr(runner, "RUN_FAILURES_DIR", tmp_path / "failures")
    monkeypatch.setattr(runner, "forward_work_dir", lambda: tmp_path)
    monkeypatch.setattr(runner.db, "run_update", lambda run_id, **kw: updates.append(kw))

    runner.task_llm(78, day, ["sporttery-301", "sporttery-302"])

    assert updates[-1]["status"] == "error"
    assert updates[-1]["done"] == 0
    assert updates[-1]["total"] == 2
    assert runner.read_run_failures(78)["match_ids"] == ["sporttery-301", "sporttery-302"]


def test_scoped_llm_gate_skip_is_not_false_success():
    matches = [{"match_id": "sporttery-401", "match_num": "001"}]
    parsed = {"rows": [], "skipped_indices": [1]}
    assert runner._handled_llm_match_ids(matches, parsed, include_skipped=False) == set()


def test_version_governance_is_read_only_and_does_not_require_release_module():
    response = TestClient(web.app).get("/api/version-governance")
    assert response.status_code == 200
    body = response.json()
    assert body["read_only_version_governance"] is True
    assert body["production_recommendations_enabled"] is False
    assert body["actions"] == []
    assert set(body["load"]) == {"identity", "progress", "release_lock"}
