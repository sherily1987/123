# -*- coding: utf-8 -*-
"""project023 工作台：只读融合库看板；写操作走 fusion_cli market_only。"""
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
import db
import daily_strategy_view as dsv
import importlib.util
import inspect
import runner
import store_view as sv
from workbench_runtime import BUILD_IDENTITY, FUSION_SCRIPTS

@asynccontextmanager
async def workbench_lifespan(_app):
    db.init()
    db.recover_orphaned_runs()
    yield


app = FastAPI(title="足球预测工作台", version="0.3.0", lifespan=workbench_lifespan)


@app.middleware("http")
async def no_store_workbench(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


class DayReq(BaseModel):
    kickoff_date: str | None = None
    sales_day: str | None = None

    def day(self) -> str | None:
        return self.sales_day or self.kickoff_date


def validated_day(req: DayReq, *, required: bool = False) -> str | None:
    if req.sales_day and req.kickoff_date and req.sales_day != req.kickoff_date:
        raise HTTPException(400, "sales_day and kickoff_date conflict; sales_day is authoritative")
    day = req.day()
    if required and not day:
        raise HTTPException(400, "sales_day or kickoff_date required")
    if not runner.valid_sales_day(day):
        raise HTTPException(400, "sales_day or kickoff_date must be YYYY-MM-DD")
    return day


def start_run(start, *args, **kwargs) -> int:
    """Translate the storage-level same-type exclusion into an honest API 409."""
    try:
        return start(*args, **kwargs)
    except db.RunAlreadyActive as exc:
        active = exc.active_run
        raise HTTPException(409, {
            "code": "run_type_running",
            "run_type": active.get("run_type"),
            "run_id": active.get("id"),
            "message": "同类任务已在运行",
        }) from exc


@app.get("/api/health")
def health():
    root = sv.store_root()
    copy_status = None
    try:
        import sys
        scripts = FUSION_SCRIPTS
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from runtime_paths import core_copy_status
        copy_status = core_copy_status()
    except Exception as exc:
        copy_status = {"status": "UNAVAILABLE", "error": str(exc)}
    return {
        "ok": True,
        "now": datetime.now(timezone.utc).isoformat(),
        "store": str(root),
        "read_only_store": True,
        "manual_backtest": True,
        "quant_mode": "market_only",
        "llm_track": True,
        "daily_strategy": "budgeted_action",
        "production_recommendations_enabled": False,
        "core_copy_status": copy_status,
    }


@app.get("/api/board")
def board():
    try:
        return sv.board()
    except Exception as exc:
        raise HTTPException(500, f"看板失败: {exc}") from exc


@app.get("/api/matches")
def matches(sales_day: str | None = None):
    """兼容旧前端：转成看板子集。"""
    data = sv.board()
    rows = data["matches"]
    if sales_day:
        rows = [r for r in rows if r.get("sales_day") == sales_day]
    return {"sales_day": sales_day, "matches": rows, "summary": data["summary"]}


@app.get("/api/late-info")
def late_info():
    _, summary = sv.load_late_info()
    return summary


@app.get("/api/daily-strategy")
def daily_strategy_api(day: str | None = None):
    try:
        kwargs = {"persist": True} if "persist" in inspect.signature(dsv.daily_strategy).parameters else {}
        return dsv.daily_strategy(day, **kwargs)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"每日策略生成失败: {exc}") from exc


@app.post("/api/daily-strategy/recommend")
def recommend_daily_strategy_api():
    """Generate against the current on-sale pool, which may kick off tomorrow."""
    try:
        day = dsv.current_sale_day()
        return dsv.daily_strategy(day, persist=True)
    except Exception as exc:
        raise HTTPException(500, f"娱乐策略推荐失败: {exc}") from exc


@app.get("/api/version-progress")
def version_progress():
    """Expose version/cohort progress without silently merging stores."""
    try:
        import sys
        scripts = FUSION_SCRIPTS
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from version_progress import build_report
        return build_report(sv.store_root() / "backtest")
    except Exception as exc:
        raise HTTPException(500, f"版本进度读取失败: {exc}") from exc


