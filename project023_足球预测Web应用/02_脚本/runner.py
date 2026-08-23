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
from evidence_merge import merge_browser_audit, merge_late_info_events  # noqa: E402

import db
import store_view as sv

PY = resolve_python()
CLI = FUSION_SCRIPTS / "fusion_cli.py"
CST = timezone(timedelta(hours=8))
DEFAULT_LLM_MODEL_ID = "deepseek/deepseek-v4-flash"
EVIDENCE_FIELDS = ("team_stats", "recent_form", "injury", "suspensions", "starting_xi")
EVIDENCE_VALID_STATUSES = {
    "VALID", "VALID_EMPTY", "PREDICTED", "OK", "AVAILABLE", "FRESH", "AGING",
    "IMAGE_EXTRACTED", "PROXY_XG", "EXPLICIT_XG",
}


def _no_proxy_env():
    import os
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(k, None)
    # Enable the bounded, evidence-only API-Sports enrichment stage for
    # production collector jobs. Unit tests and direct collector calls remain
    # deterministic unless they explicitly opt in.
    env.setdefault("ENABLE_API_SPORTS_EVIDENCE", "1")
    return env


def _cli(args: list, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(CLI), *args],
        capture_output=True, text=True, timeout=timeout,
        env=_no_proxy_env(), cwd=str(FUSION_SCRIPTS),
        encoding="utf-8", errors="replace",
    )


def _refresh_evidence_audit(match: dict, chain: dict) -> None:
    """Recompute LLM-facing gap flags after browser/late-info merges.

    The source snapshot audit is immutable, but the Markdown projection must
    describe the merged chain. Otherwise a newly arrived predicted XI or
    injury event is visible in ``evidence_chain`` while ``missing_fields``
    still reports the stale pre-refresh gap.
    """
    audit = match.get("evidence_audit")
    if not isinstance(audit, dict):
        return
    missing = []
    reasons = []
    for name in EVIDENCE_FIELDS:
        item = chain.get(name) if isinstance(chain, dict) else None
        status = str((item or {}).get("status") or "MISSING").upper()
        if status not in EVIDENCE_VALID_STATUSES:
            missing.append(name)
            reason = (item or {}).get("missing_reason") or status
            reasons.append(f"{name.upper()}_{reason}")
    audit["missing_fields"] = missing
    audit["evidence_gap"] = bool(missing)
    audit["evidence_gap_reasons"] = reasons
    audit["evidence_status"] = "GAP" if missing else "OK"
    audit["merged_chain_fields"] = [name for name in EVIDENCE_FIELDS if isinstance(chain.get(name), dict)]


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


