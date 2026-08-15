# -*- coding: utf-8 -*-
"""project023 — 流水线调度：采集 → 轻量证据 → LLM 预测(subprocess) → 解析 → 入库。

所有重活通过 subprocess 调现有 CLI（单一事实源），本模块只负责编排与进度上报。
后台任务用线程跑，进度写 db.runs 表，前端轮询。
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 2026-08-16：LLM 工程已从 C:/Users/Administrator/football-llm-predictor 迁入仓库。
# FOOTBALL_LLM_ROOT 可覆盖（例如临时指回 C 盘旧目录做对比）。
LLM_DIR = Path(os.environ.get("FOOTBALL_LLM_ROOT") or (
    HERE.parents[1] / "project018_技能工作区整合" / "02_脚本" / "llm" / "football-llm-predictor"))
PARSE_SCRIPT = LLM_DIR / "parse_predictions.py"
PREDICT_SCRIPT = LLM_DIR / "predict.py"
MODELS = ["zhipu/glm-4-flash", "deepseek/deepseek-chat", "ark/doubao-seed-evolving"]

import db
import collector
import light_evidence


def _no_proxy_env():
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(k, None)
    return env


def _run(cmd: list, timeout: int = 7200):
    """subprocess 跑命令，返回 (rc, stdout_tail, stderr_tail)。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_no_proxy_env(), cwd=str(LLM_DIR))
        return r.returncode, r.stdout[-800:] if r.stdout else "", r.stderr[-800:] if r.stderr else ""
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def task_collect(sales_day: str, run_id: int):
    try:
        db.run_update(run_id, message="拉取体彩列表…")
        res = collector.collect(sales_day)
        db.upsert_matches(sales_day, res["matches"])
        db.run_update(run_id, done=res["n"], message=f"采集完成 {res['n']} 场", status="done")
    except Exception as e:
        db.run_update(run_id, message=f"采集失败: {e}", status="error")


def task_predict(sales_day: str, run_id: int, models=None):
    try:
        models = models or MODELS
        raw_path = LLM_DIR / "data" / f"raw_{sales_day}.json"
        if not raw_path.exists():
            db.run_update(run_id, message="未找到 raw 数据，请先采集", status="error")
            return
        ev_dir = LLM_DIR / "data" / f"evidence_{sales_day}"
        # 1) 轻量证据（不覆盖已存在的深度证据文件）
        db.run_update(run_id, message="生成轻量证据…")
        ev_dir.mkdir(parents=True, exist_ok=True)
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        tiers = collector.league_tiers()
        existing = {p.name for p in ev_dir.glob("evidence_*.md")} if ev_dir.exists() else set()
        for i, m in enumerate(raw["matches"], 1):
            fname = f"evidence_{i:03d}_{m.get('home', '')}_{m.get('away', '')}.md"
            if fname in existing:
                continue  # 已有证据（可能是深度证据），不覆盖
            tier = collector.quant_annotation(m.get("league", ""), tiers)
            (ev_dir / fname).write_text(light_evidence.build_one(i, m, tier), encoding="utf-8")
        # 2) 跑 predict.py
        n = len(raw["matches"])
        db.run_update(run_id, total=n, message=f"开始预测 {n} 场 × {len(models)} 模型…")
        out_txt = LLM_DIR / "data" / f"predictions_web_{sales_day}.txt"
        cmd = [sys.executable, str(PREDICT_SCRIPT), "--input", str(raw_path),
               "--evidence-dir", str(ev_dir), "--models"] + list(models)
        with open(out_txt, "w", encoding="utf-8") as f:
            proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT,
                                    env=_no_proxy_env(), cwd=str(LLM_DIR), text=True)
            # 进度轮询：统计输出里完成的场次数
            last = 0
            while proc.poll() is None:
                time.sleep(8)
                if out_txt.exists():
                    done = out_txt.read_text(encoding="utf-8", errors="ignore").count("⚽ 第")
                    done = min(done, n)
                    if done != last:
                        last = done
                        db.run_update(run_id, done=done, message=f"预测中 {done}/{n} 场…")
            rc = proc.returncode
        if rc != 0:
            db.run_update(run_id, message="predict.py 退出码非 0，见日志", status="error")
            return
        # 3) 解析
        db.run_update(run_id, done=n, message="解析结果…")
        rc, out, err = _run([sys.executable, str(PARSE_SCRIPT), str(out_txt),
                             "--raw", str(raw_path), "--start-index", "1",
                             "--out", str(LLM_DIR / "data" / f"parsed_web_{sales_day}.json")])
        if rc != 0:
            db.run_update(run_id, message=f"解析失败: {err[-200:]}", status="error")
            return
        parsed = json.loads((LLM_DIR / "data" / f"parsed_web_{sales_day}.json").read_text(encoding="utf-8"))
        # 补 quant_tier 到 parsed（展示用）
        m_by_num = {m["match_num"]: m for m in raw["matches"]}
        for p in parsed:
            m = m_by_num.get(p["num"], {})
            p["quant_tier"] = collector.quant_annotation(m.get("league", ""), tiers)
            p["league"] = p.get("league") or m.get("league", "")
        db.upsert_predictions(sales_day, parsed)
        db.run_update(run_id, done=n, message=f"预测完成 {len(parsed)} 场", status="done")
    except Exception as e:
        db.run_update(run_id, message=f"预测失败: {e}", status="error")


