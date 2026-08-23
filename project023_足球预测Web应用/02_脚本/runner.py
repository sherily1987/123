# -*- coding: utf-8 -*-
"""工作台调度：写操作只走 fusion_cli，登记 market_only。SQLite 只记任务进度。"""
from __future__ import annotations

import json
import os
import re
import shutil
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


def llm_repo() -> Path:
    env = os.environ.get("FOOTBALL_LLM_ROOT")
    if env:
        p = Path(env)
        if (p / "predict.py").is_file():
            return p
        if (p.parent / "predict.py").is_file():
            return p.parent
    f = HERE.parents[1] / "project018_技能工作区整合" / "02_脚本" / "llm" / "football-llm-predictor"
    if (f / "predict.py").is_file():
        return f
    c = Path(r"C:\Users\Administrator\football-llm-predictor")
    if (c / "predict.py").is_file():
        return c
    raise FileNotFoundError("未找到 football-llm-predictor（可设 FOOTBALL_LLM_ROOT）")


def fusion_to_llm_match(match: dict) -> dict:
    meta = match.get("sporttery_meta") or {}
    kick = match.get("kickoff") or match.get("kickoff_iso") or ""
    odds = match.get("odds") or match.get("model_odds") or []
    local = kick.replace("T", " ")[:16] if kick else ""
    return {
        "match_id": meta.get("match_id") or match.get("match_id"),
        "match_num": meta.get("match_num") or match.get("match_num") or "",
        "kickoff_iso": kick,
        "kickoff_local": local,
        "timezone": "Asia/Shanghai",
        "league": match.get("competition") or match.get("stage") or match.get("league") or "",
        "home": match.get("home") or "",
        "away": match.get("away") or "",
        "status_name": "已开售",
        "model_odds": list(odds[:3]) if odds else [],
        "hhad": match.get("hhad") or {},
        "crs": match.get("crs") or {},
        "ttg": match.get("ttg") or {},
        "hafu": match.get("hafu") or {},
        "team_ids": {
            "home_full": meta.get("home_full") or match.get("home") or "",
            "away_full": meta.get("away_full") or match.get("away") or "",
        },
        # 证据快照只作为 LLM 可引用事实，不改变 LLM 票数语义，也不进入量化概率。
        "evidence_chain": match.get("evidence_chain") or {},
        "evidence_snapshot_ref": match.get("evidence_snapshot_ref"),
        "browser_evidence_ref": match.get("browser_evidence_ref"),
    }


def existing_evidence_index(exclude: Path | None = None) -> dict[str, Path]:
    skip = exclude.resolve() if exclude else None
    out: dict[str, Path] = {}
    for mid, rec in sv.load_llm_evidence_files(include_shared=True).items():
        path = rec.get("evidence_file")
        if not path:
            continue
        p = Path(path)
        if skip and p.parent.resolve() == skip:
            continue
        out[mid] = p
    return out


def prepare_llm_evidence(matches: list[dict], ev_dir: Path) -> list[dict]:
    """按 raw 序号写 evidence_NNN_*.md：有深度文件就复用，否则轻量生成。有投票包就套 20 源整合行。"""
    import light_evidence
    from collector import league_tiers, quant_annotation
    llm = llm_repo()
    if str(llm) not in sys.path:
        sys.path.insert(0, str(llm))

    ev_dir.mkdir(parents=True, exist_ok=True)
    index = existing_evidence_index(exclude=ev_dir)
    tiers = league_tiers()
    done = []
    for i, m in enumerate(matches, 1):
        mid = sv.sporttery_id(m.get("match_id"))
        home = m.get("home") or "home"
        away = m.get("away") or "away"
        dest = ev_dir / f"evidence_{i:03d}_{home}_{away}.md"
        src = index.get(mid) if mid else None
        if src and src.is_file():
            shutil.copy2(src, dest)
            mcp = src.with_name(src.stem + "_mcp.md")
            if mcp.is_file():
                shutil.copy2(mcp, ev_dir / f"evidence_{i:03d}_{home}_{away}_mcp.md")
            try:
                import evidence_vote as evote
                merged = evote.apply_pack_file(dest.read_text(encoding="utf-8"), mid)
                dest.write_text(merged, encoding="utf-8")
            except Exception:
                pass
            fusion_text = light_evidence.render_fusion_evidence(m)
            if fusion_text:
                with dest.open("a", encoding="utf-8") as fh:
                    fh.write("\n\n" + fusion_text + "\n")
            done.append({"match_index": i, "file": dest.name, "source": "reuse", "match_id": mid})
            continue
        tier = quant_annotation(m.get("league", ""), tiers)
        dest.write_text(light_evidence.build_one(i, m, tier), encoding="utf-8")
        done.append({"match_index": i, "file": dest.name, "source": "light", "match_id": mid})
        try:
            import evidence_vote as evote
            merged = evote.apply_pack_file(dest.read_text(encoding="utf-8"), mid)
            dest.write_text(merged, encoding="utf-8")
        except Exception:
            pass
    return done