def attach_collected_evidence(
    matches: list[dict],
    day: str,
    *,
    forward_root: Path | None = None,
    late_events_path: Path | None = None,
) -> dict:
    """Attach the latest pre-match snapshot to each LLM input by Sporttery ID.

    The collectors deliberately write immutable JSON sidecars.  This function
    creates the LLM-facing projection at run time: browser/mobile evidence is
    merged with provenance preserved, then valid pre-kickoff late-info events
    are applied.  It never changes quant probabilities or treats search
    candidates as facts.
    """
    root = Path(forward_root or forward_work_dir())
    snapshot_dir = root / day / "evidence_snapshots"
    snapshots: dict[str, tuple[Path, dict]] = {}
    if snapshot_dir.is_dir():
        for path in snapshot_dir.glob("sporttery-*.json"):
            try:
                blob = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            mid = sv.sporttery_id(blob.get("match_id"))
            if mid:
                snapshots[mid] = (path, blob)

    event_path = Path(late_events_path or (root.parent / "late_info" / "events.jsonl"))
    events_by_id: dict[str, list[dict]] = {}
    if event_path.is_file():
        for line in event_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            mid = sv.sporttery_id(event.get("match_id"))
            if mid:
                events_by_id.setdefault(mid, []).append(event)

    attached = 0
    late_merged = 0
    missing_snapshot_ids: list[str] = []
    snapshot_rejections: list[dict] = []
    for match in matches:
        mid = sv.sporttery_id(match.get("match_id"))
        if not mid:
            continue
        snapshot = snapshots.get(mid)
        chain = match.get("evidence_chain") or {}
        if snapshot:
            path, blob = snapshot
            kickoff = sv.parse_dt(match.get("kickoff_iso") or match.get("kickoff"))
            collected = sv.parse_dt(blob.get("collected_at") or (blob.get("evidence_audit") or {}).get("collected_at"))
            if kickoff and collected and collected > kickoff:
                snapshot_rejections.append({"match_id": mid, "reason": "SNAPSHOT_AFTER_KICKOFF"})
                missing_snapshot_ids.append(mid)
            else:
                chain, browser_audit = merge_browser_audit(chain, blob.get("evidence_audit"))
                match["evidence_snapshot_ref"] = str(path)
                match["browser_evidence_ref"] = str(path)
                match["evidence_snapshot_audit"] = browser_audit
                match["evidence_audit"] = blob.get("evidence_audit") or {}
                attached += 1
        else:
            missing_snapshot_ids.append(mid)
        if events_by_id.get(mid):
            chain, late_audit = merge_late_info_events(chain, events_by_id[mid])
            match["late_info_merge_audit"] = late_audit
            if late_audit.get("fields_merged"):
                late_merged += 1
        if chain:
            match["evidence_chain"] = chain
            _refresh_evidence_audit(match, chain)
    return {
        "snapshot_dir": str(snapshot_dir),
        "snapshots_available": len(snapshots),
        "matches": len(matches),
        "snapshots_attached": attached,
        "missing_snapshot_ids": missing_snapshot_ids,
        "snapshot_rejections": snapshot_rejections,
        "late_info_matches_merged": late_merged,
    }


