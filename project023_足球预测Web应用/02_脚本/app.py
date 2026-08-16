# -*- coding: utf-8 -*-
"""project023 工作台：只读融合库看板；写操作走 fusion_cli market_only。"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
import db
import runner
import store_view as sv

db.init()
app = FastAPI(title="足球预测工作台", version="0.2.0")


class DayReq(BaseModel):
    kickoff_date: str | None = None
    sales_day: str | None = None

    def day(self) -> str | None:
        return self.kickoff_date or self.sales_day


@app.get("/api/health")
def health():
    root = sv.store_root()
    return {
        "ok": True,
        "now": datetime.now(timezone.utc).isoformat(),
        "store": str(root),
        "read_only_store": True,
        "manual_backtest": True,
        "quant_mode": "market_only",
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
        rows = [r for r in rows if (r.get("kickoff") or "").startswith(sales_day)]
    return {"sales_day": sales_day, "matches": rows, "summary": data["summary"]}


@app.get("/api/late-info")
def late_info():
    _, summary = sv.load_late_info()
    return summary


@app.post("/api/collect")
def collect(req: DayReq):
    day = req.day()
    if not day:
        raise HTTPException(400, "kickoff_date required")
    return {"run_id": runner.start_collect(day), "status": "started"}


@app.post("/api/predict")
def predict(req: DayReq):
    return {"run_id": runner.start_predict(req.day()), "status": "started"}


@app.post("/api/settle")
def settle(req: DayReq):
    return {"run_id": runner.start_settle(req.day()), "status": "started"}


@app.post("/api/backtest")
def backtest(req: DayReq):
    """手动结算。没有自动回测任务。"""
    return settle(req)


@app.get("/api/run/{run_id}")
def run_status(run_id: int):
    r = db.run_get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return r


@app.get("/api/job")
def job(match_id: str):
    import sys
    scripts = HERE.parents[1] / "project018_技能工作区整合" / "02_脚本" / "skill" / "football-quant-fusion" / "scripts"
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
                f"{pcts} | {r.get('bucket')} | {llm.get('direction') or '-'} |"
            )
        L.append("")
    out = HERE / "data" / "board_report.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return FileResponse(out, filename="体彩看板.md")


app.mount("/", StaticFiles(directory=str(HERE / "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
