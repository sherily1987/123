# -*- coding: utf-8 -*-
"""工作台调度：写操作只走 fusion_cli，登记 market_only。SQLite 只记任务进度。"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
FUSION_SCRIPTS = (
    HERE.parents[1] / "project018_技能工作区整合" / "02_脚本" / "skill" / "football-quant-fusion" / "scripts"
)
if str(FUSION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(FUSION_SCRIPTS))
from runtime import resolve_python  # noqa: E402
from runtime_paths import backtest_store, forward_work_dir  # noqa: E402

import db
import store_view as sv

PY = resolve_python()
CLI = FUSION_SCRIPTS / "fusion_cli.py"
CST = timezone(timedelta(hours=8))


def _no_proxy_env():
    import os
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(k, None)
    return env


def _cli(args: list, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(CLI), *args],
        capture_output=True, text=True, timeout=timeout,
        env=_no_proxy_env(), cwd=str(FUSION_SCRIPTS),
        encoding="utf-8", errors="replace",
    )


def task_collect(kickoff_date: str, run_id: int):
    try:
        work = forward_work_dir() / kickoff_date
        work.mkdir(parents=True, exist_ok=True)
        db.run_update(run_id, message=f"采集 {kickoff_date} 开球场次…")
        r = _cli([
            "collect", "--kickoff-date", kickoff_date,
            "--output", str(work / "sporttery_prematch.json"),
            "--emit-input", str(work / "inputs_prematch.json"),
        ], timeout=900)
        if r.returncode != 0:
            db.run_update(run_id, status="error", message=(r.stderr or r.stdout)[-300:])
            return
        n = 0
        inp = work / "inputs_prematch.json"
        if inp.exists():
            n = len(json.loads(inp.read_text(encoding="utf-8")).get("matches") or [])
        db.run_update(run_id, done=n, total=n, status="done",
                      message=f"采集完成，可登记 {n} 场（写入 fusion forward，未改生产概率）")
    except Exception as e:
        db.run_update(run_id, status="error", message=f"采集失败: {e}")


def _record_one(match: dict, work: Path) -> str:
    num = (match.get("sporttery_meta") or {}).get("match_num") or "unknown"
    ip = work / f"{num}_input.json"
    op = work / f"{num}_output.json"
    ip.write_text(json.dumps(match, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    r = _cli(["record", "--input", str(ip), "--output", str(op), "--snapshot", "prematch"], timeout=180)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-240:])
    payload = json.loads(r.stdout)
    if payload.get("status") not in ("recorded", "skipped_duplicate_snapshot"):
        raise RuntimeError(payload.get("status") or "record failed")
    return payload.get("status")


def task_predict(run_id: int, kickoff_date: str | None = None):
    """只登记看板里「有盘未预测」的场次，mode 固定 market_only。"""
    try:
        board = sv.board()
        missing = board.get("missing") or []
        if kickoff_date:
            missing = [m for m in missing if (m.get("kickoff") or "").startswith(kickoff_date)]
        if not missing:
            db.run_update(run_id, status="done", message="没有待补登记的有盘场次")
            return
        days = sorted({(m.get("kickoff") or "")[:10] for m in missing if m.get("kickoff")})
        want = {m["match_id"] for m in missing}
        db.run_update(run_id, total=len(want), message=f"补登记 {len(want)} 场 market_only…")
        done = 0
        notes = []
        for day in days:
            work = forward_work_dir() / day
            work.mkdir(parents=True, exist_ok=True)
            r = _cli([
                "collect", "--kickoff-date", day,
                "--output", str(work / "sporttery_prematch.json"),
                "--emit-input", str(work / "inputs_prematch.json"),
            ], timeout=900)
            if r.returncode != 0:
                notes.append(f"{day} 采集失败")
                continue
            inp = work / "inputs_prematch.json"
            if not inp.exists():
                continue
            batch = json.loads(inp.read_text(encoding="utf-8")).get("matches") or []
            for match in batch:
                if match.get("mode") != "market_only":
                    continue
                mid = sv.sporttery_id((match.get("sporttery_meta") or {}).get("match_id"))
                if mid not in want:
                    continue
                st = _record_one(match, work)
                done += 1
                notes.append(f"{mid} {st}")
                db.run_update(run_id, done=done, message=f"已登记 {done}/{len(want)}")
        db.run_update(run_id, done=done, status="done",
                      message=f"补登记完成 {done} 场（market_only）")
    except Exception as e:
        db.run_update(run_id, status="error", message=f"登记失败: {e}")


def task_settle(run_id: int, date: str | None = None):
    try:
        db.run_update(run_id, message="手动结算（fusion_cli settle）…")
        args = ["settle", "--store", str(backtest_store())]
        if date:
            args += ["--date", date]
        r = _cli(args, timeout=600)
        tail = (r.stdout or r.stderr or "")[-400:]
        if r.returncode != 0:
            db.run_update(run_id, status="error", message=tail or "settle 失败")
            return
        db.run_update(run_id, status="done", message="结算完成，看板将读 results/")
    except Exception as e:
        db.run_update(run_id, status="error", message=f"结算失败: {e}")


def start_collect(kickoff_date: str) -> int:
    rid = db.run_start("collect", message="启动采集")
    threading.Thread(target=task_collect, args=(kickoff_date, rid), daemon=True).start()
    return rid


def start_predict(kickoff_date: str | None = None) -> int:
    rid = db.run_start("predict", message="启动补登记")
    threading.Thread(target=task_predict, args=(rid, kickoff_date), daemon=True).start()
    return rid


def start_settle(date: str | None = None) -> int:
    rid = db.run_start("settle", message="启动手动结算")
    threading.Thread(target=task_settle, args=(rid, date), daemon=True).start()
    return rid


# 旧名留给 app 兼容
start_backtest = start_settle
