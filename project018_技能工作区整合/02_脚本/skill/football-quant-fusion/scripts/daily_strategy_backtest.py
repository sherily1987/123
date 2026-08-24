#!/usr/bin/env python3
"""Settle fixed 100-yuan strategy snapshots against official Sporttery results.

This module deliberately scores only persisted recommendation rows.  It never
reconstructs an old plan from current odds, and it never treats a missing
half-time score as a loss for HAFU.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


HAFU_LABELS = ("胜胜", "胜平", "胜负", "平胜", "平平", "平负", "负胜", "负平", "负负")


def _num(value: Any) -> float | None:
    try:
        n = float(value)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def _score(blob: dict[str, Any] | None) -> tuple[int, int] | None:
    if not isinstance(blob, dict):
        return None
    try:
        home, away = int(blob["home"]), int(blob["away"])
    except (KeyError, TypeError, ValueError):
        return None
    return (home, away) if home >= 0 and away >= 0 else None


def _had(score: tuple[int, int]) -> str:
    return "胜" if score[0] > score[1] else "负" if score[0] < score[1] else "平"


def _ttg(score: tuple[int, int]) -> str:
    total = sum(score)
    return f"{total}球" if total <= 6 else "7+球"


def _hafu(score_ht: tuple[int, int] | None, score_90: tuple[int, int]) -> str | None:
    if score_ht is None:
        return None
    return _had(score_ht) + _had(score_90)


def _crs(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).replace("：", ":").replace("-", ":")


def _actual(market: str, result: dict[str, Any]) -> tuple[str | None, str | None]:
    score_90 = _score(result.get("score_90"))
    if score_90 is None:
        return None, "missing_verified_score_90"
    market = str(market or "").upper()
    if market == "HAD":
        return _had(score_90), None
    if market == "TTG":
        return _ttg(score_90), None
    if market == "CRS":
        return f"{score_90[0]}:{score_90[1]}", None
    if market == "HAFU":
        actual = _hafu(_score(result.get("score_ht")), score_90)
        return (actual, None) if actual else (None, "missing_verified_score_ht")
    return None, "unsupported_market"


def _result_index(results_root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not results_root.is_dir():
        return out
    for path in sorted(results_root.glob("sporttery-*.json")):
        try:
            blob = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        match_id = str(blob.get("match_id") or path.stem)
        out[match_id] = blob
    return out


def _score_row(row: dict[str, Any], results: dict[str, dict[str, Any]], *, combo_id: str | None = None) -> dict[str, Any]:
    match_id = str(row.get("match_id") or "")
    market = str(row.get("market") or "").upper()
    selection = str(row.get("selection") or "")
    odds = _num(row.get("odds"))
    stake = _num(row.get("stake_amount")) or 0.0
    result = results.get(match_id)
    # Keep human-readable fixture identity in the persisted strategy record;
    # match_id remains the settlement key, but the workbench must not force
    # users to decode IDs to understand which teams were recommended.
    base = {"match_id": match_id, "match_num": row.get("match_num"),
            "home": row.get("home"), "away": row.get("away"),
            "kickoff": row.get("kickoff"), "market": market,
            "selection": selection, "stake_amount": stake, "odds": odds,
            "combo_id": combo_id}
    if not match_id or odds is None or odds <= 1 or stake <= 0:
        return {**base, "status": "void", "reason": "malformed_recommendation"}
    if not result:
        return {**base, "status": "pending", "reason": "result_not_available"}
    actual, reason = _actual(market, result)
    if actual is None:
        return {**base, "status": "pending", "reason": reason}
    won = actual == (_crs(selection) if market == "CRS" else selection)
    return {**base, "actual": actual, "status": "won" if won else "lost",
            "return_amount": round(stake * odds, 2) if won else 0.0,
            "profit": round(stake * (odds - 1), 2) if won else round(-stake, 2),
            "result_source": (result.get("source") or {}).get("name", "Sporttery official")}


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [r for r in rows if r.get("status") in {"won", "lost"}]
    pending = [r for r in rows if r.get("status") == "pending"]
    committed = sum(float(r.get("stake_amount") or 0) for r in rows if r.get("status") != "void")
    settled_stake = sum(float(r.get("stake_amount") or 0) for r in settled)
    pending_stake = sum(float(r.get("stake_amount") or 0) for r in pending)
    returned = sum(float(r.get("return_amount") or 0) for r in settled)
    profit = sum(float(r.get("profit") or 0) for r in settled)
    return {"recommendation_count": len(rows), "settled_count": len(settled),
            "pending_count": len(pending), "won_count": sum(r["status"] == "won" for r in settled),
            "lost_count": sum(r["status"] == "lost" for r in settled),
            "committed_stake": round(committed, 2), "settled_stake": round(settled_stake, 2),
            "pending_stake": round(pending_stake, 2), "return_amount": round(returned, 2),
            "profit": round(profit, 2), "roi_pct": round(profit / settled_stake * 100, 2) if settled_stake else None,
            "hit_rate_pct": round(sum(r["status"] == "won" for r in settled) / len(settled) * 100, 2) if settled else None}


def _gate_diagnostics(plan: dict[str, Any]) -> dict[str, Any]:
    """Explain why a persisted plan did or did not contain recommendations.

    A zero-row strategy backtest is otherwise ambiguous: it can mean that no
    plan was generated, or that every market was deliberately blocked.  Keep
    this diagnostic separate from settlement performance so it cannot be
    mistaken for a bet or a return.
    """
    audit = [row for row in plan.get("market_audit") or [] if isinstance(row, dict)]
    reasons = Counter(
        str(reason)
        for row in audit
        for reason in (row.get("block_reasons") or [])
        if reason
    )
    return {
        "market_audit_rows": len(audit),
        "strategy_eligible_rows": sum(row.get("strategy_eligible") is True for row in audit),
        "evidence_gap_rows": sum(row.get("evidence_gap") is True for row in audit),
        "block_reason_counts": dict(sorted(reasons.items())),
    }


def score_plan(plan: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in plan.get("single_purchase_recommendations") or []:
        rows.append(_score_row(row, results))
    for combo in plan.get("combo_purchase_recommendations") or []:
        # Combo legs carry no individual stake; use a sentinel stake solely for
        # validating their market outcome, while the combo stake is settled below.
        legs = [_score_row({**leg, "stake_amount": 1}, results, combo_id=combo.get("combo_id")) for leg in combo.get("legs") or []]
        stake = _num(combo.get("stake_amount")) or 0.0
        odds = _num(combo.get("combined_odds"))
        statuses = {leg["status"] for leg in legs}
        if not legs or stake <= 0 or odds is None or odds <= 1:
            status, reason = "void", "malformed_combo"
        elif "void" in statuses:
            status, reason = "void", "malformed_leg"
        elif "pending" in statuses:
            status, reason = "pending", "leg_result_not_available"
        else:
            status, reason = ("won", None) if all(leg["status"] == "won" for leg in legs) else ("lost", None)
        rows.append({"combo_id": combo.get("combo_id"), "market": "COMBO", "selection": " / ".join(str(x.get("selection")) for x in combo.get("legs") or []),
                     "legs": legs, "stake_amount": stake, "odds": odds, "status": status, "reason": reason,
                     "return_amount": round(stake * odds, 2) if status == "won" else 0.0,
                     "profit": round(stake * (odds - 1), 2) if status == "won" else (-round(stake, 2) if status == "lost" else 0.0)})
    decision = plan.get("decision") or {}
    return {"snapshot_id": plan.get("snapshot_id"), "selected_day": plan.get("selected_day"),
            "plan_generated_at": plan.get("generated_at") or (plan.get("display") or {}).get("decision_time"),
            # Keep recreational budget actions visibly separate from
            # production recommendations in every settlement report.
            "execution_mode": plan.get("execution_mode") or "unknown",
            "production_authorized": plan.get("production_authorized") is True,
            "decision_action": decision.get("action"),
            "summary": _summary(rows), "gate_diagnostics": _gate_diagnostics(plan), "records": rows,
            "settlement_basis": "Sporttery official result, 90-minute score; HAFU requires verified half-time score"}


def build_report(plans: list[dict[str, Any]], results_root: Path) -> dict[str, Any]:
    results = _result_index(results_root)
    daily = [score_plan(plan, results) for plan in plans]
    daily.sort(key=lambda x: str(x.get("selected_day") or ""))
    records = [row for day in daily for row in day["records"]]
    total = _summary(records)
    gate_rows = [day.get("gate_diagnostics") or {} for day in daily]
    total_gate_reasons = Counter()
    for row in gate_rows:
        total_gate_reasons.update(row.get("block_reason_counts") or {})
    total["gate_diagnostics"] = {
        "market_audit_rows": sum(int(row.get("market_audit_rows") or 0) for row in gate_rows),
        "strategy_eligible_rows": sum(int(row.get("strategy_eligible_rows") or 0) for row in gate_rows),
        "evidence_gap_rows": sum(int(row.get("evidence_gap_rows") or 0) for row in gate_rows),
        "block_reason_counts": dict(sorted(total_gate_reasons.items())),
    }
    return {"schema_version": "1.0", "generated_at": datetime.now().astimezone().isoformat(),
            "snapshot_count": len(daily), "daily": daily, "summary": total,
            "note": "历史策略回测仅覆盖已持久化的每日推荐快照，不代表未来收益。"}


def load_plans(directory: Path, from_day: str | None = None, to_day: str | None = None) -> list[dict[str, Any]]:
    plans = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            plan = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        day = str(plan.get("selected_day") or path.stem)
        if (from_day and day < from_day) or (to_day and day > to_day):
            continue
        plans.append(plan)
    return plans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans-dir", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--from-day")
    parser.add_argument("--to-day")
    args = parser.parse_args()
    report = build_report(load_plans(args.plans_dir, args.from_day, args.to_day), args.results_root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
