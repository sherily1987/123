#!/usr/bin/env python3
"""只读融合库：看板用。不写 registry / predictions。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VAULT = HERE.parents[1]
FUSION_SCRIPTS = (
    VAULT / "project018_技能工作区整合" / "02_脚本" / "skill" / "football-quant-fusion" / "scripts"
)
CORE = (
    VAULT / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts"
)
if str(FUSION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(FUSION_SCRIPTS))
from runtime_paths import data_root  # noqa: E402

CST = timezone(timedelta(hours=8))
LATE_TARGET = 200
STATUS_ZH = {
    "UNAVAILABLE": "暂无数据",
    "VALID": "有效",
    "NO_API_ID": "无供应商场次号",
    "TOO_EARLY": "未到T-75",
    "POST_KICKOFF": "已开球",
    "MISSING": "缺失",
    "MARKET_BASELINE": "市场基线",
}


def status_zh(code):
    if not code:
        return None
    return STATUS_ZH.get(str(code), str(code))


def store_root() -> Path:
    return data_root()


def parse_dt(value):
    if value in (None, ""):
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s)
        else:
            dt = datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt.astimezone(timezone.utc)


def sporttery_id(value) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.lower().startswith("sporttery-"):
        rest = text.split("-", 1)[1]
        return f"sporttery-{rest}" if rest else None
    if text.isdigit():
        return f"sporttery-{text}"
    return None


def remap_pred_path(raw: str, root: Path | None = None) -> Path:
    root = root or store_root()
    text = str(raw).replace("\\", "/")
    marker = "football-quant-fusion/"
    if marker in text:
        tail = text.split(marker, 1)[1]
        return root / Path(tail)
    return Path(raw)


def list_had(row: dict) -> list[float] | None:
    try:
        odds = [float(row.get("h")), float(row.get("d")), float(row.get("a"))]
    except (TypeError, ValueError):
        return None
    if min(odds) > 1:
        return odds
    return None


def classify(has_odds: bool, not_kicked: bool, predicted: bool, finished: bool) -> str:
    if finished:
        return "finished"
    if not not_kicked:
        return "kicked"
    if not has_odds:
        return "no_odds"
    if predicted:
        return "predicted"
    return "missing_pred"


def extract_quant(payload: dict) -> dict:
    """正式登记在 output，流水线副本在 forecast。两处都认。"""
    blobs = [
        payload.get("output") if isinstance(payload.get("output"), dict) else None,
        payload.get("forecast") if isinstance(payload.get("forecast"), dict) else None,
        (payload.get("core_output") or {}).get("forecast") if isinstance(payload.get("core_output"), dict) else None,
        payload.get("core_output") if isinstance(payload.get("core_output"), dict) else None,
        payload,
    ]
    pct = tops = gate = None
    for blob in blobs:
        if not blob:
            continue
        if pct is None and isinstance(blob.get("final_1x2_pct"), list) and len(blob["final_1x2_pct"]) >= 3:
            pct = [float(x) for x in blob["final_1x2_pct"][:3]]
        if tops is None and isinstance(blob.get("top_scores"), list):
            labs = []
            for item in blob["top_scores"][:3]:
                if isinstance(item, dict) and item.get("score"):
                    labs.append(str(item["score"]))
            if labs:
                tops = labs
        if gate is None:
            rg = blob.get("recommendation_gate")
            if isinstance(rg, dict) and rg.get("status"):
                gate = rg["status"]
    return {"final_1x2_pct": pct, "top_scores": tops or [], "gate": gate}


def load_registry_quant(root: Path | None = None) -> dict[str, dict]:
    root = root or store_root()
    reg = root / "backtest" / "registry.jsonl"
    latest: dict[str, dict] = {}
    if not reg.exists():
        return latest
    for line in reg.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        mid = sporttery_id(rec.get("match_id"))
        if not mid:
            continue
        prev = latest.get(mid)
        if prev is None or str(rec.get("created_at") or "") >= str(prev.get("created_at") or ""):
            latest[mid] = rec
    out = {}
    for mid, rec in latest.items():
        path = remap_pred_path(rec.get("path") or "", root)
        payload = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
        extracted = extract_quant(payload)
        bi = payload.get("build_identity") or payload.get("model") or {}
        out[mid] = {
            "predicted": True,
            "mode": payload.get("mode") or (payload.get("output") or {}).get("mode"),
            "gate": extracted["gate"],
            "final_1x2_pct": extracted["final_1x2_pct"],
            "top_scores": extracted["top_scores"],
            "prediction_as_of": payload.get("prediction_as_of") or rec.get("created_at"),
            "prediction_id": rec.get("prediction_id"),
            "path": str(path),
            "hashes": {
                "engine_bundle_sha256": bi.get("engine_bundle_sha256"),
                "prediction_code_sha256": bi.get("prediction_code_sha256"),
                "config_sha256": bi.get("config_sha256"),
            },
        }
    return out


def load_jobs_llm(root: Path | None = None) -> dict[str, dict]:
    root = root or store_root()
    jobs = root / "jobs"
    out: dict[str, dict] = {}
    if not jobs.exists():
        return out
    for path in jobs.rglob("sporttery-*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mid = sporttery_id((job.get("identity") or {}).get("match_id") or path.stem)
        if not mid:
            continue
        llm = next((o for o in (job.get("outputs") or []) if o.get("track") == "llm"), None)
        if not llm:
            continue
        strength = llm.get("strength") if isinstance(llm.get("strength"), dict) else None
        out[mid] = {
            "direction": llm.get("direction") or llm.get("dir"),
            "vote_share": None if not strength else strength.get("value"),
            "action": llm.get("action"),
            "note": "证据方向，不是概率",
        }
    return out


def load_results(root: Path | None = None) -> dict[str, dict]:
    root = root or store_root()
    folder = root / "backtest" / "results"
    out = {}
    if not folder.exists():
        return out
    for path in folder.glob("sporttery-*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mid = sporttery_id(rec.get("match_id") or path.stem)
        sc = rec.get("score_90") or {}
        if rec.get("status") == "finished" and isinstance(sc, dict):
            out[mid] = {"score_90": [sc.get("home"), sc.get("away")], "status": "finished"}
    return out


def load_late_info(root: Path | None = None) -> tuple[dict[str, dict], dict]:
    root = root or store_root()
    path = root / "late_info" / "events.jsonl"
    by: dict[str, dict] = {}
    n_inj = n_xi = n_late = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            mid = sporttery_id(rec.get("match_id"))
            if not mid:
                continue
            slot = by.setdefault(mid, {"injury": None, "lineup": None, "late": False})
            kind = rec.get("kind")
            if kind in ("injury", "lineup"):
                slot[kind] = rec.get("status")
                slot[f"{kind}_zh"] = status_zh(rec.get("status"))
            if (rec.get("gate") or {}).get("late"):
                slot["late"] = True
                n_late += 1
            if kind == "injury" and rec.get("status") == "VALID":
                n_inj += 1
            if kind == "lineup" and rec.get("status") == "VALID":
                n_xi += 1
    summary = {
        "events_file": str(path),
        "injury_valid": n_inj,
        "lineup_valid": n_xi,
        "late_events": n_late,
        "unique_matches": len(by),
        "toward_200": LATE_TARGET,
        "note": "研究库，不进生产 1X2",
    }
    return by, summary


def fetch_live_selling(now=None) -> list[dict]:
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    import fetch_sporttery_full as sporttery

    now = now or datetime.now(CST)
    seen: dict[int, dict] = {}
    dates = [(now + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(0, 4)]
    for method in ("all", "concern"):
        for day in dates:
            try:
                data = sporttery.fetch_pages({"method": method, "matchDate": day, "isFix": 0})
            except Exception:
                continue
            for row in sporttery.parse_list(data):
                mid = row.get("matchId")
                if mid is not None:
                    seen[int(mid)] = row
    return list(seen.values())


def board(now=None, live_rows: list[dict] | None = None, root: Path | None = None) -> dict:
    root = root or store_root()
    now = now or datetime.now(CST)
    now_utc = now.astimezone(timezone.utc)
    live = live_rows if live_rows is not None else fetch_live_selling(now)
    quant = load_registry_quant(root)
    llm = load_jobs_llm(root)
    results = load_results(root)
    late_by, late_sum = load_late_info(root)
    rows = []
    for raw in live:
        mid = sporttery_id(raw.get("matchId"))
        kick = parse_dt(f"{raw.get('matchDate') or ''} {raw.get('matchTime') or ''}".strip())
        odds = list_had(raw)
        st = raw.get("matchStatusName") or ""
        finished = "完成" in st or mid in results
        not_kicked = bool(kick and kick > now_utc) and not finished
        q = quant.get(mid)
        bucket = classify(bool(odds), not_kicked, bool(q), finished)
        rows.append({
            "match_id": mid,
            "match_num": raw.get("matchNumStr"),
            "league": raw.get("leagueAbbName"),
            "home": raw.get("homeTeamAbbName"),
            "away": raw.get("awayTeamAbbName"),
            "kickoff": kick.astimezone(CST).isoformat() if kick else None,
            "status_name": st,
            "has_odds": bool(odds),
            "odds": odds,
            "not_kicked": not_kicked,
            "quant": q,
            "llm": llm.get(mid),
            "late_info": late_by.get(mid),
            "result": results.get(mid),
            "bucket": bucket,
        })
    rows.sort(key=lambda r: (r.get("kickoff") or "", r.get("match_num") or ""))
    selling = [r for r in rows if r["status_name"] == "已开售"]
    future = [r for r in selling if r["not_kicked"]]
    with_odds = [r for r in future if r["has_odds"]]
    missing = [r for r in with_odds if r["bucket"] == "missing_pred"]
    predicted = [r for r in with_odds if r["bucket"] == "predicted"]
    return {
        "as_of": now.isoformat(),
        "store": str(root),
        "read_only_store": True,
        "manual_backtest": True,
        "summary": {
            "listed": len(rows),
            "on_sale": len(selling),
            "future": len(future),
            "has_odds": len(with_odds),
            "predicted": len(predicted),
            "missing_pred": len(missing),
            "no_odds": sum(1 for r in future if not r["has_odds"]),
        },
        "matches": rows,
        "by_league": group_by_league(selling),
        "missing": [{"match_id": r["match_id"], "match_num": r["match_num"],
                     "home": r["home"], "away": r["away"], "kickoff": r["kickoff"],
                     "odds": r["odds"]} for r in missing],
        "late_info": late_sum,
        "note": "量化轨数字来自正式登记；LLM 只展示证据方向，不与量化合成。",
    }


def group_by_league(rows: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(row.get("league") or "未标注", []).append(row)
    out = []
    for name, items in buckets.items():
        items = sorted(items, key=lambda r: (r.get("kickoff") or "", r.get("match_num") or ""))
        out.append({
            "league": name,
            "n": len(items),
            "predicted": sum(1 for r in items if r.get("quant")),
            "missing_pred": sum(1 for r in items if r.get("bucket") == "missing_pred"),
            "first_kickoff": items[0].get("kickoff") if items else None,
            "matches": items,
        })
    out.sort(key=lambda g: (g.get("first_kickoff") or "", g["league"]))
    return out
