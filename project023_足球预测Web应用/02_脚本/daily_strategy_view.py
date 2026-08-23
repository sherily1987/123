#!/usr/bin/env python3
"""Build the Web workbench's read-only daily fixed-budget strategy view."""
from __future__ import annotations

import json
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import store_view as sv


CST = timezone(timedelta(hours=8))
if str(sv.FUSION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(sv.FUSION_SCRIPTS))

from daily_strategy_planner import build_daily_strategy  # noqa: E402
from recommendation_policy import load_policy  # noqa: E402
from evidence_merge import merge_late_info_events  # noqa: E402


def _validated_day(day: str | None, now: datetime) -> str:
    selected = day or now.astimezone(CST).date().isoformat()
    try:
        parsed = datetime.strptime(selected, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError("day must use YYYY-MM-DD") from exc
    if parsed.isoformat() != selected:
        raise ValueError("day must use YYYY-MM-DD")
    return selected


def _load_jobs(folder: Path) -> list[dict]:
    if not folder.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8-sig"))
        for path in sorted(folder.glob("sporttery-*.json"))
    ]


def _attach_evidence_sidecars(jobs: list[dict], store: Path, day: str) -> list[dict]:
    """Attach the latest audited sidecar without rewriting prediction tickets."""
    # The daily pipeline writes immutable snapshots under ``forward/<day>``
    # while older/manual collectors use ``research/evidence/<day>``.  Both are
    # canonical read-only evidence stores; looking at only the latter made a
    # valid snapshot appear as EVIDENCE_AUDIT_MISSING in the workbench.
    evidence_root = store / "research" / "evidence" / day
    roots = [evidence_root, store / "forward" / day]
    sidecars: dict[str, tuple[float, Path, dict]] = {}
    late_events: dict[str, list[dict]] = {}
    late_path = store / "late_info" / "events.jsonl"
    if late_path.is_file():
        for line in late_path.read_text(encoding="utf-8-sig").splitlines():
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            event_mid = str(event.get("match_id") or "")
            if event_mid and not event_mid.startswith("sporttery-"):
                event_mid = f"sporttery-{event_mid}"
            if event_mid and str(event.get("kickoff") or "").startswith(day):
                late_events.setdefault(event_mid, []).append(event)
    paths = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("sporttery-*.json"):
            # Do not treat prediction tickets/results as evidence sidecars.
            if path.parent.name not in {"evidence_snapshots", "bb-browser", "evidence"}:
                continue
            paths.append(path)
    for path in sorted(paths, key=lambda item: (item.stat().st_mtime, str(item))):
        try:
            blob = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        key = str(blob.get("match_id") or path.stem)
        sidecars[key] = (path.stat().st_mtime, path, blob)
    enriched = []
    for job in jobs:
        mid = str(job.get("match_id") or (job.get("identity") or {}).get("match_id") or "")
        found = sidecars.get(mid) or sidecars.get(f"sporttery-{mid}")
        if not found:
            enriched.append(job)
            continue
        _, sidecar_path, blob = found
        audit = blob.get("evidence_audit") or {}
        mid_key = mid if mid.startswith("sporttery-") else f"sporttery-{mid}"
        if late_events.get(mid_key):
            chain, merge_audit = merge_late_info_events(audit.get("entries") or {}, late_events[mid_key])
            valid_statuses = {"VALID", "VALID_EMPTY", "PREDICTED", "OK", "AVAILABLE", "FRESH", "AGING", "PROXY_XG", "EXPLICIT_XG"}
            audit = dict(audit)
            audit["entries"] = chain
            audit["missing_fields"] = [name for name, entry in chain.items()
                                        if str((entry or {}).get("status") or "").upper() not in valid_statuses]
            audit["evidence_gap"] = bool(audit["missing_fields"])
            audit["evidence_status"] = "GAP" if audit["evidence_gap"] else "OK"
            audit["late_info_merge_audit"] = merge_audit
        item = dict(job)
        item["evidence_audit"] = audit
        item["evidence_snapshot_ref"] = str(sidecar_path)
        enriched.append(item)
    return enriched


def _load_deepseek_calibration(store: Path, day: str) -> dict:
    """Read the model-isolated DeepSeek audit for transparent workbench display."""
    path = store / "forward" / day / "deepseek_calibration_audit.json"
    if not path.is_file():
        return {"status": "missing", "model": "deepseek/deepseek-v4-flash",
                "eligible_settled_rows": 0, "minimum_review_rows": 100}
    try:
        report = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"status": "invalid", "model": "deepseek/deepseek-v4-flash",
                "eligible_settled_rows": 0, "minimum_review_rows": 100}
    report = dict(report)
    report.setdefault("status", "ok")
    report.setdefault("minimum_review_rows", 100)
    report.setdefault("model", "deepseek/deepseek-v4-flash")
    report.setdefault("eligible_settled_rows", 0)
    report["ready_for_review"] = report.get("eligible_settled_rows", 0) >= report["minimum_review_rows"]
    report["production_change_allowed"] = False
    return report


def daily_strategy(
    day: str | None = None,
    *,
    root: Path | None = None,
    now: datetime | None = None,
    persist: bool = False,
) -> dict:
    """Return the fixed-budget plan; optionally persist one immutable daily snapshot."""
    current = now or datetime.now(CST)
    selected_day = _validated_day(day, current)
    store = root or sv.store_root()
    jobs = _attach_evidence_sidecars(_load_jobs(store / "jobs" / selected_day), store, selected_day)
    plan = build_daily_strategy(
        jobs,
        load_policy(),
        bankroll=100.0,
        execution_mode="budgeted_action",
        as_of=current,
    )
    output = {
        **plan,
        "selected_day": selected_day,
        "source_job_count": len(jobs),
        "llm_calibration": _load_deepseek_calibration(store, selected_day),
        "display": {
            "strategy_type": "固定娱乐预算（放宽门禁）",
            "edge_label": "未验证正EV",
            "decision_time": current.astimezone(CST).isoformat(),
            "warning": "这是与生产购买门禁分离的固定娱乐预算清单，不代表正EV、凯利仓位或生产推荐；单日最大损失不超过预算。",
            "evidence_warning": (
                f"{plan.get('evidence_gap_summary', {}).get('evidence_gap_market_rows', 0)} 个市场行存在证据缺口；"
                "仅允许低风险市场在规定证据状态下放宽，HAFU/CRS等衍生市场仍会因缺口排除。"
            ),
            "llm_calibration_warning": (
                "DeepSeek V4 Flash 独立校准样本未达到 100 场；LLM 仅作研究观察，不能触发生产投注。"
            ),
        },
    }
    if persist:
        snapshot_dir = store / "daily_strategy_plans"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{selected_day}.json"
        if snapshot_path.exists():
            try:
                existing = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
                output["snapshot_id"] = existing.get("snapshot_id")
                output["snapshot_path"] = str(snapshot_path)
                return output
            except (OSError, json.JSONDecodeError):
                pass
        core = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        output["snapshot_schema"] = "daily_strategy_plan.v1"
        output["snapshot_id"] = hashlib.sha256(core.encode("utf-8")).hexdigest()[:16]
        snapshot_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output["snapshot_path"] = str(snapshot_path)
    return output
