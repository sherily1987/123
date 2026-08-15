# -*- coding: utf-8 -*-
"""project023 足球预测 Web 应用 — FastAPI 后端。

启动：python app.py  →  http://127.0.0.1:8765
仅绑定本机回环地址，单机单用户，无鉴权。
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
import db
import runner

db.init()

app = FastAPI(title="足球预测工作台", version="0.1.0")


class TaskReq(BaseModel):
    sales_day: str


class PredictReq(BaseModel):
    sales_day: str
    models: list[str] | None = None


@app.get("/api/health")
def health():
    return {"ok": True, "now": datetime.now(timezone.utc).isoformat()}


@app.get("/api/matches")
def matches(sales_day: str | None = None):
    rows = db.list_matches(sales_day)
    if not rows and sales_day:
        return {"sales_day": sales_day, "matches": [], "empty": True}
    # 合并预测
    preds = {}
    if sales_day:
        for p in db.list_predictions(sales_day):
            preds[p["match_num"]] = p
    out = []
    for r in rows:
        p = preds.get(r["match_num"])
        out.append({
            "match_num": r["match_num"], "league": r["league"], "home": r["home"], "away": r["away"],
            "kickoff": r["kickoff"], "odds_1x2": r["odds_1x2"], "quant_tier": r["quant_tier"],
            "status_name": r["status_name"],
            "prediction": {
                "direction": p["direction"], "strength": p["strength"], "single_pick": p["single_pick"],
                "sp_conf": p["sp_conf"], "sp_skip": p["sp_skip"], "score": p["score"],
                "ou25": p["ou25"], "evs": p["evs"], "evidence_gap": p["evidence_gap"],
                "collapse_flags": p["collapse_flags"],
            } if p else None,
        })
    return {"sales_day": sales_day, "matches": out}


@app.get("/api/predictions")
def predictions(sales_day: str):
    rows = db.list_predictions(sales_day)
    return {"sales_day": sales_day, "predictions": rows}


@app.get("/api/backtests")
def backtests(sales_day: str | None = None):
    rows = db.list_backtests(sales_day)
    n = len(rows)
    if not n:
        return {"sales_day": sales_day, "rows": [], "summary": None}
    hs = sum(r["hit_single"] for r in rows)
    hd = sum(r["hit_double"] for r in rows)
    sh = sum(r["score_hit"] for r in rows)
    return {"sales_day": sales_day, "rows": rows,
            "summary": {"n": n, "hit_single": hs, "hit_double": hd, "score_hit": sh}}


@app.post("/api/collect")
def collect(req: TaskReq):
    rid = runner.start_collect(req.sales_day)
    return {"run_id": rid, "status": "started"}


@app.post("/api/predict")
def predict(req: PredictReq):
    rid = runner.start_predict(req.sales_day, req.models)
    return {"run_id": rid, "status": "started"}


@app.post("/api/backtest")
def backtest(req: TaskReq):
    rid = runner.start_backtest(req.sales_day)
    return {"run_id": rid, "status": "started"}


@app.get("/api/run/{run_id}")
def run_status(run_id: int):
    r = db.run_get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return r


@app.get("/api/export/report")
def export_report(sales_day: str):
    """生成预测报告 markdown，返回下载。"""
    preds = db.list_predictions(sales_day)
    if not preds:
        raise HTTPException(404, "该日无预测记录")
    L = [f"# {sales_day} 开售预测报告（project023 Web 导出）", ""]
    n = len(preds)
    nh = sum(1 for p in preds if p["direction"] == "主胜")
    ng = sum(1 for p in preds if p["evidence_gap"])
    L += [f"- 场次 {n}，主胜 {nh}（{nh/n:.0%}），证据缺口 {ng} 场", ""]
    L += ["| 场次 | 比赛 | 联赛 | 方向 | 强度 | 下注建议 | 比分 | EV |", "|---|---|---|---|---|---|---|---|"]
    for p in sorted(preds, key=lambda x: x["match_num"]):
        evs = p["evs"] or {}
        best = max(evs.items(), key=lambda kv: abs(kv[1])) if evs else None
        evtxt = f"{best[0]} {best[1]*100:+.0f}%" if best else "-"
        L.append(f"| {p['match_num']} | {p.get('home','')} vs {p.get('away','')} | {p.get('league','')} "
                 f"| {p['direction']} | {p['strength']}% | {p['single_pick'] or '-'} | {p['score'] or '-'} | {evtxt} |")
    out = HERE / "data" / f"report_{sales_day}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return FileResponse(out, filename=f"{sales_day}_预测报告.md")


@app.get("/api/export/ppt")
def export_ppt(sales_day: str):
    """从 DB 生成 parsed 格式数据 → subprocess node 生成 PPT → 返回下载。"""
    import subprocess
    import sys
    preds = db.list_predictions(sales_day)
    if not preds:
        raise HTTPException(404, "该日无预测记录")
    rows = db.list_matches(sales_day)
    m_by_num = {r["match_num"]: r for r in rows}
    parsed = []
    for p in sorted(preds, key=lambda x: x["match_num"]):
        m = m_by_num.get(p["match_num"], {})
        parsed.append({
            "num": p["match_num"], "home": m.get("home"), "away": m.get("away"),
            "league": m.get("league"), "dir": p["direction"], "strength": p["strength"],
            "sp": p["single_pick"], "sp_skip": bool(p["sp_skip"]), "score": p["score"],
            "ou25": p["ou25"], "evs": p["evs"], "ev_reason": p["ev_reason"],
            "evidence_gap": bool(p["evidence_gap"]), "collapse_flags": p["collapse_flags"],
        })
    data_file = HERE / "data" / f"ppt_data_{sales_day}.json"
    data_file.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    out_file = HERE / "data" / f"预测PPT_{sales_day}.pptx"
    r = subprocess.run(["node", r"C:/Users/Administrator/football-llm-predictor/build_ppt_web.js",
                        "--parsed", str(data_file), "--out", str(out_file), "--title", sales_day],
                       capture_output=True, text=True, timeout=300, cwd=str(HERE))
    if r.returncode != 0 or not out_file.exists():
        raise HTTPException(500, f"PPT 生成失败: {r.stderr[-300:]}")
    return FileResponse(out_file, filename=f"LLM证据轨预测_{sales_day}销售日.pptx")


app.mount("/", StaticFiles(directory=str(HERE / "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