def auto_collect_prematch_evidence(input_path: Path, day: str, match_ids: list[str]) -> dict:
    """Fetch missing official preview snapshots for the current LLM batch.

    This is intentionally a bounded, ID-scoped retry.  The collector writes
    sidecars only; a failed provider call is reported and remains a gap.
    """
    if not match_ids:
        return {"attempted": 0, "status": "not_needed"}
    input_path = Path(input_path).resolve()
    output_dir = (forward_work_dir() / day / "evidence_snapshots").resolve()
    args = ["prematch-evidence", "--input", str(input_path), "--output-dir", str(output_dir)]
    for mid in sorted(set(match_ids)):
        args += ["--match-id", mid]
    try:
        result = _cli(args, timeout=1200)
    except Exception as exc:
        return {"attempted": len(set(match_ids)), "status": "error", "error": str(exc)[:240]}
    payload = None
    for line in reversed((result.stdout or "").splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    return {
        "attempted": len(set(match_ids)),
        "status": "ok" if result.returncode == 0 else "error",
        "returncode": result.returncode,
        "report": payload,
        "error_tail": ((result.stderr or result.stdout or "")[-500:]
                       if result.returncode else ""),
    }


def auto_collect_late_info(input_path: Path, day: str, matches: list[dict], *, now: datetime | None = None) -> dict:
    """Run one bounded injury/lineup refresh when a fixture is within 24h.

    The collector itself enforces the pre-kickoff gate and writes research-only
    events. We do not use ``--watch`` here: the web job must finish, while a
    later invocation can perform the next refresh window.
    """
    now = now or datetime.now(CST)
    due = []
    for match in matches:
        kickoff = sv.parse_dt(match.get("kickoff_iso") or match.get("kickoff"))
        if kickoff is None:
            continue
        minutes = (kickoff - now).total_seconds() / 60.0
        if 0 < minutes <= 24 * 60:
            due.append(sv.sporttery_id(match.get("match_id")))
    due = [mid for mid in due if mid]
    if not due:
        return {"attempted": 0, "status": "not_needed", "reason": "no_match_within_24h"}
    input_path = Path(input_path).resolve()
    work_dir = (forward_work_dir() / day).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args = ["late-info", "--from-collect", str(input_path), "--snapshot", f"llm-{stamp}",
            "--work-dir", str(work_dir), "--once"]
    try:
        result = _cli(args, timeout=1800)
    except Exception as exc:
        return {"attempted": len(due), "status": "error", "error": str(exc)[:240]}
    payload = None
    for line in reversed((result.stdout or "").splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    return {
        "attempted": len(due),
        "status": "ok" if result.returncode == 0 else "error",
        "returncode": result.returncode,
        "report": payload,
        "error_tail": ((result.stderr or result.stdout or "")[-500:]
                       if result.returncode else ""),
    }


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
        hm = _LLM_HEAD.search(blk)
        sm = _LLM_SCORE.search(blk)
        am = _LLM_ALT.search(blk)
        audit = None
        for line in blk.splitlines():
            try:
                candidate = json.loads(line.strip())
            except (TypeError, ValueError):
                continue
            if isinstance(candidate, dict) and (
                "prediction_as_of" in candidate or "direction" in candidate
            ):
                audit = candidate
                break
        # DeepSeek V4 Flash is intentionally a single research voter. Its
        # output has no legacy "综合方向" banner, so derive the row from the
        # durable JSON audit instead of silently dropping the prediction.
        if not dm and not isinstance(audit, dict):
            continue
        audit_direction = (audit or {}).get("direction") if isinstance(audit, dict) else None
        if not dm and not audit_direction:
            continue
        individual = (audit or {}).get("individual") if isinstance(audit, dict) else None
        models_used = (audit or {}).get("models_used") if isinstance(audit, dict) else None
        logged_model_id = (
            models_used[0] if isinstance(models_used, list) and len(models_used) == 1
            else None
        )
        raw_audit = {}
        if isinstance(individual, dict):
            for item in individual.values():
                if isinstance(item, dict) and item.get("raw_llm_probs_1x2"):
                    raw_audit = item
                    break
        scores = []
        if sm:
            for part in re.split(r"[,，/]", sm.group(1)):
                token = part.strip()
                if token and token not in ("分散", "-", "比分Top3"):
                    scores.append(token)
        score = scores[0] if scores else None
        if not scores and isinstance(audit, dict):
            scores = list(audit.get("top_scores") or [])
            score = scores[0] if scores else (audit.get("top_score_pref") or None)
        direction = dm.group(1) if dm else audit_direction
        votes = float(dm.group(2)) if dm else float((audit or {}).get("votes") or 0)
        total_votes = float(dm.group(3)) if dm else float((audit or {}).get("total_votes") or 0)
        strength = int(dm.group(4)) if dm else (audit or {}).get("strength")
        alt_direction = am.group(2) if am else (audit or {}).get("alt_direction")
        rows.append({
            "num": hm.group(1) if hm else "",
            "home": hm.group(2) if hm else "",
            "away": hm.group(3) if hm else "",
            "dir": direction,
            "votes": votes,
            "total_votes": total_votes,
            "strength": strength,
            "score": score,
            "top_scores": scores[:3],
            "alt": alt_direction,
            "evidence_gap": bool((audit or {}).get("evidence_gap")) or ("证据存在缺口" in blk) or ("证据缺口" in blk),
            # Preserve historical single-model logs; only new/unlabelled logs
            # use the current DeepSeek V4 Flash default.
            "model_id": logged_model_id or DEFAULT_LLM_MODEL_ID,
            "prediction_as_of": (audit or {}).get("prediction_as_of"),
            "probs_1x2": (audit or {}).get("probs_1x2"),
            "raw_llm_probs_1x2": (audit or {}).get("raw_llm_probs_1x2") or raw_audit.get("raw_llm_probs_1x2"),
            "confidence": (audit or {}).get("confidence"),
            "decision": (audit or {}).get("decision"),
            "top_scores": (audit or {}).get("top_scores") or scores[:3],
            "ou25": (audit or {}).get("top_ou25") or (audit or {}).get("ou25"),
            "hafu": (audit or {}).get("top_hafu") or (audit or {}).get("hafu"),
            "raw_llm_top_scores": raw_audit.get("raw_llm_top_scores"),
            "raw_llm_ou25": raw_audit.get("raw_llm_ou25"),
            "raw_llm_hafu": raw_audit.get("raw_llm_hafu"),
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
            "model_id": row.get("model_id") or DEFAULT_LLM_MODEL_ID,
            "llm_prediction_as_of": row.get("prediction_as_of"),
            "direction": row.get("dir"),
            "alt_direction": row.get("alt"),
            "strength": {"type": "vote_share", "value": round(strength, 4)},
            "action": "skip",
            "evidence_gap": bool(row.get("evidence_gap")),
            "score": row.get("score"),
            "top_scores": row.get("top_scores") or ([row.get("score")] if row.get("score") else []),
            # Keep both production and research-only probability fields so a
            # settled DeepSeek cohort can be calibrated without promoting raw
            # self-reported probabilities into production.
            "llm_probs_1x2": row.get("probs_1x2"),
            "llm_raw_probs_1x2": row.get("raw_llm_probs_1x2"),
            "llm_confidence": row.get("confidence"),
            "llm_decision": row.get("decision"),
            "llm_ou25": row.get("ou25"),
            "llm_hafu": row.get("hafu"),
            "llm_raw_top_scores": row.get("raw_llm_top_scores") or [],
            "llm_raw_ou25": row.get("raw_llm_ou25"),
            "llm_raw_hafu": row.get("raw_llm_hafu"),
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
        late_info_stats = auto_collect_late_info(inp, day, matches)
        raw = {
            "schema_version": "1.0",
            "source": "fusion inputs_prematch",
            "kickoff_date": day,
            "count": len(matches),
            "matches": matches,
            "late_info_projection": late_info_stats,
        }
        evidence_stats = attach_collected_evidence(matches, day)
        refresh_ids = evidence_stats.get("missing_snapshot_ids") or []
        # When API-Sports credentials are available, refresh every fixture in
        # this bounded batch so recent form/injury state is not frozen in a
        # stale browser snapshot. Without credentials retain the cheap
        # missing-snapshot retry behavior.
        if os.environ.get("API_FOOTBALL_KEY", "").strip():
            refresh_ids = [sv.sporttery_id(match.get("match_id")) for match in matches]
            refresh_ids = [mid for mid in refresh_ids if mid]
        auto_collect = auto_collect_prematch_evidence(inp, day, refresh_ids)
        if auto_collect.get("attempted"):
            # Re-project after the bounded collector so the exact same batch
            # (and no unrelated fixture) becomes the LLM evidence input.
            evidence_stats = attach_collected_evidence(matches, day)
        evidence_stats["auto_collect"] = auto_collect
        raw["matches"] = matches
        raw["evidence_projection"] = evidence_stats
        raw_path = work / "llm_raw.json"
        raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ev_dir = work / "llm_evidence"
        prepared = prepare_llm_evidence(matches, ev_dir)
        reused = sum(1 for x in prepared if x["source"] == "reuse")
        light = sum(1 for x in prepared if x["source"] == "light")
        db.run_update(
            run_id, total=len(matches),
            message=(f"证据就绪 快照{evidence_stats['snapshots_attached']}/"
                     f"{len(matches)}，晚到合并{evidence_stats['late_info_matches_merged']}，"
                     f"自动补采{auto_collect.get('attempted', 0)}，"
                     f"晚到刷新{late_info_stats.get('attempted', 0)}，"
                     f"复用{reused} 轻量{light}，开始跑 {len(matches)} 场…"),
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
            # DeepSeek V4 Flash's single-model research output does not print
            # the legacy "综合方向" banner; its one-line JSON is the durable
            # completion marker. Keep the legacy markers for older logs.
            if ("综合方向:" in line or '"status": "evidence_' in line
                    or ('"llm_track_contract"' in line and '"match_id"' in line)):
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
            "证据方向，不是概率。不与量化轨合成。采集器快照按体彩 ID 自动投影到 LLM Markdown。",
            "",
            f"- 待跑 {len(matches)} 场，侧车快照接入 {evidence_stats['snapshots_attached']}，"
            f"晚到信息合并 {evidence_stats['late_info_matches_merged']}，"
            f"自动补采 {auto_collect.get('attempted', 0)}，"
            f"晚到刷新 {late_info_stats.get('attempted', 0)}，"
            f"补采后仍缺 {len(evidence_stats.get('missing_snapshot_ids') or [])}",
            f"- 复用深度证据 {reused}，轻量证据 {light}",
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