_LLM_HEAD = re.compile(r"⚽ 第\d+/\d+场 \[([^\]]+)\]\s+(\S+)\s+VS\s+(\S+)")
_LLM_DIR = re.compile(
    r"综合方向:\s+(\S+)\s+\((\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)票,\s*强度(\d+)%\)"
)
_LLM_SCORE = re.compile(r"比分(?:偏好|Top3):\s+(.+)")
_LLM_ALT = re.compile(r"建议双选\s+(\S+)/(\S+)")


def parse_llm_log(text: str) -> dict:
    rows = []
    for blk in re.split(r"(?=⚽ 第)", text or ""):
        dm = _LLM_DIR.search(blk)
        if not dm:
            continue
        hm = _LLM_HEAD.search(blk)
        sm = _LLM_SCORE.search(blk)
        am = _LLM_ALT.search(blk)
        scores = []
        if sm:
            for part in re.split(r"[,，/]", sm.group(1)):
                token = part.strip()
                if token and token not in ("分散", "-", "比分Top3"):
                    scores.append(token)
        score = scores[0] if scores else None
        rows.append({
            "num": hm.group(1) if hm else "",
            "home": hm.group(2) if hm else "",
            "away": hm.group(3) if hm else "",
            "dir": dm.group(1),
            "votes": float(dm.group(2)),
            "total_votes": float(dm.group(3)),
            "strength": int(dm.group(4)),
            "score": score,
            "top_scores": scores[:3],
            "alt": am.group(2) if am else None,
            "evidence_gap": ("证据存在缺口" in blk) or ("证据缺口" in blk),
        })
    skipped = len(re.findall(
        r'"status":\s*"(evidence_insufficient|evidence_audit_failed)"', text or ""
    ))
    return {"rows": rows, "ok": len(rows), "skipped": skipped}


def write_llm_jobs(kickoff_date: str, raw_matches: list[dict], parsed: list[dict]) -> int:
    from job_ticket import identity_from, jobs_root, upsert_job

    by_num = {(m.get("match_num") or ""): m for m in raw_matches}
    root = jobs_root()
    n = 0
    for row in parsed:
        src = by_num.get(row.get("num") or "")
        if not src:
            continue
        ident = identity_from(src, extra={"sales_day": kickoff_date})
        if not ident.get("match_id"):
            continue
        strength = (row.get("strength") or 0) / 100.0
        upsert_job(root, ident, llm={
            "track": "llm",
            "direction": row.get("dir"),
            "alt_direction": row.get("alt"),
            "strength": {"type": "vote_share", "value": round(strength, 4)},
            "action": "skip",
            "evidence_gap": bool(row.get("evidence_gap")),
            "score": row.get("score"),
            "top_scores": row.get("top_scores") or ([row.get("score")] if row.get("score") else []),
        })
        n += 1
    return n


def _ensure_prematch(kickoff_date: str, work: Path) -> Path:
    inp = work / "inputs_prematch.json"
    if inp.exists():
        return inp
    work.mkdir(parents=True, exist_ok=True)
    r = _cli([
        "collect", "--kickoff-date", kickoff_date,
        "--output", str(work / "sporttery_prematch.json"),
        "--emit-input", str(inp),
    ], timeout=900)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "collect 失败")[-300:])
    if not inp.exists():
        raise RuntimeError("采集完成但没有 inputs_prematch.json")
    return inp


def _future_llm_matches(fusion_matches: list[dict], now: datetime) -> list[dict]:
    out = []
    for m in fusion_matches:
        kick = sv.parse_dt(m.get("kickoff"))
        if kick is not None and kick <= now:
            continue
        if m.get("mode") and m.get("mode") != "market_only":
            continue
        row = fusion_to_llm_match(m)
        if not row.get("match_id"):
            continue
        out.append(row)
    return out