@app.get("/api/ui-contract")
def ui_contract():
    return {
        "version": "b3",
        "pages": ["overview", "strategy", "backtest", "leagues", "evidence", "tasks", "versions", "export"],
        "task_actions": ["collect", "predict", "llm", "settle", "backtest"],
        "read_only_version_governance": True,
        "build_identity": BUILD_IDENTITY,
        "process_id": os.getpid(),
    }


@app.get("/api/version-governance")
def version_governance():
    """Read current identity, progress, and release lock without mutation APIs."""
    scripts = FUSION_SCRIPTS
    config = scripts.parent / "config"
    load = {"identity": "unavailable", "progress": "unavailable", "release_lock": "unavailable"}
    identity = {}
    progress = {}
    release_lock = {"status": "UNAVAILABLE"}
    try:
        import sys
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from fusion_predict_core import build_identity
        identity = build_identity()
        load["identity"] = "ok"
    except Exception as exc:
        load["identity"] = f"error: {exc}"
    try:
        from version_progress import build_report
        progress = build_report(sv.store_root() / "backtest")
        load["progress"] = "ok"
    except Exception as exc:
        load["progress"] = f"error: {exc}"
    lock_path = config / "release_lock.json"
    try:
        locked = json.loads(lock_path.read_text(encoding="utf-8-sig"))
        if not isinstance(locked, dict):
            raise ValueError("release_lock must be an object")
        current_version = str(identity.get("model_version") or "")
        current_signature = str(identity.get("probability_signature") or "")
        locked_version = str(locked.get("model_version") or "")
        locked_signature = str(locked.get("probability_signature") or "")
        comparable = bool(current_version and current_signature)
        status = (
            "MATCH" if comparable and current_version == locked_version and current_signature == locked_signature
            else "MISMATCH" if comparable
            else "LOADED"
        )
        release_lock = {
            "status": status,
            "model_version": locked_version or None,
            "probability_signature": locked_signature or None,
            "locked_at": locked.get("locked_at"),
        }
        load["release_lock"] = "ok"
    except FileNotFoundError:
        release_lock = {"status": "MISSING", "model_version": None,
                        "probability_signature": None, "locked_at": None}
        load["release_lock"] = "missing"
    except Exception as exc:
        release_lock = {"status": "INVALID", "model_version": None,
                        "probability_signature": None, "locked_at": None}
        load["release_lock"] = f"error: {exc}"
    release = {
        "current_model_version": identity.get("model_version") or progress.get("current_model_version"),
        "probability_signature": identity.get("probability_signature") or progress.get("current_probability_signature"),
        "release_lock_status": release_lock.get("status"),
        "locked_model_version": release_lock.get("model_version"),
        "locked_probability_signature": release_lock.get("probability_signature"),
        "locked_at": release_lock.get("locked_at"),
    }
    return {
        "read_only_version_governance": True,
        "actions": [],
        "load": load,
        "identity": identity,
        "release_lock": release_lock,
        "release": release,
        "current": progress.get("current") or {},
        "signature_drift": progress.get("signature_drift") or [],
        "counted_as_current_aliases": progress.get("counted_as_current_aliases") or [],
        "production_recommendations_enabled": False,
    }


@app.get("/api/daily-strategy/backtest")
def daily_strategy_backtest_api(from_day: str | None = None, to_day: str | None = None):
    try:
        script = sv.FUSION_SCRIPTS / "daily_strategy_backtest.py"
        spec = importlib.util.spec_from_file_location("daily_strategy_backtest", script)
        if not spec or not spec.loader:
            raise RuntimeError("daily strategy backtest module unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plans = module.load_plans(sv.store_root() / "daily_strategy_plans", from_day, to_day)
        return module.build_report(plans, sv.store_root() / "backtest" / "results")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"策略回测失败: {exc}") from exc


@app.get("/api/history")
def history(day: str | None = None, full: bool = False):
    try:
        if day:
            return sv.history_day(day)
        if full:
            return sv.history_full()
        return sv.history_index()
    except Exception as exc:
        raise HTTPException(500, f"历史失败: {exc}") from exc


@app.post("/api/collect")
def collect(req: DayReq):
    day = validated_day(req, required=True)
    return {"run_id": start_run(runner.start_collect, day), "status": "started"}