def task_backtest(sales_day: str, run_id: int):
    """采赛果 + 回测：体彩 result 接口拿 sectionsNo999 比分，对比预测方向。"""
    try:
        import re
        import urllib.parse
        import urllib.request
        preds = {p["match_num"]: p for p in db.list_predictions(sales_day)}
        if not preds:
            db.run_update(run_id, message="该日无预测记录", status="error")
            return
        UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14)",
              "Referer": "https://m.sporttery.cn/mjc/zqsj/?tab=concern"}
        rows = []
        settled = []
        for d in (sales_day, (date.fromisoformat(sales_day) + date.resolution).isoformat()):
            url = ("https://webapi.sporttery.cn/gateway/uniform/fb/getMatchDataPageListV1.qry?"
                   + urllib.parse.urlencode({"method": "result", "matchDate": d}))
            try:
                data = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))
            except Exception:
                continue
            for day in data.get("value", {}).get("matchInfoList", []):
                for r in day.get("subMatchList", []):
                    num = r.get("matchNumStr") or ""
                    if num not in preds:
                        continue
                    s999 = r.get("sectionsNo999") or ""
                    m = re.match(r"(\d+):(\d+)", str(s999))
                    if not m:
                        continue
                    hg, ag = int(m.group(1)), int(m.group(2))
                    actual = "主胜" if hg > ag else ("客胜" if hg < ag else "平局")
                    p = preds[num]
                    dir_ = p["direction"]
                    sp = p["single_pick"] or ""
                    hit1 = 1 if dir_ == actual else 0
                    hit2 = 1 if (dir_ == actual or sp == actual or actual in sp) else 0
                    sh = 1 if (p["score"] or "") == f"{hg}-{ag}" else 0
                    settled.append({
                        "match_num": num, "score_90": f"{hg}-{ag}", "actual_direction": actual,
                        "hit_single": hit1, "hit_double": hit2, "score_hit": sh,
                    })
        if not settled:
            db.run_update(run_id, message="未取到赛果（场次可能未结束）", status="error")
            return
        db.upsert_backtests(sales_day, settled)
        n = len(settled)
        hs = sum(r["hit_single"] for r in settled)
        hd = sum(r["hit_double"] for r in settled)
        sh = sum(r["score_hit"] for r in settled)
        db.run_update(run_id, done=n, status="done",
                      message=f"回测完成：方向 {hs}/{n}={hs/n:.0%}，含双选 {hd}/{n}，比分 {sh}/{n}")
    except Exception as e:
        db.run_update(run_id, message=f"回测失败: {e}", status="error")


def start_collect(sales_day: str) -> int:
    rid = db.run_start("collect", message="启动采集")
    threading.Thread(target=task_collect, args=(sales_day, rid), daemon=True).start()
    return rid


def start_predict(sales_day: str, models=None) -> int:
    rid = db.run_start("predict", message="启动预测")
    threading.Thread(target=task_predict, args=(sales_day, rid, models), daemon=True).start()
    return rid


def start_backtest(sales_day: str) -> int:
    rid = db.run_start("backtest", message="启动回测")
    threading.Thread(target=task_backtest, args=(sales_day, rid), daemon=True).start()
    return rid