def task_llm(run_id: int, kickoff_date: str | None = None):
    """复用当日 fusion 采集，组 LLM raw + 证据，跑 predict.py，落盘到 forward/{date}/。"""
    try:
        day = kickoff_date or datetime.now(CST).date().isoformat()
        work = forward_work_dir() / day
        db.run_update(run_id, message=f"LLM 轨准备 {day}…")
        inp = _ensure_prematch(day, work)
        fusion = json.loads(inp.read_text(encoding="utf-8")).get("matches") or []
        matches = _future_llm_matches(fusion, datetime.now(CST))
        if not matches:
            db.run_update(run_id, status="done", message=f"{day} 没有未开球可跑的 LLM 场次")
            return
        raw = {
            "schema_version": "1.0",
            "source": "fusion inputs_prematch",
            "kickoff_date": day,
            "count": len(matches),
            "matches": matches,
        }
        raw_path = work / "llm_raw.json"
        raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ev_dir = work / "llm_evidence"
        prepared = prepare_llm_evidence(matches, ev_dir)
        reused = sum(1 for x in prepared if x["source"] == "reuse")
        light = sum(1 for x in prepared if x["source"] == "light")
        db.run_update(
            run_id, total=len(matches),
            message=f"证据就绪 复用{reused} 轻量{light}，开始跑 {len(matches)} 场…",
        )
        repo = llm_repo()
        log_path = work / "llm_predictions.txt"
        env = _no_proxy_env()
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [PY, str(repo / "predict.py"), "--input", str(raw_path), "--evidence-dir", str(ev_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            env=env, cwd=str(repo),
        )
        chunks: list[str] = []
        done = 0
        assert proc.stdout is not None
        for line in proc.stdout:
            chunks.append(line)
            if "综合方向:" in line or '"status": "evidence_' in line:
                done += 1
                db.run_update(run_id, done=done, message=f"LLM {done}/{len(matches)}")
        rc = proc.wait(timeout=7200)
        log = "".join(chunks)
        log_path.write_text(log, encoding="utf-8")
        if rc != 0:
            db.run_update(run_id, status="error", message=f"predict.py 退出 {rc}，见 {log_path.name}")
            return
        parsed = parse_llm_log(log)
        (work / "llm_parsed.json").write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        jobs_n = write_llm_jobs(day, matches, parsed["rows"])
        report = [
            f"# LLM轨 {day}",
            "",
            "证据方向，不是概率。不与量化轨合成。深度抓取不在本工作流里。",
            "",
            f"- 待跑 {len(matches)} 场，复用深度证据 {reused}，轻量证据 {light}",
            f"- 出方向 {parsed['ok']}，门禁/审计跳过 {parsed['skipped']}",
            f"- 工单写入 {jobs_n}",
            f"- 日志 `{log_path.name}`",
            "",
            "| 场次 | 比赛 | 方向 | 强度 | 比分 |",
            "|---|---|---|---|---|",
        ]
        for row in parsed["rows"]:
            report.append(
                f"| {row.get('num')} | {row.get('home')} vs {row.get('away')} | "
                f"{row.get('dir')} | {row.get('strength')}% | {row.get('score') or '-'} |"
            )
        report.append("")
        (work / "LLM轨.md").write_text("\n".join(report), encoding="utf-8")
        db.run_update(
            run_id, done=parsed["ok"], total=len(matches), status="done",
            message=f"LLM 完成 {parsed['ok']}/{len(matches)}（跳过 {parsed['skipped']}，轻量 {light}）",
        )
    except Exception as e:
        db.run_update(run_id, status="error", message=f"LLM 轨失败: {e}")


def task_backtest(run_id: int):
    """结算完赛 + 共享库量化回测 + 待回测目录双轨。"""
    try:
        workspace = HERE.parents[1]
        script = FUSION_SCRIPTS / "auto_backtest.py"
        out = workspace / "project021_五大联赛APIFootball训练" / "05_交付" / "auto_backtest"
        out.mkdir(parents=True, exist_ok=True)
        db.run_update(run_id, message="回测启动：结算 + 量化 + 双轨…")
        env = _no_proxy_env()
        env["FUSION_WORKSPACE_ROOT"] = str(workspace)
        env["FUSION_DATA_ROOT"] = str(backtest_store().parent)
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.run(
            [PY, str(script), "--workspace", str(workspace),
             "--output-dir", str(out), "--store", str(backtest_store()), "--settle"],
            capture_output=True, text=True, timeout=3600,
            env=env, cwd=str(FUSION_SCRIPTS),
            encoding="utf-8", errors="replace",
        )
        tail = ((proc.stdout or "") + (proc.stderr or ""))[-500:]
        if proc.returncode != 0:
            db.run_update(run_id, status="error", message=tail or "auto_backtest 失败")
            return
        db.run_update(run_id, status="done",
                      message="回测完成，见 05_交付/auto_backtest/latest。历史页将刷新。")
    except Exception as e:
        db.run_update(run_id, status="error", message=f"回测失败: {e}")


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


def start_llm(kickoff_date: str | None = None) -> int:
    rid = db.run_start("llm", message="启动 LLM 轨")
    threading.Thread(target=task_llm, args=(rid, kickoff_date), daemon=True).start()
    return rid


def start_backtest() -> int:
    rid = db.run_start("backtest", message="启动回测")
    threading.Thread(target=task_backtest, args=(rid,), daemon=True).start()
    return rid
