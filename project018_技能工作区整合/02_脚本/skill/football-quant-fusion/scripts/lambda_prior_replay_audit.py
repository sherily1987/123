#!/usr/bin/env python3
"""Deterministically replay legacy lambda priors from timestamped history."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from production_router import load_event_rows, route_match


def compare_prior(saved: dict[str, Any], replayed: dict[str, Any]) -> dict[str, Any]:
    mismatches = []
    for field in ("lambda_home", "lambda_away"):
        try:
            equal = math.isclose(float(saved.get(field)), float(replayed.get(field)), abs_tol=1e-9)
        except (TypeError, ValueError):
            equal = False
        if not equal:
            mismatches.append(field)
    for field in ("source", "sample_legs", "team_sample_sizes"):
        if saved.get(field) != replayed.get(field):
            mismatches.append(field)
    return {
        "equivalent": not mismatches,
        "mismatches": mismatches,
    }


def replay_job(
    job: dict[str, Any],
    understat_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    *,
    route_fn: Callable[..., dict[str, Any]] = route_match,
    min_history: int = 5,
) -> dict[str, Any]:
    identity = job.get("identity") or {}
    hybrid = (job.get("research") or {}).get("hybrid") or {}
    saved = hybrid.get("lambda_prior") or {}
    base = {
        "match_id": identity.get("match_id"),
        "kickoff": identity.get("kickoff"),
        "saved_prior": saved,
    }
    if not saved:
        return {**base, "status": "skipped", "reason": "missing_saved_prior"}
    routed = route_fn(
        job.get("input") or {},
        understat_rows,
        event_rows,
        min_history,
        True,
    )
    replayed = routed.get("lambda_prior") or {}
    if not replayed:
        audit = (routed.get("field_meta") or {}).get("production_router") or {}
        return {
            **base,
            "status": "not_reproduced",
            "reason": audit.get("fallback_reason") or "router_returned_no_prior",
            "routing_audit": audit,
        }
    comparison = compare_prior(saved, replayed)
    return {
        **base,
        "status": "equivalent" if comparison["equivalent"] else "mismatch",
        "replayed_prior": replayed,
        "routing_audit": (routed.get("field_meta") or {}).get("production_router") or {},
        **comparison,
    }


def build_report(
    jobs_root: Path,
    understat_store: Path,
    events_store: Path,
    *,
    min_history: int = 5,
) -> dict[str, Any]:
    understat_rows = load_event_rows(understat_store)
    event_rows = load_event_rows(events_store)
    rows = []
    seen = set()
    for path in sorted(Path(jobs_root).rglob("sporttery-*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        match_id = (job.get("identity") or {}).get("match_id")
        if not match_id or match_id in seen:
            continue
        if not (((job.get("research") or {}).get("hybrid") or {}).get("lambda_prior")):
            continue
        seen.add(match_id)
        row = replay_job(job, understat_rows, event_rows, min_history=min_history)
        row["job_path"] = str(path.resolve())
        rows.append(row)
    counts = {
        status: sum(1 for row in rows if row.get("status") == status)
        for status in ("equivalent", "mismatch", "not_reproduced", "skipped")
    }
    return {
        "schema": "lambda-prior-replay-audit-1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_change_allowed": False,
        "source_rows": {
            "understat": len(understat_rows),
            "events": len(event_rows),
        },
        "counts": {"total": len(rows), **counts},
        "rows": rows,
        "note": "equivalent仅证明当前时间过滤路由可从历史源重建相同λ；不改写原工单。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-root", required=True)
    parser.add_argument("--understat-store", required=True)
    parser.add_argument("--events-store", required=True)
    parser.add_argument("--min-history", type=int, default=5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_report(
        Path(args.jobs_root),
        Path(args.understat_store),
        Path(args.events_store),
        min_history=args.min_history,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
