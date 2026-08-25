# -*- coding: utf-8 -*-
"""project023 足球预测 Web 应用 — SQLite 存储层。

表：
  matches     每日场次快照（采集结果）
  predictions 预测结果（每销售日每场一条，可覆盖更新）
  backtests   回测记录（赛果+命中）
  runs        后台任务运行状态（采集/预测/回测进度）
"""
import json
import os
import ctypes
import sqlite3
import threading
from ctypes import wintypes
from pathlib import Path
from datetime import datetime, timezone

from workbench_runtime import BUILD_IDENTITY

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "data" / "app.db"
_lock = threading.Lock()

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
ERROR_INVALID_PARAMETER = 87
ERROR_NOT_FOUND = 1168


class RunAlreadyActive(RuntimeError):
    """Raised when a run type already has an authoritative running row."""

    def __init__(self, active_run: dict):
        self.active_run = active_run
        super().__init__(f"{active_run.get('run_type')} run {active_run.get('id')} is already running")

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    sales_day TEXT NOT NULL,
    match_num TEXT NOT NULL,
    match_id INTEGER NOT NULL,
    league TEXT, home TEXT, away TEXT,
    kickoff TEXT,
    odds_1x2 TEXT,            -- JSON [h,d,a] 或 null
    quant_tier TEXT,          -- 量化档位标注（A/B/C/D/F-A/无模型）
    status_name TEXT,
    raw_json TEXT,
    collected_at TEXT,
    PRIMARY KEY (sales_day, match_num)
);
CREATE TABLE IF NOT EXISTS predictions (
    sales_day TEXT NOT NULL,
    match_num TEXT NOT NULL,
    match_id TEXT,
    direction TEXT, strength REAL,
    single_pick TEXT, sp_conf REAL, sp_skip INTEGER,
    sp_action TEXT, sp_bettable INTEGER,
    score TEXT, ou25 TEXT, hafu TEXT,
    evs TEXT,                 -- JSON {方向: ev}
    ev_action TEXT, ev_reason TEXT,
    collapse_flags TEXT,      -- JSON list
    evidence_gap INTEGER,
    model_dirs TEXT,          -- JSON {模型: 方向}
    audit_json TEXT,
    created_at TEXT,
    PRIMARY KEY (sales_day, match_num)
);
CREATE TABLE IF NOT EXISTS backtests (
    sales_day TEXT NOT NULL,
    match_num TEXT NOT NULL,
    match_id TEXT,
    score_90 TEXT,            -- "2-1"
    actual_direction TEXT,    -- 主胜/平局/客胜
    hit_single INTEGER,       -- 单选命中
    hit_double INTEGER,       -- 含双选命中
    score_hit INTEGER,        -- 比分偏好命中
    settled_at TEXT,
    PRIMARY KEY (sales_day, match_num)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT,            -- collect/predict/backtest/export
    status TEXT,              -- running/done/error
    total INTEGER, done INTEGER,
    message TEXT,
    started_at TEXT, finished_at TEXT,
    owner_pid INTEGER,
    owner_identity TEXT,
    owner_fingerprint TEXT,
    progress_json TEXT,          -- JSON：结构化任务运行快照
    logs_json TEXT               -- JSON：最近的用户可见事件
);
"""


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn, table: str, column: str, decl: str):
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init():
    with _lock, _conn() as c:
        c.executescript(SCHEMA)
        _ensure_column(c, "predictions", "match_id", "TEXT")
        _ensure_column(c, "predictions", "sp_action", "TEXT")
        _ensure_column(c, "predictions", "sp_bettable", "INTEGER")
        _ensure_column(c, "backtests", "match_id", "TEXT")
        _ensure_column(c, "runs", "progress_json", "TEXT")
        _ensure_column(c, "runs", "logs_json", "TEXT")
        _ensure_column(c, "runs", "owner_pid", "INTEGER")
        _ensure_column(c, "runs", "owner_identity", "TEXT")
        _ensure_column(c, "runs", "owner_fingerprint", "TEXT")


def _probe_owner_process(pid: int) -> tuple[str, str | None]:
    """Return `alive`, `dead`, or `unknown` using non-destructive Windows APIs."""
    if not isinstance(pid, int) or pid <= 0:
        return "unknown", None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
    )
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in (ERROR_INVALID_PARAMETER, ERROR_NOT_FOUND):
            return "dead", None
        return "unknown", None
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return "unknown", None
        if exit_code.value != STILL_ACTIVE:
            return "dead", None
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user),
        ):
            return "unknown", None
        created_at = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
        return "alive", f"{created_at:016x}"
    finally:
        kernel32.CloseHandle(handle)


def recover_orphaned_runs() -> int:
    """Mark work left by a previous service process as interrupted.

    This is intentionally called only during application startup, before the
    process can accept a request and create a new run.
    """
    now = datetime.now(timezone.utc).isoformat()
    message = "服务重启，任务中断"
    recovered = 0
    with _lock, _conn() as c:
        running = c.execute(
            "SELECT id, owner_pid, owner_identity, owner_fingerprint FROM runs WHERE status='running'"
        ).fetchall()
        for row in running:
            owner_pid = row["owner_pid"]
            owner_fingerprint = row["owner_fingerprint"]
            if (row["owner_identity"] != BUILD_IDENTITY
                    or not isinstance(owner_pid, int) or owner_pid <= 0
                    or not isinstance(owner_fingerprint, str) or not owner_fingerprint):
                continue
            owner_status, current_fingerprint = _probe_owner_process(owner_pid)
            if owner_status == "unknown" or (
                owner_status == "alive" and current_fingerprint == owner_fingerprint
            ):
                continue
            cursor = c.execute(
                """UPDATE runs
                   SET status='error', finished_at=?,
                       message=CASE WHEN message IS NULL OR message='' THEN ?
                                    ELSE message || '\n' || ? END
                   WHERE id=? AND status='running' AND owner_pid=? AND owner_identity=?
                     AND owner_fingerprint=?""",
                (now, message, message, row["id"], owner_pid, BUILD_IDENTITY, owner_fingerprint),
            )
            recovered += cursor.rowcount
    return recovered


def upsert_matches(sales_day: str, rows: list[dict]):
    """rows: 采集到的场次 dict 列表（match_num/match_id/league/home/away/kickoff/odds/quant_tier/status_name）。"""
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _conn() as c:
        for r in rows:
            c.execute(
                """INSERT INTO matches (sales_day, match_num, match_id, league, home, away, kickoff,
                   odds_1x2, quant_tier, status_name, raw_json, collected_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(sales_day, match_num) DO UPDATE SET
                   odds_1x2=excluded.odds_1x2, status_name=excluded.status_name,
                   raw_json=excluded.raw_json, collected_at=excluded.collected_at""",
                (sales_day, r["match_num"], r["match_id"], r.get("league"), r.get("home"), r.get("away"),
                 r.get("kickoff"), json.dumps(r.get("odds_1x2"), ensure_ascii=False) if r.get("odds_1x2") else None,
                 r.get("quant_tier"), r.get("status_name"),
                 json.dumps(r, ensure_ascii=False), now))


def list_matches(sales_day: str = None):
    with _lock, _conn() as c:
        if sales_day:
            rows = c.execute("SELECT * FROM matches WHERE sales_day=? ORDER BY kickoff", (sales_day,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM matches ORDER BY kickoff DESC LIMIT 200").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["odds_1x2"] = json.loads(d["odds_1x2"]) if d["odds_1x2"] else None
        out.append(d)
    return out


def upsert_predictions(sales_day: str, parsed: list[dict]):
    """parsed: parse_predictions 风格的记录列表（num/home/away/dir/strength/sp/...）。"""
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _conn() as c:
        for p in parsed:
            c.execute(
                """INSERT INTO predictions (sales_day, match_num, match_id, direction, strength, single_pick,
                   sp_conf, sp_skip, sp_action, sp_bettable, score, ou25, hafu, evs, ev_action, ev_reason,
                   collapse_flags, evidence_gap, model_dirs, audit_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(sales_day, match_num) DO UPDATE SET
                   match_id=excluded.match_id,
                   direction=excluded.direction, strength=excluded.strength,
                   single_pick=excluded.single_pick, sp_conf=excluded.sp_conf, sp_skip=excluded.sp_skip,
                   sp_action=excluded.sp_action, sp_bettable=excluded.sp_bettable,
                   score=excluded.score, ou25=excluded.ou25, hafu=excluded.hafu,
                   evs=excluded.evs, ev_action=excluded.ev_action, ev_reason=excluded.ev_reason,
                   collapse_flags=excluded.collapse_flags, evidence_gap=excluded.evidence_gap,
                   model_dirs=excluded.model_dirs, audit_json=excluded.audit_json, created_at=excluded.created_at""",
                (sales_day, p["num"], p.get("match_id"), p.get("dir"), p.get("strength"), p.get("sp"),
                 p.get("sp_conf"), 1 if p.get("sp_skip") else 0, p.get("sp_action"),
                 (1 if p.get("sp_bettable") else 0) if p.get("sp_bettable") is not None else None,
                 p.get("score"), p.get("ou25"), p.get("hafu"),
                 json.dumps(p.get("evs"), ensure_ascii=False) if p.get("evs") else None,
                 p.get("ev_action"), p.get("ev_reason"),
                 json.dumps(p.get("collapse_flags"), ensure_ascii=False) if p.get("collapse_flags") else None,
                 1 if p.get("evidence_gap") else 0,
                 json.dumps(p.get("model_dirs"), ensure_ascii=False) if p.get("model_dirs") else None,
                 json.dumps(p, ensure_ascii=False), now))


def list_predictions(sales_day: str):
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM predictions WHERE sales_day=?", (sales_day,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("evs", "collapse_flags", "model_dirs"):
            d[k] = json.loads(d[k]) if d[k] else None
        out.append(d)
    return out


def upsert_backtests(sales_day: str, rows: list[dict]):
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _conn() as c:
        for r in rows:
            c.execute(
                """INSERT INTO backtests (sales_day, match_num, match_id, score_90, actual_direction,
                   hit_single, hit_double, score_hit, settled_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(sales_day, match_num) DO UPDATE SET
                   match_id=excluded.match_id,
                   score_90=excluded.score_90, actual_direction=excluded.actual_direction,
                   hit_single=excluded.hit_single, hit_double=excluded.hit_double,
                   score_hit=excluded.score_hit, settled_at=excluded.settled_at""",
                (sales_day, r["match_num"], r.get("match_id"), r.get("score_90"), r.get("actual_direction"),
                 1 if r.get("hit_single") else 0, 1 if r.get("hit_double") else 0,
                 1 if r.get("score_hit") else 0, now))


def list_backtests(sales_day: str = None):
    with _lock, _conn() as c:
        if sales_day:
            rows = c.execute("SELECT * FROM backtests WHERE sales_day=?", (sales_day,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM backtests ORDER BY sales_day DESC, match_num").fetchall()
    return [dict(r) for r in rows]


# ---- 后台任务 ----
def run_start(run_type: str, total: int = 0, message: str = "",
              owner_pid: int | None = None, owner_identity: str | None = None,
              owner_fingerprint: str | None = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    owner_pid = os.getpid() if owner_pid is None else owner_pid
    owner_identity = BUILD_IDENTITY if owner_identity is None else owner_identity
    if owner_fingerprint is None:
        status, fingerprint = _probe_owner_process(owner_pid)
        owner_fingerprint = fingerprint if status == "alive" else None
    with _lock, _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        active = c.execute(
            "SELECT * FROM runs WHERE run_type=? AND status='running' ORDER BY id DESC LIMIT 1",
            (run_type,),
        ).fetchone()
        if active:
            raise RunAlreadyActive(_run_dict(active))
        cur = c.execute(
            """INSERT INTO runs
               (run_type, status, total, done, message, started_at, owner_pid, owner_identity, owner_fingerprint)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (run_type, "running", total, 0, message, now, owner_pid, owner_identity, owner_fingerprint),
        )
        return cur.lastrowid


def run_active(run_type: str | None = None) -> list[dict]:
    with _lock, _conn() as c:
        if run_type:
            rows = c.execute(
                "SELECT * FROM runs WHERE status='running' AND run_type=? ORDER BY id DESC",
                (run_type,),
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM runs WHERE status='running' ORDER BY id DESC").fetchall()
    return [_run_dict(row) for row in rows]


def run_update(run_id: int, done: int = None, message: str = None, status: str = None,
               total: int = None, progress: dict | None = None, log: str | None = None):
    with _lock, _conn() as c:
        current = c.execute(
            "SELECT logs_json FROM runs WHERE id=?", (run_id,),
        ).fetchone()
        logs_json = None
        if log is not None:
            try:
                logs = json.loads(current["logs_json"] or "[]") if current else []
            except (TypeError, ValueError):
                logs = []
            logs.append(str(log)[:500])
            logs_json = json.dumps(logs[-30:], ensure_ascii=False)
        progress_json = json.dumps(progress, ensure_ascii=False) if progress is not None else None
        if status:
            now = datetime.now(timezone.utc).isoformat()
            c.execute("UPDATE runs SET status=?, finished_at=?, done=COALESCE(?,done), total=COALESCE(?,total), message=COALESCE(?,message), progress_json=COALESCE(?,progress_json), logs_json=COALESCE(?,logs_json) WHERE id=?",
                      (status, now, done, total, message, progress_json, logs_json, run_id))
        else:
            c.execute("UPDATE runs SET done=COALESCE(?,done), total=COALESCE(?,total), message=COALESCE(?,message), progress_json=COALESCE(?,progress_json), logs_json=COALESCE(?,logs_json) WHERE id=?",
                      (done, total, message, progress_json, logs_json, run_id))


def _run_dict(row) -> dict | None:
    if not row:
        return None
    result = dict(row)
    for source, target, fallback in (
        ("progress_json", "progress", {}), ("logs_json", "logs", []),
    ):
        raw = result.get(source)
        if raw:
            try:
                result[target] = json.loads(raw) or fallback
            except (TypeError, ValueError):
                result[target] = fallback
        result.pop(source, None)
    return result


def run_get(run_id: int):
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return _run_dict(r)
