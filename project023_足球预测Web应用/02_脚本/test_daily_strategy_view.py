from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


CST = timezone(timedelta(hours=8))


def _job(match_id: int) -> dict:
    return {
        "identity": {
            "match_id": f"sporttery-{match_id}",
            "match_num": f"周日{match_id:03d}",
            "home": f"主队{match_id}",
            "away": f"客队{match_id}",
            "competition": "测试联赛",
            "kickoff": "2026-08-23T18:00:00+08:00",
        },
        "input": {
            "odds": [1.40, 4.20, 6.00],
            "ttg": {"odds": [10.0, 4.5, 3.2, 3.6, 6.5, 12.0, 24.0, 40.0]},
            "hafu": {"odds": [1.95, 12.0, 35.0, 5.0, 7.0, 22.0, 40.0, 16.0, 9.0]},
            "crs": {"1-0": 5.5, "2-0": 6.5, "1-1": 7.0},
        },
        "outputs": [{
            "track": "quant",
            "evidence_audit": {"evidence_gap": False, "evidence_status": "OK", "evidence_gap_reasons": []},
            "mode": "market_only",
            "final_1x2_pct": [70.0, 20.0, 10.0],
            "market_forecasts": {
                "TTG": {"model_prob_pct": [5, 15, 30, 25, 15, 7, 2, 1]},
                "HAFU": {"model_prob_pct": [40, 8, 2, 15, 12, 5, 4, 5, 9]},
                "CRS": {"top_scores": [{"score": "1-0", "prob_pct": 18}]},
            },
        }],
    }


def _write_jobs(root: Path, day: str, count: int = 8) -> None:
    folder = root / "jobs" / day
    folder.mkdir(parents=True)
    for match_id in range(1, count + 1):
        (folder / f"sporttery-{match_id}.json").write_text(
            json.dumps(_job(match_id), ensure_ascii=False), encoding="utf-8"
        )


def test_daily_strategy_view_builds_user_authorized_100_yuan_plan(tmp_path: Path):
    """Catches the Web API dropping the fixed-budget strategy or relabeling it as edge."""
    import daily_strategy_view as view

    _write_jobs(tmp_path, "2026-08-23")
    got = view.daily_strategy(
        "2026-08-23",
        root=tmp_path,
        now=datetime(2026, 8, 23, 8, 0, tzinfo=CST),
    )

    assert got["selected_day"] == "2026-08-23"
    assert got["day"] == "2026-08-23"
    assert got["source_job_count"] == 8
    assert got["execution_mode"] == "budgeted_action"
    assert got["budget"]["allocated_amount"] == 100.0
    assert len(got["single_purchase_recommendations"]) == 7
    assert {row["legs_count"] for row in got["combo_purchase_recommendations"]} == {2, 3}
    assert got["risk_disclosure"]["edge_verified"] is False
    assert got["display"]["strategy_type"] == "固定娱乐预算（放宽门禁）"
    assert got["display"]["edge_label"] == "未验证正EV"


def test_daily_strategy_view_exposes_model_isolated_deepseek_calibration(tmp_path: Path):
    import daily_strategy_view as view

    _write_jobs(tmp_path, "2026-08-23", count=1)
    audit_dir = tmp_path / "forward" / "2026-08-23"
    audit_dir.mkdir(parents=True)
    (audit_dir / "deepseek_calibration_audit.json").write_text(json.dumps({
        "model": "deepseek/deepseek-v4-flash", "llm_rows": 12, "eligible_settled_rows": 9,
        "metrics": {"brier": None},
    }), encoding="utf-8")
    got = view.daily_strategy("2026-08-23", root=tmp_path,
                              now=datetime(2026, 8, 23, 8, 0, tzinfo=CST))
    assert got["llm_calibration"]["model"] == "deepseek/deepseek-v4-flash"
    assert got["llm_calibration"]["eligible_settled_rows"] == 9
    assert got["llm_calibration"]["ready_for_review"] is False
    assert got["llm_calibration"]["production_change_allowed"] is False
    assert "独立校准样本" in got["display"]["llm_calibration_warning"]


def test_daily_strategy_view_missing_jobs_preserves_budget(tmp_path: Path):
    """Catches a no-data day being turned into made-up recommendations."""
    import daily_strategy_view as view

    got = view.daily_strategy(
        "2026-08-24",
        root=tmp_path,
        now=datetime(2026, 8, 24, 8, 0, tzinfo=CST),
    )

    assert got["source_job_count"] == 0
    assert got["decision"]["action"] == "preserve_bankroll"
    assert got["budget"]["allocated_amount"] == 0.0
    assert got["single_purchase_recommendations"] == []


def test_daily_strategy_view_attaches_forward_pipeline_sidecar(tmp_path: Path):
    """The pipeline's forward snapshot must reach the planner without rewriting jobs."""
    import daily_strategy_view as view

    _write_jobs(tmp_path, "2026-08-23", count=1)
    sidecar_dir = tmp_path / "forward" / "2026-08-23" / "evidence_snapshots"
    sidecar_dir.mkdir(parents=True)
    (sidecar_dir / "sporttery-1.json").write_text(
        json.dumps({
            "match_id": "sporttery-1",
            "evidence_audit": {
                "evidence_gap": False,
                "evidence_status": "OK",
                "evidence_gap_reasons": [],
                "entries": {"team_stats": {"status": "VALID"}},
            },
        }),
        encoding="utf-8",
    )

    jobs = view._attach_evidence_sidecars(
        view._load_jobs(tmp_path / "jobs" / "2026-08-23"), tmp_path, "2026-08-23"
    )
    assert jobs[0]["evidence_audit"]["evidence_status"] == "OK"
    assert jobs[0]["evidence_snapshot_ref"].endswith("sporttery-1.json")