@app.post("/api/predict")
def predict(req: DayReq):
    return {"run_id": start_run(runner.start_predict, validated_day(req)), "status": "started"}


@app.post("/api/settle")
def settle(req: DayReq):
    return {"run_id": start_run(runner.start_settle, validated_day(req)), "status": "started"}


@app.post("/api/llm")
def llm(req: DayReq):
    return {"run_id": start_run(runner.start_llm, validated_day(req)), "status": "started"}


@app.post("/api/backtest")
def backtest():
    return {"run_id": start_run(runner.start_backtest), "status": "started"}


@app.get("/api/match/{match_id}")
def match_detail(match_id: str):
    card = sv.match_card(match_id)
    if not card:
        raise HTTPException(404, "match not found")
    return card


@app.get("/api/run/{run_id}")
def run_status(run_id: int):
    r = db.run_get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    result = dict(r)
    failures = runner.read_run_failures(run_id)
    result["failed"] = len(failures["match_ids"]) if failures else 0
    return result


@app.get("/api/runs/active")
def active_runs():
    return {"runs": db.run_active()}


@app.post("/api/run/{run_id}/retry-failed")
def retry_failed(run_id: int):
    """Retry only IDs captured by a completed predict/LLM run sidecar."""
    run = db.run_get(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    run_type = run.get("run_type")
    if run_type not in runner.ITEMIZED_RUN_TYPES:
        raise HTTPException(409, f"{run_type or 'unknown'} 不支持逐项重试")
    if run.get("status") not in {"done", "error"}:
        raise HTTPException(409, "运行尚未结束，不能重试失败项")
    failures = runner.read_run_failures(run_id)
    if not failures or failures.get("run_type") != run_type:
        raise HTTPException(409, "没有可验证的失败清单，拒绝整批重跑")
    match_ids = failures["match_ids"]
    if not match_ids:
        raise HTTPException(409, "失败清单为空，拒绝整批重跑")
    day = failures.get("sales_day")
    if run_type == "predict":
        retry_id = start_run(runner.start_predict, day, match_ids=match_ids)
    else:
        retry_id = start_run(runner.start_llm, day, match_ids=match_ids)
    return {
        "run_id": retry_id,
        "status": "started",
        "retry_of": run_id,
        "run_type": run_type,
        "match_ids": match_ids,
    }


@app.get("/api/job")
def job(match_id: str):
    import sys
    scripts = FUSION_SCRIPTS
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from job_ticket import jobs_root, load_job

    mid = sv.sporttery_id(match_id)
    disk = load_job(jobs_root(), mid)
    if not disk:
        raise HTTPException(404, "job not found")
    return disk


@app.get("/api/export/report")
def export_report():
    data = sv.board()
    L = [
        f"# 体彩看板 {data['as_of'][:16]}",
        "",
        f"事实源：`{data['store']}`。量化 = 正式登记 market_only。LLM 只列证据方向。回测手动。",
        "",
        f"- 已开售 {data['summary']['on_sale']}，未开球有盘 {data['summary']['has_odds']}，"
        f"已预测 {data['summary']['predicted']}，未预测 {data['summary']['missing_pred']}",
        "",
    ]
    for g in data.get("by_league") or []:
        L += [
            f"## {g['league']}（{g['n']} 场，已登记 {g['predicted']}）",
            "",
            "| 场次 | 开球 | 比赛 | 盘 | 量化主/平/客 | 状态 | LLM证据 |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in g["matches"]:
            q = r.get("quant") or {}
            pct = q.get("final_1x2_pct")
            pcts = "/".join(f"{x:.1f}" for x in pct) if pct else "-"
            llm = r.get("llm") or {}
            L.append(
                f"| {r.get('match_num')} | {(r.get('kickoff') or '')[5:16]} | "
                f"{r.get('home')} vs {r.get('away')} | "
                f"{'/'.join(str(x) for x in (r.get('odds') or [])) or '无HAD'} | "
                f"{pcts} | {r.get('bucket')} | {llm.get('direction') or ('已采集' if llm else '未采集')} |"
            )
        L.append("")
    out = HERE / "data" / "board_report.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return FileResponse(out, filename="体彩看板.md")


app.mount("/", StaticFiles(directory=str(HERE / "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
