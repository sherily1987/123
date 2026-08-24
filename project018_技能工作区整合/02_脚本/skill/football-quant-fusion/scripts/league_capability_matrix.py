#!/usr/bin/env python3
"""Build an auditable league capability matrix from pre-match records.

The matrix is a queue gate, not a claim that a league is profitable.  Records
must be pre-match snapshots and may contain evidence_audit/settlement metadata.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def _as_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _league_key(row):
    return str(row.get("league_id") or row.get("competition") or row.get("league") or "unknown")


def _is_verified_result(row):
    settlement = row.get("settlement") or {}
    status = str(settlement.get("score_90_status") or settlement.get("status") or "").lower()
    if status in {"verified", "settled", "complete", "finished"}:
        return True
    score = row.get("score_90") or row.get("result_90")
    return isinstance(score, (list, tuple)) and len(score) == 2


def classify(rows, *, min_samples=300, min_recent=60, max_missing_rate=0.20, min_verified_rate=0.95):
    ordered = sorted(rows, key=lambda item: str(item.get("kickoff") or item.get("prediction_as_of") or ""))
    recent = ordered[-min_recent:] if len(ordered) >= min_recent else ordered
    gap_count = 0
    for row in ordered:
        audit = row.get("evidence_audit") or {}
        if audit.get("evidence_gap") is True:
            gap_count += 1
    verified = sum(1 for row in ordered if _is_verified_result(row))
    xg_valid_statuses = {"VALID", "AVAILABLE", "EXPLICIT_XG", "PROXY_XG", "OK"}
    xg_count = sum(
        1 for row in ordered
        if str(row.get("xg_status") or row.get("xg", {}).get("status") or "").upper()
        in xg_valid_statuses
    )
    n = len(ordered)
    missing_rate = gap_count / n if n else 1.0
    verified_rate = verified / n if n else 0.0
    recent_valid = sum(1 for row in recent if not (row.get("evidence_audit") or {}).get("evidence_gap"))
    reasons = []
    if n < min_samples:
        reasons.append("sample_below_minimum")
    if recent_valid < min_recent:
        reasons.append("recent_valid_sample_below_minimum")
    if missing_rate > max_missing_rate:
        reasons.append("evidence_missing_rate_above_limit")
    if verified_rate < min_verified_rate:
        reasons.append("result_verification_rate_below_limit")
    if n == 0:
        tier = "拒绝"
    elif not reasons:
        tier = "可用"
    elif n >= min_samples // 2 and verified_rate >= min_verified_rate * 0.9:
        tier = "降级"
    else:
        tier = "拒绝"
    return {
        "tier": tier,
        "sample_count": n,
        "recent_window_count": len(recent),
        "recent_valid_sample_count": recent_valid,
        "evidence_gap_count": gap_count,
        "evidence_missing_rate": round(missing_rate, 4),
        "verified_result_count": verified,
        "verified_result_rate": round(verified_rate, 4),
        "xg_coverage_count": xg_count,
        "xg_coverage_rate": round(xg_count / n, 4) if n else 0.0,
        "production_eligible": tier == "可用",
        "research_only": tier != "可用",
        "reasons": reasons,
        "thresholds": {
            "min_samples": min_samples,
            "min_recent_valid_samples": min_recent,
            "max_evidence_missing_rate": max_missing_rate,
            "min_verified_result_rate": min_verified_rate,
        },
    }


def build_matrix(rows, **kwargs):
    grouped = defaultdict(list)
    for row in rows:
        grouped[_league_key(row)].append(row)
    leagues = {key: classify(value, **kwargs) for key, value in sorted(grouped.items())}
    counts = defaultdict(int)
    for item in leagues.values():
        counts[item["tier"]] += 1
    return {
        "schema_version": "league-capability-matrix-1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "queue_policy": "可用=允许进入候选队列；降级=降权/需豁免；拒绝=不得进入核心版本",
        "league_count": len(leagues),
        "tier_counts": dict(counts),
        "leagues": leagues,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="JSONL pre-match records")
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-samples", type=int, default=300)
    parser.add_argument("--min-recent", type=int, default=60)
    parser.add_argument("--max-missing-rate", type=float, default=0.20)
    parser.add_argument("--min-verified-rate", type=float, default=0.95)
    args = parser.parse_args()
    rows = [json.loads(line) for line in Path(args.input).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    result = build_matrix(rows, min_samples=args.min_samples, min_recent=args.min_recent,
                          max_missing_rate=args.max_missing_rate, min_verified_rate=args.min_verified_rate)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