def test_daily_strategy_view_merges_pre_kickoff_late_info(tmp_path: Path):
    import daily_strategy_view as view

    _write_jobs(tmp_path, "2026-08-23", count=1)
    sidecar_dir = tmp_path / "forward" / "2026-08-23" / "evidence_snapshots"
    sidecar_dir.mkdir(parents=True)
    (sidecar_dir / "sporttery-1.json").write_text(json.dumps({
        "match_id": "sporttery-1",
        "evidence_audit": {"evidence_gap": True, "evidence_status": "GAP",
                            "missing_fields": ["injury"],
                            "entries": {"injury": {"status": "UNAVAILABLE"}}},
    }), encoding="utf-8")
    late = tmp_path / "late_info"
    late.mkdir()
    (late / "events.jsonl").write_text(json.dumps({
        "match_id": 1, "kind": "injury", "status": "VALID",
        "kickoff": "2026-08-23T18:00:00+08:00",
        "collected_at": "2026-08-23T10:00:00+08:00",
        "absence": {"home": {"count": 1}},
        "gate": {"minutes_to_kickoff": 480},
    }) + "\n", encoding="utf-8")

    jobs = view._attach_evidence_sidecars(
        view._load_jobs(tmp_path / "jobs" / "2026-08-23"), tmp_path, "2026-08-23"
    )
    assert jobs[0]["evidence_audit"]["entries"]["injury"]["status"] == "VALID"
    assert jobs[0]["evidence_audit"]["late_info_merge_audit"]["fields_merged"] == ["injury"]


def test_daily_strategy_view_rejects_non_date_path(tmp_path: Path):
    """Catches path traversal through the day query parameter."""
    import daily_strategy_view as view

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        view.daily_strategy("../2026-08-23", root=tmp_path)


def test_daily_strategy_api_exposes_the_selected_day(monkeypatch):
    """Catches the workbench API route being absent or ignoring the requested day."""
    import app as web

    seen = []

    def fake(day):
        seen.append(day)
        return {"selected_day": day, "budget": {"allocated_amount": 100.0}}

    monkeypatch.setattr(web.dsv, "daily_strategy", fake)
    got = web.daily_strategy_api("2026-08-23")

    assert seen == ["2026-08-23"]
    assert got["selected_day"] == "2026-08-23"
    assert got["budget"]["allocated_amount"] == 100.0


def test_frontend_renderer_shows_budget_markets_combos_and_edge_boundary():
    """Catches the Web card hiding stake details or the unverified-edge warning."""
    renderer = Path(__file__).resolve().parent / "static" / "daily_strategy.js"
    sample = {
        "selected_day": "2026-08-23",
        "display": {
            "strategy_type": "固定娱乐预算",
            "edge_label": "未验证正EV",
            "warning": "不是生产胆项",
            "decision_time": "2026-08-23T10:00:00+08:00",
        },
        "budget": {"daily_budget_amount": 100, "allocated_amount": 100, "preserved_amount": 0},
        "market_audit": [
            {"market": "TTG", "model_calibration_status": "UNFITTED"},
            {"market": "HAD", "independent_calibration_status": "VALID"},
        ],
            "llm_calibration": {
                "model": "deepseek/deepseek-v4-flash",
                "llm_rows": 12,
                "eligible_settled_rows": 9,
            "minimum_review_rows": 100,
            "ready_for_review": False,
        },
        "single_purchase_recommendations": [{
            "market": "TTG", "match_num": "周日003", "home": "甲", "away": "乙",
            "selection": "2球", "odds": 3.2, "stake_amount": 10,
        }],
        "combo_purchase_recommendations": [{
            "legs_count": 2, "stake_amount": 16, "combined_odds": 1.729,
            "legs": [
                {"match_num": "周日009", "home": "丙", "away": "丁", "selection": "胜"},
                {"match_num": "周日013", "home": "戊", "away": "己", "selection": "胜"},
            ],
        }],
    }
    script = (
        f"const r=require({json.dumps(str(renderer))});"
        f"process.stdout.write(r.formatDailyStrategyHtml({json.dumps(sample, ensure_ascii=False)}));"
    )

    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")

    assert run.returncode == 0, run.stderr
    assert "今日100元娱乐策略" in run.stdout
    assert "固定娱乐预算" in run.stdout
    assert "未验证正EV" in run.stdout
    assert "进球数" in run.stdout
    assert "市场校准状态" in run.stdout and "UNFITTED" in run.stdout and "VALID" in run.stdout
    assert "DeepSeek V4 Flash 校准" in run.stdout and "已登记 12 场" in run.stdout and "已结算 9/100" in run.stdout
    assert "周日003" in run.stdout and "2球" in run.stdout and "10元" in run.stdout
    assert "2串1" in run.stdout and "16元" in run.stdout
    assert "不是生产胆项" in run.stdout


@pytest.mark.parametrize("path", ["/", "/daily_strategy.js"])
def test_workbench_static_responses_disable_browser_cache(path):
    """Catches an already-open tab reusing the pre-strategy workbench shell."""
    from fastapi.testclient import TestClient
    import app as web

    response = TestClient(web.app).get(path)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
